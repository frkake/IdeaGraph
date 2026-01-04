"""論文ダウンロードモジュール"""

import json
import logging
import random
import shutil
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

import arxiv
from pydantic import BaseModel, ConfigDict

from idea_graph.config import settings

logger = logging.getLogger(__name__)


class FileType(Enum):
    """ダウンロードファイルタイプ"""

    LATEX = "latex"
    PDF = "pdf"


class DownloadResult(BaseModel):
    """ダウンロード結果"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    paper_id: str
    file_path: Path | None = None
    file_type: FileType | None = None
    success: bool
    error_message: str | None = None
    published_date: datetime | None = None


class DownloaderService:
    """論文ダウンロードサービス"""

    def __init__(
        self,
        cache_dir: Path | None = None,
        delay_seconds: float | None = None,
        max_retries: int | None = None,
    ):
        """初期化

        Args:
            cache_dir: キャッシュディレクトリ
            delay_seconds: ダウンロード間隔（秒）
            max_retries: 最大リトライ回数
        """
        self.cache_dir = cache_dir or settings.papers_cache_dir
        self.delay_seconds = delay_seconds if delay_seconds is not None else settings.download_delay_seconds
        self.max_retries = max_retries if max_retries is not None else settings.max_download_retries

        # キャッシュディレクトリを作成
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_paper_dir(self, paper_id: str) -> Path:
        """論文用ディレクトリのパスを取得"""
        return self.cache_dir / paper_id

    def _load_metadata(self, paper_id: str) -> dict | None:
        """メタデータファイルを読み込み"""
        metadata_path = self._get_paper_dir(paper_id) / "metadata.json"
        if metadata_path.exists():
            with metadata_path.open() as f:
                return json.load(f)
        return None

    def _save_metadata(self, paper_id: str, published_date: datetime | None) -> None:
        """メタデータファイルを保存"""
        paper_dir = self._get_paper_dir(paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = paper_dir / "metadata.json"
        metadata = {
            "published_date": published_date.isoformat() if published_date else None,
        }
        with metadata_path.open("w") as f:
            json.dump(metadata, f)

    def _check_cache(self, paper_id: str) -> DownloadResult | None:
        """キャッシュを確認

        Returns:
            キャッシュがあれば DownloadResult、なければ None
        """
        paper_dir = self._get_paper_dir(paper_id)

        # メタデータを読み込み
        metadata = self._load_metadata(paper_id)
        published_date = None
        if metadata and metadata.get("published_date"):
            published_date = datetime.fromisoformat(metadata["published_date"])

        # LaTeX ソースを優先
        latex_path = paper_dir / "source.tar.gz"
        if latex_path.exists():
            return DownloadResult(
                paper_id=paper_id,
                file_path=latex_path,
                file_type=FileType.LATEX,
                success=True,
                published_date=published_date,
            )

        # PDF をチェック
        pdf_path = paper_dir / "paper.pdf"
        if pdf_path.exists():
            return DownloadResult(
                paper_id=paper_id,
                file_path=pdf_path,
                file_type=FileType.PDF,
                success=True,
                published_date=published_date,
            )

        return None

    def _search_arxiv(self, title: str) -> arxiv.Result | None:
        """arXiv で論文を検索

        Args:
            title: 論文タイトル

        Returns:
            検索結果、見つからなければ None
        """
        # arxiv.Client はバージョン差で引数が異なることがあるため、まずは安全に生成する
        try:
            client = arxiv.Client(delay_seconds=self.delay_seconds, num_retries=0, page_size=1)
        except TypeError:
            client = arxiv.Client()

        search = arxiv.Search(
            query=f'ti:"{title}"',
            max_results=1,
            sort_by=arxiv.SortCriterion.Relevance,
        )

        max_attempts = max(1, int(getattr(settings, "arxiv_search_max_retries", 3)))
        base = float(getattr(settings, "arxiv_search_backoff_base_seconds", 2.0))
        cap = float(getattr(settings, "arxiv_search_backoff_max_seconds", 60.0))
        jitter = float(getattr(settings, "arxiv_search_jitter_seconds", 1.0))

        last_err: Exception | None = None
        for attempt in range(max_attempts):
            try:
                results = list(client.results(search))
                if results:
                    return results[0]
                return None
            except arxiv.HTTPError as e:
                # arxiv ライブラリは 429/503 などで HTTPError を投げる
                last_err = e
                status_code = getattr(e, "status_code", None)
                retryable = status_code in (429, 500, 502, 503, 504) or status_code is None
                if not retryable or attempt >= max_attempts - 1:
                    raise

                sleep_seconds = min(cap, base * (2**attempt))
                sleep_seconds += random.uniform(0, max(0.0, jitter))
                logger.warning(
                    f"arXiv search rate-limited/temporary error (status={status_code}); "
                    f"retrying in {sleep_seconds:.1f}s (attempt {attempt + 1}/{max_attempts})"
                )
                time.sleep(sleep_seconds)
            except Exception as e:
                # ネットワーク・パース等の一時的失敗はバックオフしてリトライ
                last_err = e
                if attempt >= max_attempts - 1:
                    raise
                sleep_seconds = min(cap, base * (2**attempt))
                sleep_seconds += random.uniform(0, max(0.0, jitter))
                logger.warning(
                    f"arXiv search failed; retrying in {sleep_seconds:.1f}s "
                    f"(attempt {attempt + 1}/{max_attempts}): {e}"
                )
                time.sleep(sleep_seconds)

        if last_err:
            raise last_err
        return None

    def _download_with_retry(
        self,
        paper_id: str,
        result: arxiv.Result,
    ) -> DownloadResult:
        """リトライ付きでダウンロード

        Args:
            paper_id: 論文ID
            result: arXiv 検索結果

        Returns:
            ダウンロード結果
        """
        paper_dir = self._get_paper_dir(paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)

        # arXiv から公開日を取得
        published_date = result.published

        last_error = None

        # LaTeX ソースを試行
        for attempt in range(self.max_retries):
            try:
                downloaded_path = result.download_source(
                    dirpath=str(paper_dir),
                    filename="source.tar.gz",
                )
                # メタデータを保存
                self._save_metadata(paper_id, published_date)
                return DownloadResult(
                    paper_id=paper_id,
                    file_path=Path(downloaded_path),
                    file_type=FileType.LATEX,
                    success=True,
                    published_date=published_date,
                )
            except Exception as e:
                last_error = e
                logger.debug(f"LaTeX download attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay_seconds * (2**attempt))  # 指数バックオフ

        # PDF にフォールバック
        for attempt in range(self.max_retries):
            try:
                downloaded_path = result.download_pdf(
                    dirpath=str(paper_dir),
                    filename="paper.pdf",
                )
                # メタデータを保存
                self._save_metadata(paper_id, published_date)
                return DownloadResult(
                    paper_id=paper_id,
                    file_path=Path(downloaded_path),
                    file_type=FileType.PDF,
                    success=True,
                    published_date=published_date,
                )
            except Exception as e:
                last_error = e
                logger.debug(f"PDF download attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay_seconds * (2**attempt))

        return DownloadResult(
            paper_id=paper_id,
            file_path=None,
            file_type=None,
            success=False,
            error_message=f"Download failed after {self.max_retries} retries: {last_error}",
        )

    def download(
        self,
        paper_id: str,
        title: str,
        local_path: str | None = None,
    ) -> DownloadResult:
        """論文をダウンロード

        Args:
            paper_id: 論文ID
            title: 論文タイトル
            local_path: ローカルパス（使用しない、互換性のため）

        Returns:
            ダウンロード結果
        """
        # キャッシュを確認
        cached = self._check_cache(paper_id)
        if cached:
            logger.info(f"Using cached file for {paper_id}")
            return cached

        # レート制限
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        # arXiv で検索
        try:
            result = self._search_arxiv(title)
        except Exception as e:
            # 検索エラー（429/503など）でパイプライン全体を落とさず、失敗として記録できるようにする
            return DownloadResult(
                paper_id=paper_id,
                file_path=None,
                file_type=None,
                success=False,
                error_message=f"arXiv search failed: {e}",
            )
        if not result:
            return DownloadResult(
                paper_id=paper_id,
                file_path=None,
                file_type=None,
                success=False,
                error_message=f"Paper not found on arXiv: {title}",
            )

        # ダウンロード
        return self._download_with_retry(paper_id, result)
