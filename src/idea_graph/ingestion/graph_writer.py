"""Neo4j グラフ書き込みモジュール"""

import hashlib
import logging
from datetime import datetime
from typing import Sequence

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.ingestion.dataset_loader import PaperMetadata, generate_paper_id
from idea_graph.ingestion.extractor import ExtractedInfo

logger = logging.getLogger(__name__)


class GraphWriterService:
    """Neo4j グラフ書き込みサービス"""

    def __init__(self, batch_size: int | None = None):
        """初期化

        Args:
            batch_size: バッチサイズ
        """
        self.batch_size = batch_size or settings.batch_size

    def _generate_entity_id(self, entity_type: str, name: str) -> str:
        """Entity ID を生成

        Args:
            entity_type: エンティティタイプ
            name: エンティティ名

        Returns:
            16文字のハッシュベースID
        """
        combined = f"{entity_type.lower()}:{name.lower()}"
        hash_obj = hashlib.sha256(combined.encode("utf-8"))
        return hash_obj.hexdigest()[:16]

    def ensure_indexes(self) -> None:
        """インデックスと制約を作成"""
        Neo4jConnection.ensure_indexes()

    def write_papers(self, papers: Sequence[PaperMetadata]) -> int:
        """Paper ノードをバッチで作成

        Args:
            papers: 論文メタデータのリスト

        Returns:
            作成された件数
        """
        total = 0
        papers_list = list(papers)

        for i in range(0, len(papers_list), self.batch_size):
            batch = papers_list[i : i + self.batch_size]
            batch_data = [
                {
                    "id": p.paper_id,
                    "title": p.title,
                }
                for p in batch
            ]

            with Neo4jConnection.session() as session:
                session.run(
                    """
                    UNWIND $batch AS item
                    MERGE (p:Paper {id: item.id})
                    ON CREATE SET p.title = item.title
                    ON MATCH SET p.title = item.title
                    """,
                    batch=batch_data,
                )
                total += len(batch)

        logger.info(f"Created/updated {total} Paper nodes")
        for paper in papers:
            logger.info(f"Paper: {paper.paper_id} {paper.title}")
        return total

    def update_paper_published_date(
        self, paper_id: str, published_date: datetime | None
    ) -> None:
        """Paper ノードの公開日を更新

        Args:
            paper_id: 論文ID
            published_date: 公開日（None の場合は更新しない）
        """
        if published_date is None:
            return

        with Neo4jConnection.session() as session:
            session.run(
                """
                MATCH (p:Paper {id: $paper_id})
                SET p.published_date = $published_date
                """,
                paper_id=paper_id,
                published_date=published_date.isoformat(),
            )
        logger.debug(f"Updated published_date for {paper_id}: {published_date}")

    def write_citations(self, citations: Sequence[tuple[str, str, str]]) -> int:
        """CITES 関係をバッチで作成

        Args:
            citations: (from_paper_id, to_paper_id, ref_title) のタプルリスト

        Returns:
            作成された件数
        """
        total = 0
        citations_list = list(citations)

        for i in range(0, len(citations_list), self.batch_size):
            batch = citations_list[i : i + self.batch_size]
            batch_data = [
                {"from_id": c[0], "to_id": c[1], "ref_title": c[2]}
                for c in batch
            ]

            with Neo4jConnection.session() as session:
                session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (from:Paper {id: item.from_id})
                    MERGE (to:Paper {id: item.to_id})
                    ON CREATE SET to.title = item.ref_title
                    MERGE (from)-[:CITES]->(to)
                    """,
                    batch=batch_data,
                )
                total += len(batch)

        logger.info(f"Created {total} CITES relationships")
        return total

    def write_extracted(self, extractions: Sequence[ExtractedInfo]) -> int:
        """抽出情報をグラフに書き込み

        Args:
            extractions: 抽出情報のリスト

        Returns:
            処理された件数
        """
        total = 0

        for extraction in extractions:
            with Neo4jConnection.session() as session:
                # Paper ノードを更新（summary, claims を追加）
                session.run(
                    """
                    MERGE (p:Paper {id: $paper_id})
                    SET p.summary = $summary,
                        p.claims = $claims
                    """,
                    paper_id=extraction.paper_id,
                    summary=extraction.paper_summary,
                    claims=extraction.claims,
                )

                # Entity ノードを作成
                if extraction.entities:
                    entity_data = [
                        {
                            "id": self._generate_entity_id(e.type, e.name),
                            "type": e.type,
                            "name": e.name,
                            "description": e.description or "",
                        }
                        for e in extraction.entities
                    ]

                    session.run(
                        """
                        UNWIND $entities AS item
                        MERGE (e:Entity {id: item.id})
                        ON CREATE SET e.type = item.type,
                                      e.name = item.name,
                                      e.description = item.description
                        """,
                        entities=entity_data,
                    )

                    # MENTIONS 関係を作成
                    mentions_data = [
                        {
                            "paper_id": extraction.paper_id,
                            "entity_id": self._generate_entity_id(e.type, e.name),
                        }
                        for e in extraction.entities
                    ]

                    session.run(
                        """
                        UNWIND $mentions AS item
                        MATCH (p:Paper {id: item.paper_id})
                        MATCH (e:Entity {id: item.entity_id})
                        MERGE (p)-[:MENTIONS]->(e)
                        """,
                        mentions=mentions_data,
                    )

                # Entity 間関係を作成
                if extraction.relations:
                    for relation in extraction.relations:
                        # source と target の Entity を探す
                        source_entity = next(
                            (e for e in extraction.entities if e.name == relation.source),
                            None,
                        )
                        target_entity = next(
                            (e for e in extraction.entities if e.name == relation.target),
                            None,
                        )

                        if source_entity and target_entity:
                            source_id = self._generate_entity_id(
                                source_entity.type, source_entity.name
                            )
                            target_id = self._generate_entity_id(
                                target_entity.type, target_entity.name
                            )

                            # 動的に関係タイプを設定
                            session.run(
                                f"""
                                MATCH (s:Entity {{id: $source_id}})
                                MATCH (t:Entity {{id: $target_id}})
                                MERGE (s)-[:{relation.relation_type}]->(t)
                                """,
                                source_id=source_id,
                                target_id=target_id,
                            )

                # CITES 関係を重要度付きで作成
                if extraction.cited_papers:
                    for cited in extraction.cited_papers:
                        cited_id = generate_paper_id(cited.title)
                        session.run(
                            """
                            MATCH (p:Paper {id: $paper_id})
                            MERGE (cited:Paper {id: $cited_id})
                            ON CREATE SET cited.title = $cited_title
                            MERGE (p)-[r:CITES]->(cited)
                            SET r.importance_score = $importance_score,
                                r.citation_type = $citation_type,
                                r.context = $context
                            """,
                            paper_id=extraction.paper_id,
                            cited_id=cited_id,
                            cited_title=cited.title,
                            importance_score=cited.importance_score,
                            citation_type=cited.citation_type,
                            context=cited.context or "",
                        )

                total += 1

        logger.info(f"Processed {total} extractions")
        return total
