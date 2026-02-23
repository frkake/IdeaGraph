"""マルチホップ分析サービス"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from idea_graph.db import Neo4jConnection

logger = logging.getLogger(__name__)


class PathNode(BaseModel):
    """パスノード"""

    id: str
    label: str  # Paper or Entity
    name: str
    # Entity用の追加情報
    entity_type: str | None = None  # Method, Dataset, Metric, Task, etc.
    description: str | None = None  # Entityの説明


class PathEdge(BaseModel):
    """パスエッジ"""

    type: str  # CITES, MENTIONS, etc.
    from_id: str  # ソースノードID
    to_id: str  # ターゲットノードID
    importance_score: int | None = None  # 1-5 (CITES関係のみ)
    citation_type: str | None = None  # EXTENDS, COMPARES, USES, BACKGROUND, MENTIONS
    context: str | None = None  # 引用コンテキスト


class RankedPath(BaseModel):
    """ランク付きパス"""

    nodes: list[PathNode]
    edges: list[PathEdge]
    score: float
    score_breakdown: dict[str, Any] | None = None


class AnalysisResult(BaseModel):
    """分析結果"""

    target_paper_id: str
    candidates: list[RankedPath]  # 全パス（後方互換性のため）
    paper_paths: list[RankedPath] | None = None  # Paper引用パス
    entity_paths: list[RankedPath] | None = None  # Entity関連パス
    multihop_k: int
    total_paths: int | None = None
    total_paper_paths: int | None = None
    total_entity_paths: int | None = None
    total_nodes: int | None = None
    total_edges: int | None = None


class AnalysisService:
    """マルチホップ分析サービス"""

    def __init__(self):
        """初期化"""
        pass

    def _check_paper_exists(self, paper_id: str) -> bool:
        """論文が存在するか確認"""
        with Neo4jConnection.session() as session:
            result = session.run(
                "MATCH (p:Paper {id: $id}) RETURN p LIMIT 1",
                id=paper_id,
            )
            return result.single() is not None

    def _find_paths(
        self,
        target_paper_id: str,
        multihop_k: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """マルチホップパスを探索（Paper引用パスとEntity関連パスを両方取得）"""
        paths = []

        with Neo4jConnection.session() as session:
            limit_clause = ""
            params: dict[str, Any] = {"target_id": target_paper_id}
            if limit is not None:
                limit_clause = "LIMIT $limit"
                params["limit"] = limit

            # クエリのベース部分
            base_query = """
                MATCH path = (target:Paper {id: $target_id})-[rels*1..""" + str(multihop_k) + """]->(n)
                WHERE (n:Paper OR n:Entity)
                  AND NONE(node IN nodes(path)[1..] WHERE node = target)
                WITH path, target, n, rels,
                     length(path) AS path_length,
                     // Paper引用関連
                     size([r IN rels WHERE type(r) = 'CITES']) AS cite_count,
                     reduce(s = 0, r IN [rel IN rels WHERE type(rel) = 'CITES'] |
                            s + coalesce(r.importance_score, 3)) AS cite_importance,
                     size([r IN rels WHERE type(r) = 'CITES' AND r.citation_type = 'EXTENDS']) AS cite_extends,
                     size([r IN rels WHERE type(r) = 'CITES' AND r.citation_type = 'COMPARES']) AS cite_compares,
                     size([r IN rels WHERE type(r) = 'CITES' AND r.citation_type = 'USES']) AS cite_uses,
                     // Entity関連
                     size([r IN rels WHERE type(r) = 'MENTIONS']) AS mentions_count,
                     size([r IN rels WHERE type(r) = 'USES']) AS entity_uses_count,
                     size([r IN rels WHERE type(r) = 'EXTENDS']) AS entity_extends_count,
                     size([r IN rels WHERE type(r) = 'COMPARES']) AS entity_compares_count,
                     size([r IN rels WHERE type(r) = 'ENABLES']) AS enables_count,
                     size([r IN rels WHERE type(r) = 'IMPROVES']) AS improves_count,
                     size([r IN rels WHERE type(r) = 'ADDRESSES']) AS addresses_count,
                     // Entityノードの数
                     size([node IN nodes(path) WHERE 'Entity' IN labels(node)]) AS entity_count,
                     // 関係タイプのリスト
                     [r IN rels | type(r)] AS rel_types
            """

            # 1. Paper引用パス（CITES を含む）を取得
            cite_query = base_query + """
                WHERE cite_count > 0
                RETURN path, target, n, rels, path_length,
                       cite_count, cite_importance, cite_extends, cite_compares, cite_uses,
                       mentions_count, entity_uses_count, entity_extends_count, entity_compares_count,
                       enables_count, improves_count, addresses_count,
                       entity_count, rel_types
                ORDER BY cite_importance DESC, path_length ASC
                """ + limit_clause + """
            """
            result = session.run(cite_query, **params)

            for record in result:
                paths.append(self._record_to_path_data(record))

            # 2. Entity関連パス（MENTIONS, USES, EXTENDS 等を含む、CITES を含まない）を取得
            entity_query = base_query + """
                WHERE cite_count = 0 AND entity_count > 0
                RETURN path, target, n, rels, path_length,
                       cite_count, cite_importance, cite_extends, cite_compares, cite_uses,
                       mentions_count, entity_uses_count, entity_extends_count, entity_compares_count,
                       enables_count, improves_count, addresses_count,
                       entity_count, rel_types
                ORDER BY
                    entity_uses_count + entity_extends_count + enables_count DESC,
                    path_length ASC
                """ + limit_clause + """
            """
            result = session.run(entity_query, **params)

            for record in result:
                paths.append(self._record_to_path_data(record))

        return paths

    def _record_to_path_data(self, record) -> dict[str, Any]:
        """Neo4jレコードをパスデータに変換"""
        return {
            "path": record["path"],
            "target": record["target"],
            "end_node": record["n"],
            "rels": record["rels"],
            "path_length": record["path_length"],
            # Paper引用関連
            "cite_count": record["cite_count"],
            "cite_importance": record["cite_importance"],
            "cite_extends": record["cite_extends"],
            "cite_compares": record["cite_compares"],
            "cite_uses": record["cite_uses"],
            # Entity関連
            "mentions_count": record["mentions_count"],
            "entity_uses_count": record["entity_uses_count"],
            "entity_extends_count": record["entity_extends_count"],
            "entity_compares_count": record["entity_compares_count"],
            "enables_count": record["enables_count"],
            "improves_count": record["improves_count"],
            "addresses_count": record["addresses_count"],
            "entity_count": record["entity_count"],
            "rel_types": record["rel_types"],
        }

    def _score_path(self, path_data: dict[str, Any]) -> dict[str, Any]:
        """パスをスコアリング

        スコアリング基準:
        1. Paper引用関連:
           - importance_score: LLMが抽出した引用の重要度 (1-5)
           - citation_type: EXTENDS/COMPARES/USES による重み付け
        2. Entity関連:
           - MENTIONS: 論文がエンティティに言及
           - USES/EXTENDS/COMPARES: エンティティ間の関係
           - ENABLES/IMPROVES/ADDRESSES: エンティティの効果
        3. パス長: 短いほど良い
        """
        # === Paper引用スコア ===
        cite_importance_score = path_data.get("cite_importance", 0) * 2.0
        cite_type_score = (
            path_data.get("cite_extends", 0) * 20 +  # EXTENDS は最重要
            path_data.get("cite_compares", 0) * 15 +
            path_data.get("cite_uses", 0) * 12 +
            max(0, path_data["cite_count"] -
                path_data.get("cite_extends", 0) -
                path_data.get("cite_compares", 0) -
                path_data.get("cite_uses", 0)) * 10
        )

        # === Entity関連スコア ===
        mentions_score = path_data.get("mentions_count", 0) * 3.0
        entity_relation_score = (
            path_data.get("entity_uses_count", 0) * 8 +
            path_data.get("entity_extends_count", 0) * 10 +
            path_data.get("entity_compares_count", 0) * 7 +
            path_data.get("enables_count", 0) * 9 +
            path_data.get("improves_count", 0) * 8 +
            path_data.get("addresses_count", 0) * 6
        )

        # === ペナルティ ===
        length_penalty = -path_data["path_length"] * 2.0

        # === 合計スコア ===
        total_score = (
            cite_importance_score +
            cite_type_score +
            mentions_score +
            entity_relation_score +
            length_penalty +
            100  # ベーススコア
        )

        return {
            "total": total_score,
            # Paper引用関連
            "cite_importance_score": cite_importance_score,
            "cite_type_score": cite_type_score,
            "cite_extends": path_data.get("cite_extends", 0),
            "cite_compares": path_data.get("cite_compares", 0),
            "cite_uses": path_data.get("cite_uses", 0),
            # Entity関連
            "mentions_score": mentions_score,
            "entity_relation_score": entity_relation_score,
            "entity_uses": path_data.get("entity_uses_count", 0),
            "entity_extends": path_data.get("entity_extends_count", 0),
            "entity_compares": path_data.get("entity_compares_count", 0),
            "enables": path_data.get("enables_count", 0),
            "improves": path_data.get("improves_count", 0),
            "addresses": path_data.get("addresses_count", 0),
            # その他
            "entity_count": path_data.get("entity_count", 0),
            "rel_types": path_data.get("rel_types", []),
            "length_penalty": length_penalty,
        }

    def _extract_path_info(self, path_data: dict[str, Any]) -> RankedPath:
        """パス情報を抽出"""
        path = path_data["path"]
        nodes = []
        edges = []

        # ノードを抽出
        for node in path.nodes:
            labels = list(node.labels)
            label = labels[0] if labels else "Unknown"

            if "Paper" in labels:
                name = node.get("title", node.get("id", "Unknown"))
                nodes.append(PathNode(
                    id=node.get("id", node.element_id),
                    label=label,
                    name=name,
                ))
            else:
                # Entity ノード
                name = node.get("name", node.get("id", "Unknown"))
                nodes.append(PathNode(
                    id=node.get("id", node.element_id),
                    label=label,
                    name=name,
                    entity_type=node.get("type"),
                    description=node.get("description"),
                ))

        # エッジを抽出（詳細属性を含む）
        for i, rel in enumerate(path.relationships):
            # ソースとターゲットのノードIDを取得
            from_node = path.nodes[i]
            to_node = path.nodes[i + 1]
            from_id = from_node.get("id", from_node.element_id)
            to_id = to_node.get("id", to_node.element_id)

            edge = PathEdge(
                type=rel.type,
                from_id=from_id,
                to_id=to_id,
                importance_score=rel.get("importance_score") if rel.type == "CITES" else None,
                citation_type=rel.get("citation_type") if rel.type == "CITES" else None,
                context=rel.get("context") if rel.type == "CITES" else None,
            )
            edges.append(edge)

        score_data = self._score_path(path_data)

        return RankedPath(
            nodes=nodes,
            edges=edges,
            score=score_data["total"],
            score_breakdown=score_data,  # 全てのスコア詳細を含める
        )

    def analyze(
        self,
        target_paper_id: str,
        multihop_k: int = 3,
        top_n: int | None = None,
    ) -> AnalysisResult:
        """マルチホップ分析を実行

        Args:
            target_paper_id: ターゲット論文ID
            multihop_k: 最大ホップ数
            top_n: 返す候補数（Noneの場合は制限なし）

        Returns:
            分析結果

        Raises:
            ValueError: 論文が見つからない場合
        """
        # 論文の存在確認
        if not self._check_paper_exists(target_paper_id):
            raise ValueError(f"Paper not found: {target_paper_id}")

        # パス探索
        paths = self._find_paths(target_paper_id, multihop_k)

        if not paths:
            return AnalysisResult(
                target_paper_id=target_paper_id,
                candidates=[],
                paper_paths=[],
                entity_paths=[],
                multihop_k=multihop_k,
                total_paths=0,
                total_paper_paths=0,
                total_entity_paths=0,
                total_nodes=0,
                total_edges=0,
            )

        # スコアリングとランキング、Paper引用とEntity関連を分離
        paper_paths = []
        entity_paths = []

        for path_data in paths:
            ranked_path = self._extract_path_info(path_data)
            # Entity を含むパスかどうかで分類
            if path_data.get("entity_count", 0) > 0 and path_data.get("cite_count", 0) == 0:
                entity_paths.append(ranked_path)
            else:
                paper_paths.append(ranked_path)

        # 各カテゴリでスコア降順ソート
        paper_paths.sort(key=lambda x: x.score, reverse=True)
        entity_paths.sort(key=lambda x: x.score, reverse=True)

        # 全パスを結合してソート（後方互換性）
        all_paths = paper_paths + entity_paths
        all_paths.sort(key=lambda x: x.score, reverse=True)
        total_paper_paths = len(paper_paths)
        total_entity_paths = len(entity_paths)
        total_paths = len(all_paths)
        total_nodes = len({node.id for path in all_paths for node in path.nodes})
        total_edges = sum(len(path.edges) for path in all_paths)
        # top_n が None の場合は制限なし
        if top_n is None:
            display_limit = None
        else:
            display_limit = max(top_n, 0)

        return AnalysisResult(
            target_paper_id=target_paper_id,
            candidates=all_paths,
            paper_paths=paper_paths[:display_limit] if display_limit is not None else paper_paths,
            entity_paths=entity_paths[:display_limit] if display_limit is not None else entity_paths,
            multihop_k=multihop_k,
            total_paths=total_paths,
            total_paper_paths=total_paper_paths,
            total_entity_paths=total_entity_paths,
            total_nodes=total_nodes,
            total_edges=total_edges,
        )
