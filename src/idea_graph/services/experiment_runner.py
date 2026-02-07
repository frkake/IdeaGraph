"""実験オーケストレーションサービス"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.models.experiment import (
    AnalysisConfig,
    ConditionConfig,
    ExperimentConfig,
    MethodType,
    PaperSelectionStrategy,
    PromptConfig,
    load_experiment_config,
)
from idea_graph.services.analysis import AnalysisService
from idea_graph.services.coi_converter import CoIConverter
from idea_graph.services.coi_runner import CoIRunner
from idea_graph.services.evaluation import EvaluationService
from idea_graph.services.experiment_cache import ExperimentCache
from idea_graph.services.proposal import Proposal, ProposalResult, ProposalService

logger = logging.getLogger(__name__)


class PaperRunRecord(BaseModel):
    paper_id: str
    condition: str
    method: MethodType
    proposals_file: str
    single_evaluation_file: str | None = None


class PairwiseRunRecord(BaseModel):
    paper_id: str
    file: str


class SkippedPaperRecord(BaseModel):
    paper_id: str
    condition: str
    method: MethodType
    reason: str


class ExperimentRunSummary(BaseModel):
    run_id: str
    experiment_id: str
    config_file: str
    run_dir: str
    started_at: str
    completed_at: str | None = None
    target_papers: list[str] = Field(default_factory=list)
    records: list[PaperRunRecord] = Field(default_factory=list)
    pairwise_records: list[PairwiseRunRecord] = Field(default_factory=list)
    skipped_records: list[SkippedPaperRecord] = Field(default_factory=list)


class ExperimentRunner:
    """PLAN.md準拠の実験実行サービス"""

    def __init__(self, no_cache: bool = False) -> None:
        self._analysis_service = AnalysisService()
        self._cache = ExperimentCache()
        self._no_cache = no_cache

    # ──────────────────────────── ユーティリティ ────────────────────────────

    def _resolve_run_dir(self, config: ExperimentConfig) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_id = f"{config.experiment.id}_{timestamp}"
        return Path(config.output.base_dir) / run_id

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _save_yaml(self, path: Path, payload: dict[str, Any]) -> None:
        import yaml

        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def _git_hash(self) -> str | None:
        try:
            out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True)
            return out.strip()
        except Exception:
            return None

    def _neo4j_stats(self) -> dict[str, int]:
        stats: dict[str, int] = {}
        with Neo4jConnection.session() as session:
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()
            edge_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
            paper_count = session.run("MATCH (p:Paper) RETURN count(p) AS c").single()
            entity_count = session.run("MATCH (e:Entity) RETURN count(e) AS c").single()
            stats["nodes"] = int(node_count["c"]) if node_count else 0
            stats["edges"] = int(edge_count["c"]) if edge_count else 0
            stats["paper_nodes"] = int(paper_count["c"]) if paper_count else 0
            stats["entity_nodes"] = int(entity_count["c"]) if entity_count else 0
        return stats

    def _fetch_paper_title(self, paper_id: str) -> str | None:
        with Neo4jConnection.session() as session:
            record = session.run(
                "MATCH (p:Paper {id: $paper_id}) RETURN p.title AS title",
                paper_id=paper_id,
            ).single()
            if not record:
                return None
            title = record.get("title")
            return title if isinstance(title, str) and title.strip() else None

    def _query_papers(self, query: str, params: dict[str, Any]) -> list[str]:
        with Neo4jConnection.session() as session:
            return [str(row["id"]) for row in session.run(query, **params) if row.get("id")]

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _hash_dict(d: Any) -> str:
        raw = json.dumps(d, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    # ──────────────────────────── ターゲット論文選定 ────────────────────────────

    def _select_target_papers(self, config: ExperimentConfig, limit: int | None) -> list[str]:
        target_count = limit if limit is not None else config.targets.count
        target_count = max(1, target_count)

        if config.targets.paper_ids:
            return config.targets.paper_ids[:target_count]

        strategy = config.targets.selection_strategy
        random.seed(config.seed.paper_selection)

        if strategy == PaperSelectionStrategy.MANUAL:
            raise ValueError("targets.paper_ids is empty for manual selection strategy")
        if strategy == PaperSelectionStrategy.RANDOM:
            all_ids = self._query_papers(
                "MATCH (p:Paper) RETURN p.id AS id",
                {},
            )
            random.shuffle(all_ids)
            return all_ids[:target_count]
        if strategy == PaperSelectionStrategy.TOP_CITED:
            return self._query_papers(
                """
                MATCH (p:Paper)
                OPTIONAL MATCH ()-[r:CITES]->(p)
                WITH p, count(r) AS c
                RETURN p.id AS id
                ORDER BY c DESC
                LIMIT $limit
                """,
                {"limit": target_count},
            )
        if strategy == PaperSelectionStrategy.CONNECTIVITY:
            return self._query_papers(
                """
                MATCH (p:Paper)
                OPTIONAL MATCH (p)-[r]->()
                WITH p, count(r) AS degree
                WHERE degree > 0
                RETURN p.id AS id
                ORDER BY degree DESC
                LIMIT $limit
                """,
                {"limit": target_count},
            )

        # connectivity_stratified
        with Neo4jConnection.session() as session:
            rows = list(
                session.run(
                    """
                    MATCH (p:Paper)
                    OPTIONAL MATCH (p)-[r]->()
                    WITH p, count(r) AS degree
                    WHERE degree > 0
                    RETURN p.id AS id, degree
                    ORDER BY degree ASC
                    """
                )
            )

        if not rows:
            return []

        data = [(str(row["id"]), int(row["degree"])) for row in rows if row.get("id")]
        if not data:
            return []
        n = len(data)
        p33_idx = max(0, int((n - 1) * 0.33))
        p66_idx = max(0, int((n - 1) * 0.66))
        sorted_degrees = [d for _, d in data]
        p33 = sorted_degrees[p33_idx]
        p66 = sorted_degrees[p66_idx]

        low = [pid for pid, degree in data if degree < p33]
        mid = [pid for pid, degree in data if p33 <= degree < p66]
        high = [pid for pid, degree in data if degree >= p66]

        tier = config.targets.connectivity_tier_filter
        if tier == "low":
            base = low
            random.shuffle(base)
            return base[:target_count]
        if tier == "medium":
            base = mid
            random.shuffle(base)
            return base[:target_count]
        if tier == "high":
            base = high
            random.shuffle(base)
            return base[:target_count]

        per_bucket = max(1, target_count // 3)
        random.shuffle(low)
        random.shuffle(mid)
        random.shuffle(high)
        selected = low[:per_bucket] + mid[:per_bucket] + high[:per_bucket]

        pool = [pid for pid, _ in data if pid not in set(selected)]
        random.shuffle(pool)
        while len(selected) < target_count and pool:
            selected.append(pool.pop())
        return selected[:target_count]

    # ──────────────────────────── 条件別設定解決 ────────────────────────────

    def _resolve_condition_config(
        self,
        config: ExperimentConfig,
        condition: ConditionConfig,
    ) -> tuple[AnalysisConfig, PromptConfig]:
        """条件ごとの analysis/prompt 設定を解決する（条件別 > 実験全体）。"""
        analysis = condition.analysis if condition.analysis is not None else config.analysis
        prompt = condition.prompt if condition.prompt is not None else config.prompt
        return analysis, prompt

    def _prompt_options_from_prompt_config(self, prompt_cfg: PromptConfig) -> dict[str, Any]:
        return {
            "graph_format": prompt_cfg.graph_format,
            "scope": prompt_cfg.scope,
            "max_paths": prompt_cfg.max_paths,
            "max_nodes": prompt_cfg.max_nodes,
            "max_edges": prompt_cfg.max_edges,
            "neighbor_k": prompt_cfg.neighbor_k,
            "include_inline_edges": prompt_cfg.include_inline_edges,
        }

    # ──────────────────────────── 条件実行 ────────────────────────────

    def _run_ideagraph(
        self,
        paper_id: str,
        condition: ConditionConfig,
        config: ExperimentConfig,
    ) -> ProposalResult:
        analysis_cfg, prompt_cfg = self._resolve_condition_config(config, condition)
        prompt_opts = self._prompt_options_from_prompt_config(prompt_cfg)
        prompt_hash = self._hash_dict(prompt_opts)

        # キャッシュ: 分析
        analysis_data = None
        if not self._no_cache:
            analysis_data = self._cache.get("analysis", paper_id, analysis_cfg.max_hops)
        if analysis_data is not None:
            from idea_graph.services.analysis import AnalysisResult as AR
            analysis_result = AR.model_validate(analysis_data)
        else:
            analysis_result = self._analysis_service.analyze(
                target_paper_id=paper_id,
                multihop_k=analysis_cfg.max_hops,
                top_n=analysis_cfg.top_k,
            )
            self._cache.put("analysis", analysis_result.model_dump(mode="json"), paper_id, analysis_cfg.max_hops)

        if not analysis_result.candidates:
            raise ValueError(
                f"Analysis for paper {paper_id} returned no candidates (no outgoing paths)"
            )

        # キャッシュ: 提案
        cache_key_parts = (paper_id, analysis_cfg.max_hops, prompt_hash, condition.generation.model, condition.generation.num_proposals)
        proposal_data = None
        if not self._no_cache:
            proposal_data = self._cache.get("proposals/ideagraph", *cache_key_parts)
        if proposal_data is not None:
            proposal_result = ProposalResult.model_validate(proposal_data)
        else:
            proposal_service = ProposalService(model_name=condition.generation.model)
            proposal_result = proposal_service.propose(
                target_paper_id=paper_id,
                analysis_result=analysis_result,
                num_proposals=condition.generation.num_proposals,
                prompt_options=prompt_opts,
            )
            self._cache.put("proposals/ideagraph", proposal_result.model_dump(mode="json"), *cache_key_parts)

        return proposal_result

    def _run_direct_llm(
        self,
        paper_id: str,
        condition: ConditionConfig,
    ) -> ProposalResult:
        cache_key_parts = (paper_id, condition.generation.model, condition.generation.num_proposals)
        proposal_data = None
        if not self._no_cache:
            proposal_data = self._cache.get("proposals/direct_llm", *cache_key_parts)
        if proposal_data is not None:
            return ProposalResult.model_validate(proposal_data)

        proposal_service = ProposalService(model_name=condition.generation.model)
        result = proposal_service.propose_direct(
            target_paper_id=paper_id,
            num_proposals=condition.generation.num_proposals,
        )
        self._cache.put("proposals/direct_llm", result.model_dump(mode="json"), *cache_key_parts)
        return result

    def _run_coi(
        self,
        paper_id: str,
        condition: ConditionConfig,
    ) -> ProposalResult:
        num_proposals = condition.generation.num_proposals
        cache_key_parts = (paper_id, condition.generation.model, num_proposals)
        proposal_data = None
        if not self._no_cache:
            proposal_data = self._cache.get("proposals/coi", *cache_key_parts)
        if proposal_data is not None:
            return ProposalResult.model_validate(proposal_data)

        paper_title = self._fetch_paper_title(paper_id) or paper_id
        converter = CoIConverter(model_name=condition.generation.model)
        proposals: list[Proposal] = []
        last_prompt: str = ""

        for i in range(num_proposals):
            logger.info("COI run %d/%d for %s", i + 1, num_proposals, paper_id)
            runner = CoIRunner(main_model=condition.generation.model)
            result = asyncio.run(runner.run(topic=paper_title))
            proposal = converter.convert_to_proposal(result)
            proposals.append(proposal)
            last_prompt = result.prompt

        proposal_result = ProposalResult(
            target_paper_id=paper_id,
            proposals=proposals,
            prompt=last_prompt,
        )
        self._cache.put("proposals/coi", proposal_result.model_dump(mode="json"), *cache_key_parts)
        return proposal_result

    # ──────────────────────────── 評価 ────────────────────────────

    def _evaluate_single(
        self,
        proposals: list[Proposal],
        source: MethodType,
        model_name: str,
    ) -> dict[str, Any]:
        service = EvaluationService(model_name=model_name)
        result = service.evaluate_single(
            proposals=proposals,
            proposal_sources=[source.value] * len(proposals),
        )
        return result.model_dump(mode="json")

    def _evaluate_single_repeat(
        self,
        proposals: list[Proposal],
        source: MethodType,
        model_name: str,
        repeat: int,
    ) -> list[dict[str, Any]]:
        """repeat > 1 のとき、同一提案を複数回評価する。"""
        results = []
        for i in range(repeat):
            logger.info("Single evaluation repeat %d/%d", i + 1, repeat)
            results.append(self._evaluate_single(proposals, source, model_name))
        return results

    @staticmethod
    def _get_paper_full_text(paper_id: str) -> str | None:
        """キャッシュから論文の全文テキストを取得する。"""
        import io
        import tarfile

        from idea_graph.ingestion.downloader import FileType

        paper_dir = settings.papers_cache_dir / paper_id
        if not paper_dir.exists():
            logger.warning("Paper directory not found: %s", paper_dir)
            return None

        tar_path = paper_dir / "source.tar.gz"
        pdf_path = paper_dir / "paper.pdf"

        if tar_path.exists():
            file_path = tar_path
            file_type = FileType.LATEX
        elif pdf_path.exists():
            file_path = pdf_path
            file_type = FileType.PDF
        else:
            logger.warning("No paper file found in: %s", paper_dir)
            return None

        if file_type == FileType.LATEX:
            try:
                content = file_path.read_bytes()
                with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                    tex_files = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".tex")]
                    if not tex_files:
                        return None
                    main_file = None
                    for tf in tex_files:
                        name_lower = tf.name.lower()
                        if "main" in name_lower or "paper" in name_lower:
                            main_file = tf
                            break
                    if main_file is None:
                        main_file = max(tex_files, key=lambda x: x.size)
                    f = tar.extractfile(main_file)
                    if f is None:
                        return None
                    text_content = f.read().decode("utf-8", errors="ignore")
                    bbl_files = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".bbl")]
                    if bbl_files:
                        bbl = max(bbl_files, key=lambda x: x.size)
                        bf = tar.extractfile(bbl)
                        if bf is not None:
                            bbl_content = bf.read().decode("utf-8", errors="ignore")
                            text_content = f"{text_content}\n\n{bbl_content}"
                    return text_content
            except Exception as e:
                logger.error("Failed to extract text from LaTeX: %s", e)
                return None
        else:
            extraction_path = settings.extractions_cache_dir / f"{paper_id}.json"
            if extraction_path.exists():
                try:
                    data = json.loads(extraction_path.read_text())
                    summary = data.get("paper_summary", "") or ""
                    claims = data.get("claims", []) or []
                    entities = data.get("entities", []) or []
                    parts = []
                    if summary:
                        parts.append("Paper summary:\n" + summary)
                    if claims:
                        parts.append("Claims:\n- " + "\n- ".join(claims))
                    entity_lines = []
                    for e in entities:
                        name = (e.get("name") or "").strip()
                        e_type = (e.get("type") or "").strip()
                        if name and e_type:
                            entity_lines.append(f"- {name} ({e_type})")
                    if entity_lines:
                        parts.append("Key entities:\n" + "\n".join(entity_lines))
                    return "\n\n".join(parts).strip() if parts else None
                except Exception as e:
                    logger.error("Failed to load extraction cache: %s", e)
                    return None
            return None

    def _evaluate_pairwise(
        self,
        proposal_set: list[tuple[MethodType, Proposal]],
        model_name: str,
        include_experiment: bool,
        include_target: bool = False,
        paper_id: str | None = None,
    ) -> dict[str, Any]:
        service = EvaluationService(model_name=model_name)
        proposals = [proposal for _, proposal in proposal_set]
        sources = [source.value for source, _ in proposal_set]

        target_paper_content: str | None = None
        target_paper_title: str | None = None
        if include_target and paper_id:
            target_paper_content = self._get_paper_full_text(paper_id)
            target_paper_title = self._fetch_paper_title(paper_id)

        result = service.evaluate(
            proposals=proposals,
            include_experiment=include_experiment,
            proposal_sources=sources,
            target_paper_content=target_paper_content,
            target_paper_title=target_paper_title,
            target_paper_id=paper_id if include_target else None,
        )
        return result.model_dump(mode="json")

    # ──────────────────────────── コンソール出力 ────────────────────────────

    def _print_summary(self, config: ExperimentConfig, summary: ExperimentRunSummary, run_dir: Path) -> None:
        """PLAN 10.2 準拠のコンソール出力。"""
        try:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
        except ImportError:
            return

        console = Console()

        console.print()
        console.print(Panel(
            f"[bold]{config.experiment.id}: {config.experiment.name}[/bold] — 完了",
            border_style="blue",
        ))
        skipped_count = len(summary.skipped_records)
        skipped_suffix = f"  |  スキップ: {skipped_count}件" if skipped_count else ""
        console.print(
            f"  対象論文: {len(summary.target_papers)}件  |  "
            f"条件: {len(config.conditions)}  |  "
            f"総提案数: {len(summary.records)}"
            f"{skipped_suffix}"
        )

        if skipped_count:
            skipped_ids = sorted({r.paper_id for r in summary.skipped_records})
            console.print(f"  [yellow]スキップ論文: {', '.join(skipped_ids)}[/yellow]")

        # Single 評価サマリー
        single_root = run_dir / "evaluations" / "single"
        if single_root.exists():
            table = Table(title="Single評価 (平均スコア)", show_header=True, header_style="bold magenta")
            table.add_column("条件", style="cyan")
            for metric in ["Nov", "Sig", "Fea", "Cla", "Eff", "Avg"]:
                table.add_column(metric, justify="right")

            for condition_dir in sorted(single_root.iterdir()):
                if not condition_dir.is_dir():
                    continue
                totals: dict[str, list[float]] = {}
                for f in condition_dir.glob("*.json"):
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        for entry in data.get("ranking", []):
                            for s in entry.get("scores", []):
                                m = s.get("metric", "")
                                sc = s.get("score")
                                if m and sc is not None:
                                    totals.setdefault(m, []).append(float(sc))
                            overall = entry.get("overall_score")
                            if overall is not None:
                                totals.setdefault("overall", []).append(float(overall))
                    except Exception:
                        continue

                def _avg(key: str) -> str:
                    vals = totals.get(key, [])
                    return f"{sum(vals) / len(vals):.1f}" if vals else "-"

                table.add_row(
                    condition_dir.name,
                    _avg("novelty"), _avg("significance"), _avg("feasibility"),
                    _avg("clarity"), _avg("effectiveness"), _avg("overall"),
                )

            console.print(table)

        # Pairwise サマリー
        pairwise_root = run_dir / "evaluations" / "pairwise"
        if pairwise_root.exists():
            wins: dict[str, int] = {}
            total = 0
            for f in pairwise_root.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    ranking = data.get("ranking", [])
                    if ranking:
                        top = ranking[0]
                        source = str(top.get("source", "unknown"))
                        wins[source] = wins.get(source, 0) + 1
                        total += 1
                except Exception:
                    continue
            if total:
                console.print("\n[bold]Pairwise評価[/bold]")
                for source, count in sorted(wins.items(), key=lambda x: -x[1]):
                    pct = count / total * 100
                    console.print(f"  {source} 勝率: {pct:.1f}% ({count}/{total})")

        console.print(f"\n  結果: {run_dir}/")

    # ──────────────────────────── レポート生成 ────────────────────────────

    def _generate_report(self, config: ExperimentConfig, run_dir: Path) -> Path:
        """Markdown レポートを生成する。"""
        lines = [
            f"# {config.experiment.id}: {config.experiment.name}",
            "",
            f"**説明**: {config.experiment.description}",
            f"**カテゴリ**: {config.experiment.category.value}",
            "",
        ]

        # Single 評価サマリー
        single_root = run_dir / "evaluations" / "single"
        if single_root.exists():
            lines.append("## Single評価サマリー")
            lines.append("")
            lines.append("| 条件 | Novelty | Significance | Feasibility | Clarity | Effectiveness | Overall |")
            lines.append("|---|---|---|---|---|---|---|")

            for condition_dir in sorted(single_root.iterdir()):
                if not condition_dir.is_dir():
                    continue
                totals: dict[str, list[float]] = {}
                for f in condition_dir.glob("*.json"):
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        for entry in data.get("ranking", []):
                            for s in entry.get("scores", []):
                                m = s.get("metric", "")
                                sc = s.get("score")
                                if m and sc is not None:
                                    totals.setdefault(m, []).append(float(sc))
                            overall = entry.get("overall_score")
                            if overall is not None:
                                totals.setdefault("overall", []).append(float(overall))
                    except Exception:
                        continue

                def _fmt(key: str) -> str:
                    vals = totals.get(key, [])
                    return f"{sum(vals) / len(vals):.2f}" if vals else "-"

                lines.append(
                    f"| {condition_dir.name} | {_fmt('novelty')} | {_fmt('significance')} | "
                    f"{_fmt('feasibility')} | {_fmt('clarity')} | {_fmt('effectiveness')} | {_fmt('overall')} |"
                )
            lines.append("")

        report_path = run_dir / "report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    # ──────────────────────────── メイン実行 ────────────────────────────

    def run(
        self,
        config_path: str | Path,
        limit: int | None = None,
        no_cache: bool = False,
        clear_cache: bool = False,
    ) -> ExperimentRunSummary:
        if no_cache:
            self._no_cache = True
        if clear_cache:
            cleared = self._cache.clear()
            logger.info("Cleared %d cache files", cleared)

        config = load_experiment_config(config_path)
        if not Neo4jConnection.verify_connectivity():
            raise RuntimeError("Neo4j is not connected")

        run_dir = self._resolve_run_dir(config)
        run_dir.mkdir(parents=True, exist_ok=True)

        target_papers = self._select_target_papers(config, limit)
        if not target_papers:
            raise ValueError("No target papers selected")

        summary = ExperimentRunSummary(
            run_id=run_dir.name,
            experiment_id=config.experiment.id,
            config_file=str(Path(config_path)),
            run_dir=str(run_dir),
            started_at=datetime.now(timezone.utc).isoformat(),
            target_papers=target_papers,
        )

        config_copy = self._load_yaml(Path(config_path))
        self._save_yaml(run_dir / "config.yaml", config_copy)

        metadata = {
            "experiment_id": config.experiment.id,
            "experiment_name": config.experiment.name,
            "git_hash": self._git_hash(),
            "timestamp": summary.started_at,
            "models": {
                "conditions": {c.name: c.generation.model for c in config.conditions},
                "evaluation": config.evaluation.model,
            },
            "neo4j": self._neo4j_stats(),
        }
        self._write_json(run_dir / "metadata.json", metadata)

        # 評価モデルリスト（cross-model 対応）
        eval_models = config.evaluation.models or [config.evaluation.model]

        pairwise_cache: dict[str, list[tuple[MethodType, Proposal]]] = {}

        for condition in config.conditions:
            for paper_id in target_papers:
                logger.info("Running %s for %s", condition.name, paper_id)

                try:
                    if condition.method == MethodType.IDEAGRAPH:
                        proposal_result = self._run_ideagraph(paper_id, condition, config)
                    elif condition.method == MethodType.DIRECT_LLM:
                        proposal_result = self._run_direct_llm(paper_id, condition)
                    elif condition.method == MethodType.COI:
                        proposal_result = self._run_coi(paper_id, condition)
                    else:
                        raise ValueError(f"Unsupported method: {condition.method}")

                    proposals_file = run_dir / "proposals" / condition.name / f"{paper_id}.json"
                    self._write_json(proposals_file, proposal_result.model_dump(mode="json"))

                    single_eval_file: Path | None = None
                    if config.evaluation.mode in {"single", "both"}:
                        for eval_model in eval_models:
                            model_suffix = f"_{eval_model}" if len(eval_models) > 1 else ""
                            if config.evaluation.repeat > 1:
                                eval_results = self._evaluate_single_repeat(
                                    proposals=proposal_result.proposals,
                                    source=condition.method,
                                    model_name=eval_model,
                                    repeat=config.evaluation.repeat,
                                )
                                for r_idx, eval_data in enumerate(eval_results):
                                    repeat_file = (
                                        run_dir / "evaluations" / "single" / condition.name
                                        / f"{paper_id}{model_suffix}_r{r_idx}.json"
                                    )
                                    self._write_json(repeat_file, eval_data)
                                single_eval_file = repeat_file  # type: ignore[assignment]
                            else:
                                single_eval = self._evaluate_single(
                                    proposals=proposal_result.proposals,
                                    source=condition.method,
                                    model_name=eval_model,
                                )
                                single_eval_file = (
                                    run_dir / "evaluations" / "single" / condition.name
                                    / f"{paper_id}{model_suffix}.json"
                                )
                                self._write_json(single_eval_file, single_eval)

                    summary.records.append(
                        PaperRunRecord(
                            paper_id=paper_id,
                            condition=condition.name,
                            method=condition.method,
                            proposals_file=str(proposals_file),
                            single_evaluation_file=str(single_eval_file) if single_eval_file else None,
                        )
                    )

                    first = proposal_result.proposals[0] if proposal_result.proposals else None
                    if first is not None:
                        pairwise_cache.setdefault(paper_id, []).append((condition.method, first))

                except Exception as e:
                    logger.warning("Skipped paper %s for condition %s: %s", paper_id, condition.name, e)
                    summary.skipped_records.append(
                        SkippedPaperRecord(
                            paper_id=paper_id,
                            condition=condition.name,
                            method=condition.method,
                            reason=str(e),
                        )
                    )
                    continue

        has_multiple_pairwise_items = len(config.conditions) >= 2 or config.evaluation.include_target
        if config.evaluation.mode in {"pairwise", "both"} and has_multiple_pairwise_items:
            min_proposals = 1 if config.evaluation.include_target else 2
            for paper_id, proposal_set in pairwise_cache.items():
                if len(proposal_set) < min_proposals:
                    continue
                for eval_model in eval_models:
                    model_suffix = f"_{eval_model}" if len(eval_models) > 1 else ""
                    pairwise = self._evaluate_pairwise(
                        proposal_set=proposal_set,
                        model_name=eval_model,
                        include_experiment=config.evaluation.include_experiment,
                        include_target=config.evaluation.include_target,
                        paper_id=paper_id,
                    )
                    pairwise_file = run_dir / "evaluations" / "pairwise" / f"{paper_id}{model_suffix}.json"
                    self._write_json(pairwise_file, pairwise)
                    summary.pairwise_records.append(
                        PairwiseRunRecord(
                            paper_id=paper_id,
                            file=str(pairwise_file),
                        )
                    )

        summary.completed_at = datetime.now(timezone.utc).isoformat()
        self._write_json(run_dir / "summary.json", summary.model_dump(mode="json"))
        self._generate_report(config, run_dir)

        # 可視化
        try:
            from idea_graph.services.visualizer import ExperimentVisualizer
            vis = ExperimentVisualizer()
            vis.visualize(run_dir)
        except Exception as e:
            logger.warning("Visualization failed: %s", e)

        self._print_summary(config, summary, run_dir)
        return summary

    def list_runs(self, base_dir: str | Path = "experiments/runs") -> list[ExperimentRunSummary]:
        root = Path(base_dir)
        if not root.exists():
            return []
        runs: list[ExperimentRunSummary] = []
        for summary_file in sorted(root.glob("*/summary.json"), reverse=True):
            try:
                payload = json.loads(summary_file.read_text(encoding="utf-8"))
                runs.append(ExperimentRunSummary.model_validate(payload))
            except Exception:
                continue
        return runs
