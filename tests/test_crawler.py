"""CitationCrawler のテスト"""

from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from idea_graph.ingestion.crawler import CitationCrawler, CrawlTarget, CrawlResult
from idea_graph.ingestion.dataset_loader import PaperMetadata
from idea_graph.ingestion.downloader import DownloadResult, FileType


class TestCrawlTarget:
    """CrawlTarget のテスト"""

    def test_create_crawl_target(self):
        """CrawlTarget が正しく作成されること"""
        target = CrawlTarget(
            paper_id="paper1",
            title="Test Paper",
            depth=1,
        )
        assert target.paper_id == "paper1"
        assert target.title == "Test Paper"
        assert target.depth == 1


class TestCrawlResult:
    """CrawlResult のテスト"""

    def test_create_crawl_result(self):
        """CrawlResult が正しく作成されること"""
        result = CrawlResult(
            paper_id="paper1",
            title="Test Paper",
            depth=1,
            status="completed",
        )
        assert result.paper_id == "paper1"
        assert result.title == "Test Paper"
        assert result.depth == 1
        assert result.status == "completed"
        assert result.error_message is None

    def test_create_crawl_result_with_error(self):
        """エラーメッセージ付き CrawlResult が正しく作成されること"""
        result = CrawlResult(
            paper_id="paper1",
            title="Test Paper",
            depth=1,
            status="failed",
            error_message="Download failed",
        )
        assert result.status == "failed"
        assert result.error_message == "Download failed"


