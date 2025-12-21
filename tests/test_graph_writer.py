"""GraphWriter のテスト"""

from unittest.mock import MagicMock, patch

import pytest

from idea_graph.ingestion.graph_writer import GraphWriterService
from idea_graph.ingestion.dataset_loader import PaperMetadata
from idea_graph.ingestion.extractor import ExtractedInfo, Entity, InternalRelation


class TestGraphWriterService:
    """GraphWriterService のテスト"""

    def test_write_papers_creates_nodes(self):
        """Paper ノードが作成されること"""
        with patch("idea_graph.ingestion.graph_writer.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            papers = [
                PaperMetadata(
                    paper_id="paper1",
                    title="Test Paper 1",
                    references=["Ref A", "Ref B"],
                ),
                PaperMetadata(
                    paper_id="paper2",
                    title="Test Paper 2",
                    references=[],
                ),
            ]

            service = GraphWriterService(batch_size=100)
            count = service.write_papers(papers)

            assert count == 2
            mock_session.run.assert_called()

    def test_write_papers_with_batching(self):
        """バッチ処理が機能すること"""
        with patch("idea_graph.ingestion.graph_writer.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            # 5件の論文、バッチサイズ2
            papers = [
                PaperMetadata(paper_id=f"paper{i}", title=f"Paper {i}", references=[])
                for i in range(5)
            ]

            service = GraphWriterService(batch_size=2)
            count = service.write_papers(papers)

            assert count == 5
            # 3回のバッチ処理 (2 + 2 + 1)
            assert mock_session.run.call_count == 3

    def test_write_citations_creates_relationships(self):
        """CITES 関係が作成されること"""
        with patch("idea_graph.ingestion.graph_writer.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            citations = [
                ("paper1", "paper2"),
                ("paper1", "paper3"),
                ("paper2", "paper3"),
            ]

            service = GraphWriterService(batch_size=100)
            count = service.write_citations(citations)

            assert count == 3
            mock_session.run.assert_called()

    def test_write_extracted_creates_entities(self):
        """Entity ノードが作成されること"""
        with patch("idea_graph.ingestion.graph_writer.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            extractions = [
                ExtractedInfo(
                    paper_id="paper1",
                    paper_summary="Summary 1",
                    claims=["Claim 1"],
                    entities=[
                        Entity(type="Method", name="Transformer"),
                        Entity(type="Dataset", name="ImageNet"),
                    ],
                    relations=[],
                ),
            ]

            service = GraphWriterService(batch_size=100)
            count = service.write_extracted(extractions)

            # Paper 更新 + Entity 作成 + MENTIONS 関係
            assert mock_session.run.call_count >= 3

    def test_write_extracted_with_relations(self):
        """Entity 間関係が作成されること"""
        with patch("idea_graph.ingestion.graph_writer.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            extractions = [
                ExtractedInfo(
                    paper_id="paper1",
                    paper_summary="Summary",
                    claims=["Claim"],
                    entities=[
                        Entity(type="Method", name="BERT"),
                        Entity(type="Method", name="Transformer"),
                    ],
                    relations=[
                        InternalRelation(
                            source="BERT",
                            target="Transformer",
                            relation_type="EXTENDS",
                        ),
                    ],
                ),
            ]

            service = GraphWriterService(batch_size=100)
            service.write_extracted(extractions)

            # 関係作成のクエリが呼ばれていることを確認
            calls = [str(call) for call in mock_session.run.call_args_list]
            assert any("EXTENDS" in str(call) or "relation" in str(call).lower() for call in calls)

    def test_ensure_indexes_called(self):
        """ensure_indexes が Neo4j に正しいクエリを送ること"""
        with patch("idea_graph.ingestion.graph_writer.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            service = GraphWriterService()
            service.ensure_indexes()

            mock_conn.ensure_indexes.assert_called_once()

    def test_generate_entity_id(self):
        """Entity ID が正しく生成されること"""
        service = GraphWriterService()

        id1 = service._generate_entity_id("Method", "Transformer")
        id2 = service._generate_entity_id("Method", "Transformer")
        id3 = service._generate_entity_id("Dataset", "Transformer")

        # 同じ type + name は同じ ID
        assert id1 == id2
        # 異なる type は異なる ID
        assert id1 != id3
