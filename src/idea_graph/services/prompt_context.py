"""Prompt context models, validation, and builder."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from pydantic import BaseModel, Field, field_validator

from idea_graph.db import Neo4jConnection
from idea_graph.services.analysis import AnalysisResult, PathEdge, PathNode, RankedPath

logger = logging.getLogger(__name__)

ALLOWED_SCOPES = {"path", "k_hop", "path_plus_k_hop"}
ALLOWED_PAPER_FIELDS = {
    "paper_title",
    "paper_summary",
    "paper_claims",
}
ALLOWED_ENTITY_FIELDS = {
    "entity_type",
    "entity_description",
}
ALLOWED_EDGE_FIELDS_BY_TYPE = {
    "CITES": {"type", "citation_type", "importance_score", "context"},
    "MENTIONS": {"type", "context"},
    "USES": {"type", "context"},
    "EXTENDS": {"type", "context"},
    "COMPARES": {"type", "context"},
    "ENABLES": {"type", "context"},
    "IMPROVES": {"type", "context"},
    "ADDRESSES": {"type", "context"},
}
ALLOWED_EDGE_TYPES = set(ALLOWED_EDGE_FIELDS_BY_TYPE.keys())
ALLOWED_GRAPH_FORMATS = {"mermaid", "paths"}
MERMAID_UNSAFE_CHARS = set('\"\'[](){}|<>`:;`')
MERMAID_MAX_LABEL_LINES = 6
MERMAID_MAX_LINE_LENGTH = 80
MERMAID_MAX_LABEL_LENGTH = 200
MERMAID_REMOVAL_RATIO_THRESHOLD = 0.4


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


class PromptExpansionOptions(BaseModel):
    """Prompt expansion configuration."""

    graph_format: str = Field(default="mermaid")
    scope: str = Field(default="path")
    node_type_fields: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "Paper": sorted(ALLOWED_PAPER_FIELDS),
            "Entity": sorted(ALLOWED_ENTITY_FIELDS),
        }
    )
    edge_type_fields: dict[str, list[str]] = Field(
        default_factory=lambda: {edge_type: sorted(fields) for edge_type, fields in ALLOWED_EDGE_FIELDS_BY_TYPE.items()}
    )
    max_paths: int = Field(default=5)
    max_nodes: int = Field(default=50)
    max_edges: int = Field(default=100)
    neighbor_k: int = Field(default=2)
    include_inline_edges: bool = Field(default=True)

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        if value not in ALLOWED_SCOPES:
            raise ValueError(f"Invalid scope: {value}")
        return value

    @field_validator("graph_format")
    @classmethod
    def validate_graph_format(cls, value: str) -> str:
        if value not in ALLOWED_GRAPH_FORMATS:
            raise ValueError(f"Invalid graph_format: {value}")
        return value

    @field_validator("node_type_fields")
    @classmethod
    def validate_node_type_fields(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise ValueError("node_type_fields must be a dict")
        cleaned: dict[str, list[str]] = {}
        for node_type, fields in value.items():
            if not isinstance(node_type, str) or not node_type.strip():
                raise ValueError("node_type_fields keys must be non-empty strings")
            if not isinstance(fields, list):
                raise ValueError("node_type_fields values must be lists")
            allowed = ALLOWED_PAPER_FIELDS if node_type == "Paper" else ALLOWED_ENTITY_FIELDS
            invalid = [item for item in fields if item not in allowed]
            if invalid:
                raise ValueError(f"Invalid node_type_fields for {node_type}: {invalid}")
            cleaned[node_type] = _dedupe(fields)
        return cleaned

    @field_validator("edge_type_fields")
    @classmethod
    def validate_edge_type_fields(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if not isinstance(value, dict):
            raise ValueError("edge_type_fields must be a dict")
        cleaned: dict[str, list[str]] = {}
        for edge_type, fields in value.items():
            if edge_type not in ALLOWED_EDGE_TYPES:
                raise ValueError(f"Invalid edge_type_fields type: {edge_type}")
            if not isinstance(fields, list):
                raise ValueError("edge_type_fields values must be lists")
            allowed = ALLOWED_EDGE_FIELDS_BY_TYPE[edge_type]
            invalid = [item for item in fields if item not in allowed]
            if invalid:
                raise ValueError(f"Invalid edge_type_fields for {edge_type}: {invalid}")
            cleaned[edge_type] = _dedupe(fields)
        return cleaned

    @field_validator("max_paths", "max_nodes", "max_edges", "neighbor_k")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than 0")
        return value


class PromptContextNode(BaseModel):
    """Expanded node information for prompt context."""

    id: str
    label: str
    name: str
    title: str | None = None
    summary: str | None = None
    claims: list[str] | None = None
    entity_type: str | None = None
    description: str | None = None
    published_date: datetime | None = None


@dataclass(frozen=True)
class MergedNode:
    id: str
    label: str
    name: str
    details: dict[str, str]


@dataclass(frozen=True)
class MergedEdge:
    from_id: str
    to_id: str
    edge_type: str
    details: dict[str, str]


@dataclass
class MermaidSanitizeStats:
    removed_chars: int = 0
    unsafe_label_count: int = 0


class PromptContextBuilder:
    """Build prompt context from analysis results and graph lookups."""

    def build_context(
        self,
        target_paper_id: str,
        analysis_result: AnalysisResult,
        options: PromptExpansionOptions | None = None,
    ) -> str:
        opts = options or PromptExpansionOptions()
        paths = self._select_paths(target_paper_id, analysis_result, opts)
        paths = self._filter_paths(paths, opts, target_paper_id)
        if opts.graph_format == "paths":
            return self._build_paths_context(paths, opts)
        return self._build_mermaid_context(paths, opts)

    def _build_paths_context(self, paths: list[RankedPath], options: PromptExpansionOptions) -> str:
        lines: list[str] = []
        if paths:
            lines.append("### Graph Paths")
            for idx, path in enumerate(paths, 1):
                formatted = self._format_path(path, options)
                if formatted:
                    lines.append(f"{idx}. {formatted}")

        if self._has_node_fields(options):
            nodes = self._collect_nodes(paths, options.max_nodes)
            details = self._format_node_details(nodes, options)
            if details:
                if lines:
                    lines.append("")
                lines.append("### Node Details")
                lines.extend(details)

        return "\n".join(lines).strip()

    def _build_mermaid_context(self, paths: list[RankedPath], options: PromptExpansionOptions) -> str:
        if not paths:
            return ""

        try:
            nodes = self._collect_nodes(paths, options.max_nodes)
            merged_nodes = self._merge_nodes(nodes, options)
            if not merged_nodes:
                return ""

            merged_edges = self._merge_edges(paths, options)

            node_ids = {node.id for node in merged_nodes}
            filtered_edges: list[MergedEdge] = []
            for edge in merged_edges:
                if edge.from_id not in node_ids or edge.to_id not in node_ids:
                    logger.warning(
                        "Skipping mermaid edge with missing nodes: %s -> %s (%s)",
                        edge.from_id,
                        edge.to_id,
                        edge.edge_type,
                    )
                    continue
                filtered_edges.append(edge)

            filtered_edges = sorted(
                filtered_edges,
                key=lambda edge: (edge.from_id, edge.to_id, edge.edge_type),
            )
            if len(filtered_edges) > options.max_edges:
                logger.warning("Reached max_edges limit (%s); truncating mermaid edges.", options.max_edges)
                filtered_edges = filtered_edges[: options.max_edges]

            merged_nodes = sorted(merged_nodes, key=lambda node: node.id)
            id_map = {node.id: f"N{idx}" for idx, node in enumerate(merged_nodes, 1)}

            stats = MermaidSanitizeStats()
            mermaid_lines = ["```mermaid", "graph LR"]

            for node in merged_nodes:
                label = self._build_mermaid_node_label(node, stats)
                if not label:
                    stats.unsafe_label_count += 1
                    continue
                mermaid_lines.append(f'  {id_map[node.id]}["{label}"]')

            if stats.unsafe_label_count:
                logger.warning(
                    "Mermaid label sanitization triggered fallback (%s unsafe labels).",
                    stats.unsafe_label_count,
                )
                return self._build_paths_context(paths, options)

            for edge in filtered_edges:
                label = self._build_mermaid_edge_label(edge, options, stats)
                from_id = id_map.get(edge.from_id)
                to_id = id_map.get(edge.to_id)
                if not from_id or not to_id:
                    continue
                if label:
                    mermaid_lines.append(f"  {from_id} -- {label} --> {to_id}")
                else:
                    mermaid_lines.append(f"  {from_id} --> {to_id}")

            if stats.removed_chars:
                logger.warning(
                    "Mermaid label sanitization removed %s characters.",
                    stats.removed_chars,
                )

            mermaid_lines.append("```")
            return "\n".join(mermaid_lines)
        except Exception as exc:
            logger.warning("Mermaid generation failed; fallback to paths: %s", exc)
            return self._build_paths_context(paths, options)

    def _select_paths(
        self,
        target_paper_id: str,
        analysis_result: AnalysisResult,
        options: PromptExpansionOptions,
    ) -> list[RankedPath]:
        paths: list[RankedPath] = []

        if options.scope in {"path", "path_plus_k_hop"}:
            paths.extend(analysis_result.candidates[: options.max_paths])

        if options.scope in {"k_hop", "path_plus_k_hop"}:
            try:
                k_hop_paths = self._fetch_k_hop_paths(
                    target_paper_id,
                    options.neighbor_k,
                    options.max_paths,
                    options.max_edges,
                )
                paths.extend(k_hop_paths)
            except Exception as exc:
                logger.warning("Failed to fetch k-hop paths: %s", exc)

        return paths

    def _filter_paths(
        self,
        paths: list[RankedPath],
        options: PromptExpansionOptions,
        target_paper_id: str,
    ) -> list[RankedPath]:
        if not paths:
            return []

        paper_ids = self._collect_paper_ids(paths)
        paper_ids.add(target_paper_id)
        published_dates = self._fetch_paper_published_dates(list(paper_ids))
        target_published_date = published_dates.get(target_paper_id)
        future_paper_ids: set[str] = set()

        if target_published_date:
            for paper_id, published_date in published_dates.items():
                if published_date and published_date > target_published_date:
                    future_paper_ids.add(paper_id)
        else:
            logger.warning("Target paper published_date not found; skipping future paper filter.")

        excluded_node_ids = set(future_paper_ids)
        # Exclude the target paper from prompt context to avoid leaking it via graph paths.
        excluded_node_ids.add(target_paper_id)

        filtered: list[RankedPath] = []
        for path in paths:
            filtered_path = self._filter_path(path, options, excluded_node_ids)
            if filtered_path and filtered_path.nodes:
                filtered.append(filtered_path)
        return filtered

    def _filter_path(
        self,
        path: RankedPath,
        options: PromptExpansionOptions,
        excluded_node_ids: set[str],
    ) -> RankedPath | None:
        kept_nodes: list[PathNode] = []
        kept_node_ids: set[str] = set()
        for node in path.nodes:
            if node.id in excluded_node_ids:
                continue
            node_type = self._resolve_node_type(node)
            if not self._is_node_type_included(node_type, options):
                continue
            kept_nodes.append(node)
            kept_node_ids.add(node.id)

        # A "path" with fewer than 2 nodes is not useful in prompt context and is usually
        # a symptom of upstream filtering/limits.
        if len(kept_nodes) < 2:
            return None

        kept_edges: list[PathEdge] = []
        for edge in path.edges:
            edge_fields = self._edge_fields_for_type(edge.type, options)
            if not edge_fields:
                continue
            if edge.from_id not in kept_node_ids or edge.to_id not in kept_node_ids:
                continue
            kept_edges.append(edge)

        # If filtering removed any intermediate node/edge, the remaining nodes no longer form a
        # valid linear path. Drop it rather than outputting a degenerate "node-only" path.
        if len(kept_edges) != len(kept_nodes) - 1:
            if options.graph_format == "mermaid":
                logger.warning("Mermaid path edge mismatch; omitting edges for path.")
                return RankedPath(
                    nodes=kept_nodes,
                    edges=[],
                    score=path.score,
                    score_breakdown=getattr(path, "score_breakdown", None),
                )
            return None

        return RankedPath(
            nodes=kept_nodes,
            edges=kept_edges,
            score=path.score,
            score_breakdown=getattr(path, "score_breakdown", None),
        )

    def _collect_paper_ids(self, paths: list[RankedPath]) -> set[str]:
        return {
            node.id
            for path in paths
            for node in path.nodes
            if node.label == "Paper"
        }

    def _fetch_paper_published_dates(self, paper_ids: list[str]) -> dict[str, datetime | None]:
        if not paper_ids:
            return {}
        published_dates: dict[str, datetime | None] = {}
        try:
            with Neo4jConnection.session() as session:
                result = session.run(
                    "MATCH (p:Paper) WHERE p.id IN $ids "
                    "RETURN p.id AS id, p.published_date AS published_date",
                    ids=paper_ids,
                )
                for record in result:
                    published_dates[record["id"]] = self._parse_published_date(
                        record.get("published_date")
                    )
        except Exception as exc:
            logger.warning("Failed to fetch published_date: %s", exc)
        return published_dates

    def _has_node_fields(self, options: PromptExpansionOptions) -> bool:
        return any(fields for fields in options.node_type_fields.values())

    def _resolve_node_type(self, node: PathNode | PromptContextNode) -> str:
        if node.label == "Paper":
            return "Paper"
        return node.entity_type or "Entity"

    def _node_fields_for_type(self, node_type: str, options: PromptExpansionOptions) -> list[str]:
        if node_type in options.node_type_fields:
            return options.node_type_fields[node_type]
        if node_type != "Paper" and "Entity" in options.node_type_fields:
            return options.node_type_fields["Entity"]
        return []

    def _is_node_type_included(self, node_type: str, options: PromptExpansionOptions) -> bool:
        return bool(self._node_fields_for_type(node_type, options))

    def _edge_fields_for_type(self, edge_type: str, options: PromptExpansionOptions) -> list[str]:
        return options.edge_type_fields.get(edge_type, [])

    def _fetch_k_hop_paths(
        self,
        target_paper_id: str,
        neighbor_k: int,
        max_paths: int,
        max_edges: int,
    ) -> list[RankedPath]:
        paths: list[RankedPath] = []
        query = (
            "MATCH path = (target:Paper {id: $target_id})-[rels*1.."
            + str(neighbor_k)
            + "]->(n) "
            "WHERE (n:Paper OR n:Entity) "
            "RETURN nodes(path) AS nodes, rels AS rels "
            "LIMIT $limit"
        )

        edge_count = 0
        with Neo4jConnection.session() as session:
            result = session.run(
                query,
                target_id=target_paper_id,
                limit=max_paths,
            )
            for record in result:
                path_nodes = self._nodes_from_records(record["nodes"])
                path_edges = self._edges_from_records(record["rels"], record["nodes"])
                if edge_count + len(path_edges) > max_edges:
                    logger.warning("Reached max_edges limit (%s); truncating k-hop paths.", max_edges)
                    break
                edge_count += len(path_edges)
                paths.append(RankedPath(nodes=path_nodes, edges=path_edges, score=0.0))

        return paths

    def _nodes_from_records(self, nodes) -> list[PathNode]:
        path_nodes: list[PathNode] = []
        for node in nodes:
            labels = list(getattr(node, "labels", []))
            label = labels[0] if labels else "Unknown"
            if "Paper" in labels:
                name = node.get("title", node.get("id", "Unknown"))
                path_nodes.append(
                    PathNode(
                        id=node.get("id", node.element_id),
                        label=label,
                        name=name,
                    )
                )
            else:
                name = node.get("name", node.get("id", "Unknown"))
                path_nodes.append(
                    PathNode(
                        id=node.get("id", node.element_id),
                        label=label,
                        name=name,
                        entity_type=node.get("type"),
                        description=node.get("description"),
                    )
                )
        return path_nodes

    def _edges_from_records(self, rels, nodes) -> list[PathEdge]:
        edges: list[PathEdge] = []
        for idx, rel in enumerate(rels):
            if idx + 1 >= len(nodes):
                break
            from_node = nodes[idx]
            to_node = nodes[idx + 1]
            edges.append(
                PathEdge(
                    type=rel.type,
                    from_id=from_node.get("id", from_node.element_id),
                    to_id=to_node.get("id", to_node.element_id),
                    importance_score=rel.get("importance_score") if rel.type == "CITES" else None,
                    citation_type=rel.get("citation_type") if rel.type == "CITES" else None,
                    context=rel.get("context") if rel.type == "CITES" else None,
                )
            )
        return edges

    def _format_path(self, path: RankedPath, options: PromptExpansionOptions) -> str:
        if not path.nodes:
            return ""
        if not options.include_inline_edges or not path.edges:
            return " -> ".join(node.name for node in path.nodes)

        output = path.nodes[0].name
        for idx, edge in enumerate(path.edges):
            if idx + 1 >= len(path.nodes):
                break
            edge_fields = self._edge_fields_for_type(edge.type, options)
            edge_label = edge.type if "type" in edge_fields else ""
            extra = self._format_edge_details(edge, edge_fields)
            if extra:
                edge_label = f"{edge_label}{extra}" if edge_label else extra
            if edge_label:
                output += f" -({edge_label})-> {path.nodes[idx + 1].name}"
            else:
                output += f" -> {path.nodes[idx + 1].name}"
        return output

    def _format_edge_details(self, edge: PathEdge, edge_fields: list[str]) -> str:
        details: list[str] = []
        if "citation_type" in edge_fields and edge.citation_type:
            details.append(f"citation_type={edge.citation_type}")
        if "importance_score" in edge_fields and edge.importance_score is not None:
            details.append(f"importance_score={edge.importance_score}")
        if "context" in edge_fields and edge.context:
            details.append(f"context={edge.context}")
        if not details:
            return ""
        return "{" + ", ".join(details) + "}"

    def _merge_nodes(
        self,
        nodes: list[PromptContextNode],
        options: PromptExpansionOptions,
    ) -> list[MergedNode]:
        merged: list[MergedNode] = []
        for node in nodes:
            node_type = self._resolve_node_type(node)
            fields = self._node_fields_for_type(node_type, options)
            if not fields:
                continue
            details: dict[str, str] = {}
            if node.label == "Paper":
                if "paper_title" in fields and node.title and node.title != node.name:
                    details["Title"] = node.title
                if "paper_summary" in fields and node.summary:
                    details["Summary"] = node.summary
                if "paper_claims" in fields and node.claims:
                    details["Claims"] = ", ".join(node.claims)
            else:
                if "entity_type" in fields and node.entity_type:
                    details["Type"] = node.entity_type
                if "entity_description" in fields and node.description:
                    details["Description"] = node.description
            merged.append(
                MergedNode(
                    id=node.id,
                    label=node.label,
                    name=node.name,
                    details=details,
                )
            )
        return merged

    def _merge_edges(
        self,
        paths: list[RankedPath],
        options: PromptExpansionOptions,
    ) -> list[MergedEdge]:
        merged: list[MergedEdge] = []
        seen: set[tuple[str, str, str]] = set()
        for path in paths:
            if path.edges and len(path.edges) != len(path.nodes) - 1:
                logger.warning("Mermaid path edge mismatch; omitting edges for path.")
                continue
            for edge in path.edges:
                edge_fields = self._edge_fields_for_type(edge.type, options)
                if not edge_fields:
                    continue
                key = (edge.from_id, edge.to_id, edge.type)
                if key in seen:
                    continue
                seen.add(key)
                details: dict[str, str] = {}
                if "citation_type" in edge_fields and edge.citation_type:
                    details["citation_type"] = str(edge.citation_type)
                if "importance_score" in edge_fields and edge.importance_score is not None:
                    details["importance_score"] = str(edge.importance_score)
                if "context" in edge_fields and edge.context:
                    details["context"] = str(edge.context)
                merged.append(
                    MergedEdge(
                        from_id=edge.from_id,
                        to_id=edge.to_id,
                        edge_type=edge.type,
                        details=details,
                    )
                )
        return merged

    def _sanitize_mermaid_text(self, value: str, stats: MermaidSanitizeStats) -> tuple[str, bool]:
        if value is None:
            return "", True
        text = str(value)
        removed = 0
        cleaned: list[str] = []
        for ch in text:
            if ch in MERMAID_UNSAFE_CHARS or ch in {"\n", "\r", "\t"}:
                removed += 1
                cleaned.append(" ")
                continue
            if unicodedata.category(ch) in {"Cc", "Cf"}:
                removed += 1
                continue
            cleaned.append(ch)
        sanitized = re.sub(r"\s+", " ", "".join(cleaned)).strip()
        stats.removed_chars += removed
        if not sanitized:
            return "", True
        ratio = removed / max(1, len(text))
        return sanitized, ratio > MERMAID_REMOVAL_RATIO_THRESHOLD

    def _truncate_mermaid_label(self, text: str, max_length: int) -> str:
        if len(text) <= max_length:
            return text
        if max_length <= 3:
            return text[:max_length]
        return text[: max_length - 3].rstrip() + "..."

    def _build_mermaid_node_label(
        self,
        node: MergedNode,
        stats: MermaidSanitizeStats,
    ) -> str:
        raw_lines = [node.name]
        for key, value in node.details.items():
            raw_lines.append(f"{key}={value}")

        safe_lines: list[str] = []
        unsafe = False
        for raw in raw_lines[:MERMAID_MAX_LABEL_LINES]:
            sanitized, removed_too_much = self._sanitize_mermaid_text(raw, stats)
            if removed_too_much:
                unsafe = True
            if not sanitized:
                continue
            sanitized = self._truncate_mermaid_label(sanitized, MERMAID_MAX_LINE_LENGTH)
            safe_lines.append(sanitized)

        if not safe_lines:
            return ""
        if unsafe:
            stats.unsafe_label_count += 1
        label = "<br/>".join(safe_lines)
        return self._truncate_mermaid_label(label, MERMAID_MAX_LABEL_LENGTH)

    def _build_mermaid_edge_label(
        self,
        edge: MergedEdge,
        options: PromptExpansionOptions,
        stats: MermaidSanitizeStats,
    ) -> str:
        edge_fields = self._edge_fields_for_type(edge.edge_type, options)
        raw_lines: list[str] = []
        if "type" in edge_fields:
            raw_lines.append(edge.edge_type)
        for key, value in edge.details.items():
            raw_lines.append(f"{key}={value}")

        safe_lines: list[str] = []
        for raw in raw_lines[:MERMAID_MAX_LABEL_LINES]:
            sanitized, _removed_too_much = self._sanitize_mermaid_text(raw, stats)
            if not sanitized:
                continue
            sanitized = self._truncate_mermaid_label(sanitized, MERMAID_MAX_LINE_LENGTH)
            safe_lines.append(sanitized)

        if not safe_lines:
            return ""
        label = "<br/>".join(safe_lines)
        return self._truncate_mermaid_label(label, MERMAID_MAX_LABEL_LENGTH)

    def _collect_nodes(self, paths: list[RankedPath], max_nodes: int) -> list[PromptContextNode]:
        seen: set[str] = set()
        ordered: list[PathNode] = []
        for path in paths:
            for node in path.nodes:
                if node.id in seen:
                    continue
                seen.add(node.id)
                ordered.append(node)
                if len(ordered) >= max_nodes:
                    logger.warning("Reached max_nodes limit (%s); truncating node details.", max_nodes)
                    break
            if len(ordered) >= max_nodes:
                break

        return self._fetch_node_details(ordered)

    def _fetch_node_details(self, nodes: list[PathNode]) -> list[PromptContextNode]:
        if not nodes:
            return []

        paper_ids = [node.id for node in nodes if node.label == "Paper"]
        entity_ids = [node.id for node in nodes if node.label != "Paper"]

        paper_details: dict[str, dict[str, object]] = {}
        entity_details: dict[str, dict[str, object]] = {}

        try:
            with Neo4jConnection.session() as session:
                if paper_ids:
                    result = session.run(
                        "MATCH (p:Paper) WHERE p.id IN $ids "
                        "RETURN p.id AS id, p.title AS title, p.summary AS summary, "
                        "p.claims AS claims, p.published_date AS published_date",
                        ids=paper_ids,
                    )
                    for record in result:
                        published_date = self._parse_published_date(record.get("published_date"))
                        paper_details[record["id"]] = {
                            "title": record.get("title"),
                            "summary": record.get("summary"),
                            "claims": record.get("claims"),
                            "published_date": published_date,
                        }
                if entity_ids:
                    result = session.run(
                        "MATCH (e:Entity) WHERE e.id IN $ids "
                        "RETURN e.id AS id, e.name AS name, e.type AS type, e.description AS description",
                        ids=entity_ids,
                    )
                    for record in result:
                        entity_details[record["id"]] = {
                            "name": record.get("name"),
                            "type": record.get("type"),
                            "description": record.get("description"),
                        }
        except Exception as exc:
            logger.warning("Failed to fetch node details: %s", exc)

        expanded: list[PromptContextNode] = []
        for node in nodes:
            if node.label == "Paper":
                details = paper_details.get(node.id, {})
                expanded.append(
                    PromptContextNode(
                        id=node.id,
                        label=node.label,
                        name=node.name,
                        title=details.get("title"),
                        summary=details.get("summary"),
                        claims=details.get("claims"),
                        published_date=details.get("published_date"),
                    )
                )
            else:
                details = entity_details.get(node.id, {})
                expanded.append(
                    PromptContextNode(
                        id=node.id,
                        label=node.label,
                        name=details.get("name") or node.name,
                        entity_type=details.get("type") or node.entity_type,
                        description=details.get("description") or node.description,
                    )
                )
        return expanded

    def _parse_published_date(self, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            logger.warning("Invalid published_date format: %s", value)
            return None

    def _format_node_details(
        self,
        nodes: list[PromptContextNode],
        options: PromptExpansionOptions,
    ) -> list[str]:
        lines: list[str] = []
        for node in nodes:
            node_type = self._resolve_node_type(node)
            fields = self._node_fields_for_type(node_type, options)
            if not fields:
                continue
            lines.append(f"- {node.name} ({node.label})")
            if "paper_title" in fields and node.title:
                lines.append(f"  - Title: {node.title}")
            if "paper_summary" in fields and node.summary:
                lines.append(f"  - Summary: {node.summary}")
            if "paper_claims" in fields and node.claims:
                lines.append(f"  - Claims: {', '.join(node.claims)}")
            if "entity_type" in fields and node.entity_type:
                lines.append(f"  - Type: {node.entity_type}")
            if "entity_description" in fields and node.description:
                lines.append(f"  - Description: {node.description}")
        return lines