class TestCitationCrawler:
    """CitationCrawler のテスト"""

    def _create_crawler(
        self,
        max_depth: int = 2,
        crawl_limit: int | None = None,
    ) -> tuple[CitationCrawler, MagicMock, MagicMock, MagicMock, MagicMock]:
        """テスト用クローラーを作成"""
        downloader = MagicMock()
        extractor = MagicMock()
        writer = MagicMock()
        progress = MagicMock()

        # デフォルトでは完了していないと返す
        progress.is_completed.return_value = False

        crawler = CitationCrawler(
            downloader=downloader,
            extractor=extractor,
            writer=writer,
            progress=progress,
            max_depth=max_depth,
            crawl_limit=crawl_limit,
        )

        return crawler, downloader, extractor, writer, progress

    def test_add_seeds_marks_visited(self):
        """add_seeds がシード論文を visited に追加すること"""
        crawler, _, _, _, _ = self._create_crawler()

        papers = [
            PaperMetadata(paper_id="seed1", title="Seed 1", references=["Ref A"]),
            PaperMetadata(paper_id="seed2", title="Seed 2", references=["Ref B"]),
        ]

        crawler.add_seeds(papers)

        # シード論文が visited に追加されている
        assert "seed1" in crawler._visited
        assert "seed2" in crawler._visited

    def test_add_seeds_queues_citations(self):
        """add_seeds が引用論文をキューに追加すること"""
        crawler, _, _, _, _ = self._create_crawler()

        papers = [
            PaperMetadata(paper_id="seed1", title="Seed 1", references=["Ref A", "Ref B"]),
        ]

        crawler.add_seeds(papers)

        # 引用論文がキューに追加されている (depth=1)
        assert len(crawler._queue) == 2
        target = crawler._queue[0]
        assert target.depth == 1

    def test_add_seeds_deduplicates_citations(self):
        """add_seeds が重複する引用を除外すること"""
        crawler, _, _, _, _ = self._create_crawler()

        papers = [
            PaperMetadata(paper_id="seed1", title="Seed 1", references=["Ref A"]),
            PaperMetadata(paper_id="seed2", title="Seed 2", references=["Ref A"]),  # 同じ引用
        ]

        crawler.add_seeds(papers)

        # 重複が除外されている
        assert len(crawler._queue) == 1

    def test_crawl_respects_max_depth(self):
        """crawl が max_depth を超えないこと"""
        crawler, downloader, extractor, writer, progress = self._create_crawler(max_depth=1)

        # depth=2 のターゲットを直接キューに追加
        crawler._queue.append(CrawlTarget(paper_id="deep", title="Deep", depth=2))
        crawler._visited.add("deep")

        results = list(crawler.crawl())

        # 深度制限により処理されない（スキップ）
        assert len(results) == 0

    def test_crawl_respects_crawl_limit(self):
        """crawl が crawl_limit を超えないこと"""
        crawler, downloader, extractor, writer, progress = self._create_crawler(crawl_limit=2)

        # ダウンロード成功を設定
        downloader.download.return_value = DownloadResult(
            paper_id="test",
            success=True,
            file_path="/tmp/test.pdf",
            file_type=FileType.PDF,
        )
        extractor.extract.return_value = MagicMock()

        # 5件のターゲットを追加
        for i in range(5):
            crawler._queue.append(CrawlTarget(paper_id=f"paper{i}", title=f"Paper {i}", depth=1))
            crawler._visited.add(f"paper{i}")

        with patch("idea_graph.ingestion.crawler.Neo4jConnection"):
            results = list(crawler.crawl())

        # crawl_limit=2 なので 2件のみ処理
        assert len(results) == 2

    def test_crawl_skips_completed_papers(self):
        """crawl が完了済み論文をスキップすること"""
        crawler, _, _, _, progress = self._create_crawler()

        # 完了済みと設定
        progress.is_completed.return_value = True

        crawler._queue.append(CrawlTarget(paper_id="done", title="Done", depth=1))
        crawler._visited.add("done")

        results = list(crawler.crawl())

        assert len(results) == 1
        assert results[0].status == "skipped"

    def test_crawl_handles_download_failure(self):
        """crawl がダウンロード失敗を処理すること"""
        crawler, downloader, _, _, progress = self._create_crawler()

        downloader.download.return_value = DownloadResult(
            paper_id="test",
            success=False,
            error_message="Connection error",
        )

        crawler._queue.append(CrawlTarget(paper_id="fail", title="Fail", depth=1))
        crawler._visited.add("fail")

        results = list(crawler.crawl())

        assert len(results) == 1
        assert results[0].status == "failed"
        assert results[0].error_message == "Connection error"

    def test_crawl_handles_not_found(self):
        """crawl が not found を正しく処理すること"""
        crawler, downloader, _, _, progress = self._create_crawler()

        downloader.download.return_value = DownloadResult(
            paper_id="test",
            success=False,
            error_message="Paper not found on arXiv",
        )

        crawler._queue.append(CrawlTarget(paper_id="missing", title="Missing", depth=1))
        crawler._visited.add("missing")

        results = list(crawler.crawl())

        assert len(results) == 1
        assert results[0].status == "not_found"

    def test_crawl_handles_extraction_failure(self):
        """crawl が抽出失敗を処理すること"""
        crawler, downloader, extractor, _, progress = self._create_crawler()

        downloader.download.return_value = DownloadResult(
            paper_id="test",
            success=True,
            file_path="/tmp/test.pdf",
            file_type=FileType.PDF,
        )
        extractor.extract.return_value = None

        crawler._queue.append(CrawlTarget(paper_id="extract_fail", title="Extract Fail", depth=1))
        crawler._visited.add("extract_fail")

        results = list(crawler.crawl())

        assert len(results) == 1
        assert results[0].status == "failed"
        assert results[0].error_message == "Extraction failed"

    def test_crawl_successful_processing(self):
        """crawl が正常処理を行うこと"""
        crawler, downloader, extractor, writer, progress = self._create_crawler(max_depth=1)

        downloader.download.return_value = DownloadResult(
            paper_id="test",
            success=True,
            file_path="/tmp/test.pdf",
            file_type=FileType.PDF,
        )
        extractor.extract.return_value = MagicMock()

        crawler._queue.append(CrawlTarget(paper_id="success", title="Success", depth=1))
        crawler._visited.add("success")

        with patch("idea_graph.ingestion.crawler.Neo4jConnection"):
            results = list(crawler.crawl())

        assert len(results) == 1
        assert results[0].status == "completed"

        # 各サービスが呼ばれたことを確認
        downloader.download.assert_called_once()
        extractor.extract.assert_called_once()
        writer.write_extracted.assert_called_once()

    def test_get_stats(self):
        """get_stats が正しい統計を返すこと"""
        crawler, _, _, _, _ = self._create_crawler(max_depth=2, crawl_limit=100)

        crawler._queue.append(CrawlTarget(paper_id="q1", title="Q1", depth=1))
        crawler._visited.add("v1")
        crawler._visited.add("v2")
        crawler._crawled_count = 5

        stats = crawler.get_stats()

        assert stats["crawled"] == 5
        assert stats["queued"] == 1
        assert stats["visited"] == 2
        assert stats["max_depth"] == 2
        assert stats["crawl_limit"] == 100

    def test_enqueue_citations_from_graph(self):
        """_enqueue_citations がグラフから引用を取得すること"""
        crawler, _, _, _, _ = self._create_crawler()

        # Neo4j セッションをモック
        mock_record1 = {"id": "cited1", "title": "Cited Paper 1"}
        mock_record2 = {"id": "cited2", "title": "Cited Paper 2"}

        with patch("idea_graph.ingestion.crawler.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.run.return_value = [mock_record1, mock_record2]

            crawler._enqueue_citations("paper1", 2)

        # 引用がキューに追加されている
        assert len(crawler._queue) == 2
        assert crawler._queue[0].depth == 2
        assert "cited1" in crawler._visited
        assert "cited2" in crawler._visited

    def test_enqueue_citations_skips_visited(self):
        """_enqueue_citations が既訪問の引用をスキップすること"""
        crawler, _, _, _, _ = self._create_crawler()

        # 既に visited に追加
        crawler._visited.add("cited1")

        mock_record = {"id": "cited1", "title": "Already Visited"}

        with patch("idea_graph.ingestion.crawler.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)
            mock_session.run.return_value = [mock_record]

            crawler._enqueue_citations("paper1", 2)

        # キューに追加されていない
        assert len(crawler._queue) == 0
