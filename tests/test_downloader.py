"""PaperDownloader のテスト"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from idea_graph.ingestion.downloader import (
    DownloaderService,
    DownloadResult,
    FileType,
)


class TestDownloadResult:
    """DownloadResult モデルのテスト"""

    def test_successful_result(self):
        """成功結果の作成"""
        result = DownloadResult(
            paper_id="abc123",
            file_path=Path("/path/to/file.tar.gz"),
            file_type=FileType.LATEX,
            success=True,
            error_message=None,
        )
        assert result.success is True
        assert result.file_type == FileType.LATEX

    def test_failed_result(self):
        """失敗結果の作成"""
        result = DownloadResult(
            paper_id="abc123",
            file_path=None,
            file_type=None,
            success=False,
            error_message="Download failed",
        )
        assert result.success is False
        assert result.error_message == "Download failed"


class TestFileType:
    """FileType 列挙型のテスト"""

    def test_latex_value(self):
        """LATEX の値"""
        assert FileType.LATEX.value == "latex"

    def test_pdf_value(self):
        """PDF の値"""
        assert FileType.PDF.value == "pdf"


class TestDownloaderService:
    """DownloaderService のテスト"""

    def test_init_creates_cache_dir(self):
        """初期化時にキャッシュディレクトリが作成されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "cache"
            service = DownloaderService(cache_dir=cache_dir)
            assert cache_dir.exists()

    def test_download_returns_cached_file(self):
        """キャッシュ済みファイルを返すこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_id = "abc123"

            # キャッシュファイルを作成
            paper_dir = cache_dir / paper_id
            paper_dir.mkdir(parents=True)
            cached_file = paper_dir / "source.tar.gz"
            cached_file.write_text("cached content")

            service = DownloaderService(cache_dir=cache_dir)
            result = service.download(paper_id=paper_id, title="Test Paper")

            assert result.success is True
            assert result.file_path == cached_file
            assert result.file_type == FileType.LATEX

    def test_download_returns_cached_pdf(self):
        """キャッシュ済みPDFファイルを返すこと"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            paper_id = "abc123"

            # PDFキャッシュファイルを作成
            paper_dir = cache_dir / paper_id
            paper_dir.mkdir(parents=True)
            cached_file = paper_dir / "paper.pdf"
            cached_file.write_text("cached pdf content")

            service = DownloaderService(cache_dir=cache_dir)
            result = service.download(paper_id=paper_id, title="Test Paper")

            assert result.success is True
            assert result.file_path == cached_file
            assert result.file_type == FileType.PDF

    def test_download_from_arxiv_latex(self):
        """arXiv から LaTeX ソースをダウンロード"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with patch("idea_graph.ingestion.downloader.arxiv.Client") as mock_client_class:
                # モックの設定
                mock_result = MagicMock()
                mock_result.entry_id = "http://arxiv.org/abs/2101.00001"
                mock_result.download_source = MagicMock(return_value=Path(tmpdir) / "source.tar.gz")

                mock_client = MagicMock()
                mock_client.results.return_value = iter([mock_result])
                mock_client_class.return_value = mock_client

                # ダウンロードされるファイルを作成
                (Path(tmpdir) / "source.tar.gz").write_text("latex content")

                service = DownloaderService(cache_dir=cache_dir, delay_seconds=0)
                result = service.download(paper_id="abc123", title="Test Paper on Neural Networks")

                assert result.success is True
                assert result.file_type == FileType.LATEX

    def test_download_fallback_to_pdf(self):
        """LaTeX がない場合に PDF にフォールバック"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with patch("idea_graph.ingestion.downloader.arxiv.Client") as mock_client_class:
                mock_result = MagicMock()
                mock_result.entry_id = "http://arxiv.org/abs/2101.00001"
                mock_result.download_source = MagicMock(side_effect=Exception("No source available"))
                mock_result.download_pdf = MagicMock(return_value=Path(tmpdir) / "paper.pdf")

                mock_client = MagicMock()
                mock_client.results.return_value = iter([mock_result])
                mock_client_class.return_value = mock_client

                # ダウンロードされるPDFファイルを作成
                (Path(tmpdir) / "paper.pdf").write_text("pdf content")

                service = DownloaderService(cache_dir=cache_dir, delay_seconds=0)
                result = service.download(paper_id="abc123", title="Test Paper")

                assert result.success is True
                assert result.file_type == FileType.PDF

    def test_download_not_found(self):
        """論文が見つからない場合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with patch("idea_graph.ingestion.downloader.arxiv.Client") as mock_client_class:
                mock_client = MagicMock()
                mock_client.results.return_value = iter([])
                mock_client_class.return_value = mock_client

                service = DownloaderService(cache_dir=cache_dir, delay_seconds=0)
                result = service.download(paper_id="abc123", title="Nonexistent Paper")

                assert result.success is False
                assert "not found" in result.error_message.lower()

    def test_download_with_retry(self):
        """リトライが機能すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with patch("idea_graph.ingestion.downloader.arxiv.Client") as mock_client_class:
                mock_result = MagicMock()
                mock_result.entry_id = "http://arxiv.org/abs/2101.00001"

                # 最初の2回は失敗、3回目で成功
                call_count = 0

                def download_source_side_effect(dirpath, filename):
                    nonlocal call_count
                    call_count += 1
                    if call_count < 3:
                        raise Exception("Temporary error")
                    file_path = Path(dirpath) / filename
                    file_path.write_text("latex content")
                    return file_path

                mock_result.download_source = MagicMock(side_effect=download_source_side_effect)

                mock_client = MagicMock()
                mock_client.results.return_value = iter([mock_result])
                mock_client_class.return_value = mock_client

                service = DownloaderService(cache_dir=cache_dir, delay_seconds=0, max_retries=3)
                result = service.download(paper_id="abc123", title="Test Paper")

                assert result.success is True
                assert call_count == 3

    def test_download_max_retries_exceeded(self):
        """最大リトライ回数を超えた場合"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)

            with patch("idea_graph.ingestion.downloader.arxiv.Client") as mock_client_class:
                mock_result = MagicMock()
                mock_result.entry_id = "http://arxiv.org/abs/2101.00001"
                mock_result.download_source = MagicMock(side_effect=Exception("Persistent error"))
                mock_result.download_pdf = MagicMock(side_effect=Exception("Persistent error"))

                mock_client = MagicMock()
                mock_client.results.return_value = iter([mock_result])
                mock_client_class.return_value = mock_client

                service = DownloaderService(cache_dir=cache_dir, delay_seconds=0, max_retries=3)
                result = service.download(paper_id="abc123", title="Test Paper")

                assert result.success is False
                assert "error" in result.error_message.lower() or "failed" in result.error_message.lower()
