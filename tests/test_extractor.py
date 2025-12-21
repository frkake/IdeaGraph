"""InformationExtractor のテスト"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from idea_graph.ingestion.extractor import (
    Entity,
    ExtractedInfo,
    ExtractorService,
    InternalRelation,
)
from idea_graph.ingestion.downloader import FileType


class TestEntity:
    """Entity モデルのテスト"""

    def test_valid_entity(self):
        """有効な Entity の作成"""
        entity = Entity(
            type="Method",
            name="Transformer",
            description="An attention-based architecture",
        )
        assert entity.type == "Method"
        assert entity.name == "Transformer"
        assert entity.description == "An attention-based architecture"

    def test_entity_optional_description(self):
        """description はオプショナル"""
        entity = Entity(type="Dataset", name="ImageNet")
        assert entity.description is None


class TestInternalRelation:
    """InternalRelation モデルのテスト"""

    def test_valid_relation(self):
        """有効な InternalRelation の作成"""
        relation = InternalRelation(
            source="BERT",
            target="Transformer",
            relation_type="EXTENDS",
        )
        assert relation.source == "BERT"
        assert relation.target == "Transformer"
        assert relation.relation_type == "EXTENDS"


class TestExtractedInfo:
    """ExtractedInfo モデルのテスト"""

    def test_valid_extracted_info(self):
        """有効な ExtractedInfo の作成"""
        info = ExtractedInfo(
            paper_id="abc123",
            paper_summary="This paper proposes a new method.",
            claims=["Claim 1", "Claim 2"],
            entities=[
                Entity(type="Method", name="NewMethod"),
            ],
            relations=[
                InternalRelation(source="NewMethod", target="OldMethod", relation_type="EXTENDS"),
            ],
        )
        assert info.paper_id == "abc123"
        assert len(info.claims) == 2
        assert len(info.entities) == 1
        assert len(info.relations) == 1

    def test_extracted_info_empty_relations(self):
        """relations はデフォルトで空リスト"""
        info = ExtractedInfo(
            paper_id="abc123",
            paper_summary="Summary",
            claims=["Claim"],
            entities=[],
        )
        assert info.relations == []


class TestExtractorService:
    """ExtractorService のテスト"""

    def test_init_creates_cache_dir(self):
        """初期化時にキャッシュディレクトリが作成されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "extractions"
            service = ExtractorService(cache_dir=cache_dir)
            assert cache_dir.exists()

    def test_extract_returns_cached_result(self):
        """キャッシュ済み結果を返すこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_id = "abc123"

            # キャッシュファイルを作成
            cached_info = ExtractedInfo(
                paper_id=paper_id,
                paper_summary="Cached summary",
                claims=["Cached claim"],
                entities=[Entity(type="Method", name="CachedMethod")],
                relations=[],
            )
            cache_file = cache_dir / f"{paper_id}.json"
            cache_file.write_text(cached_info.model_dump_json())

            service = ExtractorService(cache_dir=cache_dir)
            result = service.extract(
                paper_id=paper_id,
                file_path=Path("/dummy/path.pdf"),
                file_type=FileType.PDF,
            )

            assert result.paper_id == paper_id
            assert result.paper_summary == "Cached summary"
            assert result.claims == ["Cached claim"]

    def test_extract_calls_llm(self):
        """LLM が呼び出されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_dir = Path(tmpdir) / "paper"
            paper_dir.mkdir()
            pdf_file = paper_dir / "paper.pdf"
            pdf_file.write_bytes(b"dummy pdf content")

            with patch("idea_graph.ingestion.extractor.ChatGoogleGenerativeAI") as mock_llm_class:
                # モックの設定
                mock_response = ExtractedInfo(
                    paper_id="",  # サービスで上書きされる
                    paper_summary="Extracted summary",
                    claims=["Extracted claim"],
                    entities=[Entity(type="Method", name="ExtractedMethod")],
                    relations=[],
                )

                mock_structured = MagicMock()
                mock_structured.invoke.return_value = mock_response

                mock_llm = MagicMock()
                mock_llm.with_structured_output.return_value = mock_structured

                mock_llm_class.return_value = mock_llm

                service = ExtractorService(cache_dir=cache_dir)
                result = service.extract(
                    paper_id="abc123",
                    file_path=pdf_file,
                    file_type=FileType.PDF,
                )

                assert result.paper_id == "abc123"
                assert result.paper_summary == "Extracted summary"
                mock_llm.with_structured_output.assert_called_once()

    def test_extract_saves_to_cache(self):
        """抽出結果がキャッシュに保存されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_dir = Path(tmpdir) / "paper"
            paper_dir.mkdir()
            pdf_file = paper_dir / "paper.pdf"
            pdf_file.write_bytes(b"dummy pdf content")

            with patch("idea_graph.ingestion.extractor.ChatGoogleGenerativeAI") as mock_llm_class:
                mock_response = ExtractedInfo(
                    paper_id="",
                    paper_summary="Extracted summary",
                    claims=["Claim"],
                    entities=[],
                    relations=[],
                )

                mock_structured = MagicMock()
                mock_structured.invoke.return_value = mock_response

                mock_llm = MagicMock()
                mock_llm.with_structured_output.return_value = mock_structured
                mock_llm_class.return_value = mock_llm

                service = ExtractorService(cache_dir=cache_dir)
                service.extract(
                    paper_id="abc123",
                    file_path=pdf_file,
                    file_type=FileType.PDF,
                )

                # キャッシュファイルが作成されていることを確認
                cache_file = cache_dir / "abc123.json"
                assert cache_file.exists()

                # キャッシュの内容を確認
                cached_data = json.loads(cache_file.read_text())
                assert cached_data["paper_id"] == "abc123"
                assert cached_data["paper_summary"] == "Extracted summary"

    def test_extract_with_retry_on_error(self):
        """エラー時にリトライすること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_dir = Path(tmpdir) / "paper"
            paper_dir.mkdir()
            pdf_file = paper_dir / "paper.pdf"
            pdf_file.write_bytes(b"dummy pdf content")

            with patch("idea_graph.ingestion.extractor.ChatGoogleGenerativeAI") as mock_llm_class:
                call_count = 0

                def invoke_side_effect(*args, **kwargs):
                    nonlocal call_count
                    call_count += 1
                    if call_count < 3:
                        raise Exception("Temporary error")
                    return ExtractedInfo(
                        paper_id="",
                        paper_summary="Success after retry",
                        claims=["Claim"],
                        entities=[],
                        relations=[],
                    )

                mock_structured = MagicMock()
                mock_structured.invoke.side_effect = invoke_side_effect

                mock_llm = MagicMock()
                mock_llm.with_structured_output.return_value = mock_structured
                mock_llm_class.return_value = mock_llm

                service = ExtractorService(cache_dir=cache_dir, max_retries=3)
                result = service.extract(
                    paper_id="abc123",
                    file_path=pdf_file,
                    file_type=FileType.PDF,
                )

                assert result.paper_summary == "Success after retry"
                assert call_count == 3

    def test_extract_returns_none_on_max_retries(self):
        """最大リトライ回数を超えた場合は None を返すこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_dir = Path(tmpdir) / "paper"
            paper_dir.mkdir()
            pdf_file = paper_dir / "paper.pdf"
            pdf_file.write_bytes(b"dummy pdf content")

            with patch("idea_graph.ingestion.extractor.ChatGoogleGenerativeAI") as mock_llm_class:
                mock_structured = MagicMock()
                mock_structured.invoke.side_effect = Exception("Persistent error")

                mock_llm = MagicMock()
                mock_llm.with_structured_output.return_value = mock_structured
                mock_llm_class.return_value = mock_llm

                service = ExtractorService(cache_dir=cache_dir, max_retries=3)
                result = service.extract(
                    paper_id="abc123",
                    file_path=pdf_file,
                    file_type=FileType.PDF,
                )

                assert result is None
