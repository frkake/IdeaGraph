"""DatasetLoader のテスト"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from idea_graph.ingestion.dataset_loader import (
    DatasetLoaderService,
    PaperMetadata,
    generate_paper_id,
    normalize_title,
)


class TestPaperMetadata:
    """PaperMetadata モデルのテスト"""

    def test_valid_paper_metadata(self):
        """有効なメタデータでの作成"""
        metadata = PaperMetadata(
            paper_id="abc123",
            title="Test Paper Title",
            references=["ref1", "ref2"],
            local_path="/path/to/paper.pdf",
        )
        assert metadata.paper_id == "abc123"
        assert metadata.title == "Test Paper Title"
        assert metadata.references == ["ref1", "ref2"]
        assert metadata.local_path == "/path/to/paper.pdf"

    def test_paper_metadata_optional_fields(self):
        """オプショナルフィールドのテスト"""
        metadata = PaperMetadata(
            paper_id="abc123",
            title="Test Paper",
            references=[],
        )
        assert metadata.local_path is None

    def test_paper_metadata_empty_references(self):
        """空の引用リストのテスト"""
        metadata = PaperMetadata(
            paper_id="abc123",
            title="Test Paper",
            references=[],
        )
        assert metadata.references == []


class TestNormalizeTitle:
    """タイトル正規化のテスト"""

    def test_lowercase(self):
        """小文字化"""
        assert normalize_title("Test Paper") == "test paper"

    def test_strip_whitespace(self):
        """空白のトリム"""
        assert normalize_title("  Test Paper  ") == "test paper"

    def test_multiple_spaces(self):
        """複数空白の圧縮"""
        assert normalize_title("Test   Paper") == "test paper"

    def test_unicode_normalization(self):
        """Unicode正規化"""
        # NFD形式の é を NFC に正規化
        title = "Café Paper"
        normalized = normalize_title(title)
        assert "café paper" == normalized or "cafe paper" == normalized


class TestGeneratePaperId:
    """論文ID生成のテスト"""

    def test_generates_hash(self):
        """ハッシュが生成されることを確認"""
        paper_id = generate_paper_id("Test Paper Title")
        assert len(paper_id) == 16  # 短いハッシュ

    def test_same_title_same_id(self):
        """同じタイトルは同じIDを生成"""
        id1 = generate_paper_id("Test Paper")
        id2 = generate_paper_id("Test Paper")
        assert id1 == id2

    def test_different_titles_different_ids(self):
        """異なるタイトルは異なるIDを生成"""
        id1 = generate_paper_id("Paper A")
        id2 = generate_paper_id("Paper B")
        assert id1 != id2

    def test_case_insensitive(self):
        """大文字小文字を無視"""
        id1 = generate_paper_id("Test Paper")
        id2 = generate_paper_id("test paper")
        assert id1 == id2


class TestDatasetLoaderService:
    """DatasetLoaderService のテスト"""

    def test_load_returns_iterator(self):
        """load() がイテレータを返すことを確認"""
        with patch("idea_graph.ingestion.dataset_loader.load_dataset") as mock_load:
            # モックデータセット
            mock_dataset = MagicMock()
            mock_dataset.__iter__ = MagicMock(return_value=iter([
                {
                    "target_paper": "Test Paper Title",
                    "find_cite": {"top_references": ["Ref 1", "Ref 2"]},
                    "paper_local_path": "/path/to/paper.pdf",
                }
            ]))
            mock_load.return_value = {"train": mock_dataset}

            service = DatasetLoaderService()
            papers = list(service.load())

            assert len(papers) == 1
            assert papers[0].title == "Test Paper Title"
            assert papers[0].references == ["Ref 1", "Ref 2"]
            assert papers[0].local_path == "/path/to/paper.pdf"

    def test_load_handles_missing_references(self):
        """引用が欠損している場合の処理"""
        with patch("idea_graph.ingestion.dataset_loader.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__iter__ = MagicMock(return_value=iter([
                {
                    "target_paper": "Test Paper",
                    "find_cite": None,
                    "paper_local_path": None,
                }
            ]))
            mock_load.return_value = {"train": mock_dataset}

            service = DatasetLoaderService()
            papers = list(service.load())

            assert len(papers) == 1
            assert papers[0].references == []
            assert papers[0].local_path is None

    def test_load_skips_duplicates(self):
        """重複論文をスキップすることを確認"""
        with patch("idea_graph.ingestion.dataset_loader.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__iter__ = MagicMock(return_value=iter([
                {
                    "target_paper": "Test Paper",
                    "find_cite": {"top_references": []},
                    "paper_local_path": None,
                },
                {
                    "target_paper": "Test Paper",  # 重複
                    "find_cite": {"top_references": []},
                    "paper_local_path": None,
                },
                {
                    "target_paper": "Different Paper",
                    "find_cite": {"top_references": []},
                    "paper_local_path": None,
                },
            ]))
            mock_load.return_value = {"train": mock_dataset}

            service = DatasetLoaderService()
            papers = list(service.load())

            assert len(papers) == 2
            titles = [p.title for p in papers]
            assert "Test Paper" in titles
            assert "Different Paper" in titles

    def test_load_handles_empty_title(self):
        """空のタイトルをスキップ"""
        with patch("idea_graph.ingestion.dataset_loader.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__iter__ = MagicMock(return_value=iter([
                {
                    "target_paper": "",
                    "find_cite": {"top_references": []},
                    "paper_local_path": None,
                },
                {
                    "target_paper": "Valid Paper",
                    "find_cite": {"top_references": []},
                    "paper_local_path": None,
                },
            ]))
            mock_load.return_value = {"train": mock_dataset}

            service = DatasetLoaderService()
            papers = list(service.load())

            assert len(papers) == 1
            assert papers[0].title == "Valid Paper"

    def test_load_handles_missing_find_cite_key(self):
        """find_cite 内の top_references キーが欠損している場合"""
        with patch("idea_graph.ingestion.dataset_loader.load_dataset") as mock_load:
            mock_dataset = MagicMock()
            mock_dataset.__iter__ = MagicMock(return_value=iter([
                {
                    "target_paper": "Test Paper",
                    "find_cite": {},  # top_references がない
                    "paper_local_path": None,
                }
            ]))
            mock_load.return_value = {"train": mock_dataset}

            service = DatasetLoaderService()
            papers = list(service.load())

            assert len(papers) == 1
            assert papers[0].references == []
