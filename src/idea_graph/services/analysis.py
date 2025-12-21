"""マルチホップ分析サービス"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from idea_graph.db import Neo4jConnection

logger = logging.getLogger(__name__)


class PathNode(BaseModel):
    """パスノード"""

    id: str
    label: str  # Paper or Entity type
    name: str


class PathEdge(BaseModel):
    """パスエッジ"""

    type: str  # CITES, MENTIONS, etc.


class RankedPath(BaseModel):
    """ランク付きパス"""

    nodes: list[PathNode]
    edges: list[PathEdge]
    score: float
    score_breakdown: dict[str, float] | None = None


class AnalysisResult(BaseModel):
    """分析結果"""

    target_paper_id: str
    candidates: list[RankedPath]
    multihop_k: int


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
        top_n: int,
    ) -> list[dict[str, Any]]:
        """マルチホップパスを探索"""
        with Neo4jConnection.session() as session:
            # CITES と MENTIONS を含むパスを探索
            result = session.run(
                """
                MATCH path = (target:Paper {id: $target_id})-[rels*1..""" + str(multihop_k) + """]->(n)
                WHERE n:Paper OR n:Entity
                WITH path, target, n, rels,
                     length(path) AS path_length,
                     size([r IN rels WHERE type(r) = 'CITES']) AS cite_count,
                     size([r IN rels WHERE type(r) = 'MENTIONS']) AS mention_count
                RETURN path, target, n, rels, path_length, cite_count, mention_count
                ORDER BY cite_count DESC, path_length ASC
                LIMIT $limit
                """,
                target_id=target_paper_id,
                limit=top_n * 2,  # スコアリング後にフィルタするため多めに取得
            )

            paths = []
            for record in result:
                paths.append({
                    "path": record["path"],
                    "target": record["target"],
                    "end_node": record["n"],
                    "rels": record["rels"],
                    "path_length": record["path_length"],
                    "cite_count": record["cite_count"],
                    "mention_count": record["mention_count"],
                })

            return paths

    def _score_path(self, path_data: dict[str, Any]) -> float:
        """パスをスコアリング

        スコアリング基準:
        - CITES 関係の数: 高いほど良い（引用関係は重要）
        - パスの長さ: 短いほど良い（直接的な関連）
        - MENTIONS 関係の数: 中程度（エンティティ関連）
        """
        cite_weight = 10.0
        mention_weight = 5.0
        length_penalty = 2.0

        cite_score = path_data["cite_count"] * cite_weight
        mention_score = path_data["mention_count"] * mention_weight
        length_score = -path_data["path_length"] * length_penalty

        return cite_score + mention_score + length_score + 100  # ベーススコア

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
            else:
                name = node.get("name", node.get("id", "Unknown"))

            nodes.append(PathNode(
                id=node.get("id", node.element_id),
                label=label,
                name=name,
            ))

        # エッジを抽出
        for rel in path.relationships:
            edges.append(PathEdge(type=rel.type))

        score = self._score_path(path_data)

        return RankedPath(
            nodes=nodes,
            edges=edges,
            score=score,
            score_breakdown={
                "cite_score": path_data["cite_count"] * 10.0,
                "mention_score": path_data["mention_count"] * 5.0,
                "length_penalty": -path_data["path_length"] * 2.0,
            },
        )

    def analyze(
        self,
        target_paper_id: str,
        multihop_k: int = 3,
        top_n: int = 10,
    ) -> AnalysisResult:
        """マルチホップ分析を実行

        Args:
            target_paper_id: ターゲット論文ID
            multihop_k: 最大ホップ数
            top_n: 返す候補数

        Returns:
            分析結果

        Raises:
            ValueError: 論文が見つからない場合
        """
        # 論文の存在確認
        if not self._check_paper_exists(target_paper_id):
            raise ValueError(f"Paper not found: {target_paper_id}")

        # パス探索
        paths = self._find_paths(target_paper_id, multihop_k, top_n)

        if not paths:
            return AnalysisResult(
                target_paper_id=target_paper_id,
                candidates=[],
                multihop_k=multihop_k,
            )

        # スコアリングとランキング
        ranked_paths = []
        for path_data in paths:
            ranked_path = self._extract_path_info(path_data)
            ranked_paths.append(ranked_path)

        # スコア降順でソート
        ranked_paths.sort(key=lambda x: x.score, reverse=True)

        # 上位 N 件を返す
        return AnalysisResult(
            target_paper_id=target_paper_id,
            candidates=ranked_paths[:top_n],
            multihop_k=multihop_k,
        )
