"""Neo4j グラフ書き込みモジュール"""

import hashlib
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Sequence

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.ingestion.dataset_loader import PaperMetadata, generate_paper_id
from idea_graph.ingestion.extractor import ExtractedInfo

logger = logging.getLogger(__name__)
_RELATION_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


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

    def update_paper_published_dates(
        self,
        items: Sequence[tuple[str, datetime | None]],
    ) -> int:
        """Paper ノードの公開日をまとめて更新"""
        updates = [
            {
                "paper_id": paper_id,
                "published_date": published_date.isoformat(),
            }
            for paper_id, published_date in items
            if published_date is not None
        ]
        total = 0

        for i in range(0, len(updates), self.batch_size):
            batch = updates[i : i + self.batch_size]
            with Neo4jConnection.session() as session:
                session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (p:Paper {id: item.paper_id})
                    SET p.published_date = item.published_date
                    """,
                    batch=batch,
                )
            total += len(batch)

        if total:
            logger.debug(f"Updated published_date for {total} papers")
        return total

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

    def write_extracted_batch(self, extractions: Sequence[ExtractedInfo]) -> int:
        """抽出情報をまとめてグラフへ書き込む"""
        total = 0
        extraction_list = list(extractions)

        for i in range(0, len(extraction_list), self.batch_size):
            batch = extraction_list[i : i + self.batch_size]
            paper_data = [
                {
                    "paper_id": extraction.paper_id,
                    "summary": extraction.paper_summary,
                    "claims": extraction.claims,
                }
                for extraction in batch
            ]
            entity_data = []
            mentions_data = []
            relations_by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
            citations_data = []

            for extraction in batch:
                entity_by_name = {}
                for entity in extraction.entities:
                    entity_id = self._generate_entity_id(entity.type, entity.name)
                    entity_data.append(
                        {
                            "id": entity_id,
                            "type": entity.type,
                            "name": entity.name,
                            "description": entity.description or "",
                        }
                    )
                    mentions_data.append(
                        {
                            "paper_id": extraction.paper_id,
                            "entity_id": entity_id,
                        }
                    )
                    entity_by_name[entity.name] = entity

                for relation in extraction.relations:
                    relation_type = relation.relation_type.strip().upper()
                    if not _RELATION_TYPE_PATTERN.fullmatch(relation_type):
                        logger.warning(
                            "Skipping invalid relation type '%s' for paper %s",
                            relation.relation_type,
                            extraction.paper_id,
                        )
                        continue

                    source_entity = entity_by_name.get(relation.source)
                    target_entity = entity_by_name.get(relation.target)
                    if not source_entity or not target_entity:
                        continue

                    relations_by_type[relation_type].append(
                        {
                            "source_id": self._generate_entity_id(
                                source_entity.type,
                                source_entity.name,
                            ),
                            "target_id": self._generate_entity_id(
                                target_entity.type,
                                target_entity.name,
                            ),
                        }
                    )

                for cited in extraction.cited_papers:
                    citations_data.append(
                        {
                            "paper_id": extraction.paper_id,
                            "cited_id": generate_paper_id(cited.title),
                            "cited_title": cited.title,
                            "importance_score": cited.importance_score,
                            "citation_type": cited.citation_type,
                            "context": cited.context or "",
                        }
                    )

            with Neo4jConnection.session() as session:
                session.run(
                    """
                    UNWIND $papers AS item
                    MERGE (p:Paper {id: item.paper_id})
                    SET p.summary = item.summary,
                        p.claims = item.claims
                    """,
                    papers=paper_data,
                )

                if entity_data:
                    session.run(
                        """
                        UNWIND $entities AS item
                        MERGE (e:Entity {id: item.id})
                        ON CREATE SET e.type = item.type,
                                      e.name = item.name,
                                      e.description = item.description
                        ON MATCH SET e.type = item.type,
                                     e.name = item.name,
                                     e.description = item.description
                        """,
                        entities=entity_data,
                    )

                if mentions_data:
                    session.run(
                        """
                        UNWIND $mentions AS item
                        MATCH (p:Paper {id: item.paper_id})
                        MATCH (e:Entity {id: item.entity_id})
                        MERGE (p)-[:MENTIONS]->(e)
                        """,
                        mentions=mentions_data,
                    )

                for relation_type, relation_batch in relations_by_type.items():
                    session.run(
                        f"""
                        UNWIND $relations AS item
                        MATCH (s:Entity {{id: item.source_id}})
                        MATCH (t:Entity {{id: item.target_id}})
                        MERGE (s)-[:{relation_type}]->(t)
                        """,
                        relations=relation_batch,
                    )

                if citations_data:
                    session.run(
                        """
                        UNWIND $citations AS item
                        MATCH (p:Paper {id: item.paper_id})
                        MERGE (cited:Paper {id: item.cited_id})
                        ON CREATE SET cited.title = item.cited_title
                        ON MATCH SET cited.title = CASE
                            WHEN cited.title IS NULL OR cited.title = "" THEN item.cited_title
                            ELSE cited.title
                        END
                        MERGE (p)-[r:CITES]->(cited)
                        SET r.importance_score = item.importance_score,
                            r.citation_type = item.citation_type,
                            r.context = item.context
                        """,
                        citations=citations_data,
                    )

            total += len(batch)

        logger.info(f"Processed {total} extractions")
        return total

    def write_extracted(self, extractions: Sequence[ExtractedInfo]) -> int:
        """抽出情報をグラフに書き込み"""
        return self.write_extracted_batch(extractions)
