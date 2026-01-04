"""引用論文の再帰的探索モジュール（優先度付き）"""

import heapq
import logging
from dataclasses import dataclass, field
from typing import Iterator

from idea_graph.db import Neo4jConnection
from idea_graph.ingestion.dataset_loader import PaperMetadata, generate_paper_id
from idea_graph.ingestion.downloader import DownloaderService
from idea_graph.ingestion.extractor import ExtractorService
from idea_graph.ingestion.graph_writer import GraphWriterService
from idea_graph.ingestion.progress import ProgressManager

logger = logging.getLogger(__name__)


@dataclass(order=True)
class CrawlTarget:
    """クロール対象（優先度付き）"""

    # heapq用のソートキー: 低い値ほど優先（重要度は負の値で保存）
    priority: tuple[int, int] = field(compare=True)  # (-importance_score, depth)

    # 実際のデータ（比較に含めない）
    paper_id: str = field(compare=False)
    title: str = field(compare=False)
    depth: int = field(compare=False)
    importance_score: int = field(default=3, compare=False)  # 1-5, default: 3


@dataclass
class CrawlResult:
    """クロール結果"""

    paper_id: str
    title: str
    depth: int
    status: str  # completed, failed, not_found, skipped
    error_message: str | None = None


class CitationCrawler:
    """引用論文の再帰的クローラー（重要度優先）"""

    def __init__(
        self,
        downloader: DownloaderService,
        extractor: ExtractorService,
        writer: GraphWriterService,
        progress: ProgressManager,
        max_depth: int = 1,
        crawl_limit: int | None = None,
        top_n_citations: int = 5,
    ):
        """初期化

        Args:
            downloader: ダウンロードサービス
            extractor: 抽出サービス
            writer: グラフ書き込みサービス
            progress: 進捗管理
            max_depth: 最大探索深度
            crawl_limit: クロールする最大論文数
            top_n_citations: 各論文から探索する引用の最大数（重要度上位N件）
        """
        self.downloader = downloader
        self.extractor = extractor
        self.writer = writer
        self.progress = progress
        self.max_depth = max_depth
        self.crawl_limit = crawl_limit
        self.top_n_citations = top_n_citations

        # 優先度付きキュー（heapq）
        self._queue: list[CrawlTarget] = []
        # 処理済みまたはキュー済みの paper_id
        self._visited: set[str] = set()
        # クロール済みカウント
        self._crawled_count: int = 0

    def _create_target(
        self, paper_id: str, title: str, depth: int, importance_score: int = 3
    ) -> CrawlTarget:
        """CrawlTargetを作成（優先度を自動計算）"""
        return CrawlTarget(
            priority=(-importance_score, depth),  # 重要度高い順、深度浅い順
            paper_id=paper_id,
            title=title,
            depth=depth,
            importance_score=importance_score,
        )

    def add_seeds(self, papers: list[PaperMetadata]) -> None:
        """シード論文（depth=0）を処理済みとしてマーク

        シード論文は既にメインパイプラインで処理済みなので、
        その引用論文をキューに追加する。

        Args:
            papers: シード論文リスト
        """
        for paper in papers:
            self._visited.add(paper.paper_id)

            # グラフから重要度付き引用情報を取得（上位N件）
            citations = self._get_citations_with_importance(paper.paper_id)
            top_citations = citations[: self.top_n_citations]

            added = 0
            for cited_id, cited_title, importance_score in top_citations:
                if cited_id not in self._visited:
                    target = self._create_target(cited_id, cited_title, 1, importance_score)
                    heapq.heappush(self._queue, target)
                    self._visited.add(cited_id)
                    added += 1

            logger.debug(f"Paper {paper.paper_id}: queued {added}/{len(citations)} citations")

        logger.info(f"Added {len(papers)} seed papers, {len(self._queue)} citations queued")

    def crawl(self) -> Iterator[CrawlResult]:
        """重要度優先でクロール実行

        Yields:
            CrawlResult: 各論文の処理結果
        """
        while self._queue:
            # クロール制限チェック
            if self.crawl_limit and self._crawled_count >= self.crawl_limit:
                logger.info(f"Crawl limit reached: {self.crawl_limit}")
                break

            target = heapq.heappop(self._queue)

            # 深度チェック
            if target.depth > self.max_depth:
                continue

            # 既に処理済みかチェック（progressから）
            if self.progress.is_completed(target.paper_id):
                yield CrawlResult(
                    paper_id=target.paper_id,
                    title=target.title,
                    depth=target.depth,
                    status="skipped",
                )
                continue

            logger.info(
                f"Processing: {target.title[:50]}... "
                f"(importance={target.importance_score}, depth={target.depth})"
            )

            # 処理実行
            result = self._process_paper(target)
            self._crawled_count += 1
            yield result

    def _process_paper(self, target: CrawlTarget) -> CrawlResult:
        """単一論文を処理

        Args:
            target: クロール対象

        Returns:
            CrawlResult: 処理結果
        """
        # 進捗に登録
        self.progress.register_paper(
            target.paper_id,
            target.title,
            depth=target.depth,
            source="citation",
        )

        # ダウンロード
        self.progress.update_status(target.paper_id, "downloading")
        download_result = self.downloader.download(target.paper_id, target.title)

        if not download_result.success:
            # arXivで見つからない場合は not_found として記録（失敗カウントに含めない）
            if "not found" in (download_result.error_message or "").lower():
                self.progress.update_status(target.paper_id, "not_found", download_result.error_message)
                return CrawlResult(
                    paper_id=target.paper_id,
                    title=target.title,
                    depth=target.depth,
                    status="not_found",
                    error_message=download_result.error_message,
                )
            else:
                self.progress.update_status(target.paper_id, "failed", download_result.error_message)
                return CrawlResult(
                    paper_id=target.paper_id,
                    title=target.title,
                    depth=target.depth,
                    status="failed",
                    error_message=download_result.error_message,
                )

        # 抽出
        self.progress.update_status(target.paper_id, "extracting")
        extracted = self.extractor.extract(
            target.paper_id,
            download_result.file_path,
            download_result.file_type,
        )

        if extracted is None:
            self.progress.update_status(target.paper_id, "failed", "Extraction failed")
            return CrawlResult(
                paper_id=target.paper_id,
                title=target.title,
                depth=target.depth,
                status="failed",
                error_message="Extraction failed",
            )

        # グラフに書き込み
        self.progress.update_status(target.paper_id, "writing")
        self.writer.write_extracted([extracted])

        # 完了
        self.progress.update_status(target.paper_id, "completed")

        # 引用論文をキューに追加（次の深度）
        if target.depth < self.max_depth:
            self._enqueue_citations(target.paper_id, target.depth + 1)

        return CrawlResult(
            paper_id=target.paper_id,
            title=target.title,
            depth=target.depth,
            status="completed",
        )

    def _get_citations_with_importance(
        self, paper_id: str
    ) -> list[tuple[str, str, int]]:
        """グラフから重要度付き引用情報を取得

        Args:
            paper_id: 論文ID

        Returns:
            (cited_id, cited_title, importance_score) のリスト
        """
        try:
            with Neo4jConnection.session() as session:
                result = session.run(
                    """
                    MATCH (p:Paper {id: $paper_id})-[r:CITES]->(cited:Paper)
                    RETURN cited.id AS id,
                           cited.title AS title,
                           COALESCE(r.importance_score, 3) AS importance_score
                    ORDER BY importance_score DESC
                    """,
                    paper_id=paper_id,
                )

                return [
                    (record["id"], record["title"] or "", record["importance_score"])
                    for record in result
                    if record["id"]
                ]

        except Exception as e:
            logger.warning(f"Failed to get citations for {paper_id}: {e}")
            return []

    def _enqueue_citations(self, paper_id: str, next_depth: int) -> None:
        """論文の引用論文をキューに追加（重要度上位N件）

        グラフから CITES 関係を読み取り、重要度上位N件を優先度付きでキューに追加する。

        Args:
            paper_id: 論文ID
            next_depth: 追加する論文の深度
        """
        citations = self._get_citations_with_importance(paper_id)
        top_citations = citations[: self.top_n_citations]

        for cited_id, cited_title, importance_score in top_citations:
            if cited_id not in self._visited:
                target = self._create_target(cited_id, cited_title, next_depth, importance_score)
                heapq.heappush(self._queue, target)
                self._visited.add(cited_id)

    def get_stats(self) -> dict:
        """クロール統計を取得"""
        return {
            "crawled": self._crawled_count,
            "queued": len(self._queue),
            "visited": len(self._visited),
            "max_depth": self.max_depth,
            "crawl_limit": self.crawl_limit,
            "top_n_citations": self.top_n_citations,
        }

    def get_queue_size(self) -> int:
        """現在のキューサイズを取得"""
        return len(self._queue)

    def get_total_estimate(self) -> int:
        """処理総数の推定値を取得

        crawl_limit が設定されていればその値を、
        設定されていなければ現在のキューサイズを返す。
        """
        if self.crawl_limit:
            return min(self.crawl_limit, len(self._queue))
        return len(self._queue)
