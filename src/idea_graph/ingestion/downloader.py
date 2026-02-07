"""論文ダウンロードモジュール"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import arxiv
import httpx
from pydantic import BaseModel, ConfigDict

from idea_graph.config import settings

if TYPE_CHECKING:
    from idea_graph.ingestion.parallel import RateLimiters

logger = logging.getLogger(__name__)


class FileType(Enum):
    """ダウンロードファイルタイプ"""

    LATEX = "latex"
    PDF = "pdf"


class PaperSource(Enum):
    """論文の取得元"""

    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    CACHE = "cache"


@dataclass
class SemanticScholarResult:
    """Semantic Scholar 検索結果（内部用）"""

    paper_id: str
    title: str
    year: int | None
    venue: str | None
    open_access_pdf_url: str | None


class DownloadResult(BaseModel):
    """ダウンロード結果"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    paper_id: str
    file_path: Path | None = None
    file_type: FileType | None = None
    success: bool
    error_message: str | None = None
    published_date: datetime | None = None
    source: PaperSource | None = None


class DownloaderService:
    """論文ダウンロードサービス"""

    def __init__(
        self,
        cache_dir: Path | None = None,
        delay_seconds: float | None = None,
        max_retries: int | None = None,
        rate_limiters: "RateLimiters | None" = None,
    ):
        """初期化

        Args:
            cache_dir: キャッシュディレクトリ
            delay_seconds: ダウンロード間隔（秒）
            max_retries: 最大リトライ回数
            rate_limiters: 外部サービスのレートリミッター（並列処理時に使用）
        """
        self.cache_dir = cache_dir or settings.papers_cache_dir
        self.delay_seconds = delay_seconds if delay_seconds is not None else settings.download_delay_seconds
        self.max_retries = max_retries if max_retries is not None else settings.max_download_retries
        self.rate_limiters = rate_limiters

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
                source=PaperSource.CACHE,
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
                source=PaperSource.CACHE,
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
                    source=PaperSource.ARXIV,
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
                    source=PaperSource.ARXIV,
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

    @staticmethod
    def _normalize_title_for_matching(title: str) -> str:
        """タイトルを正規化して比較用文字列を返す"""
        title = title.lower()
        title = re.sub(r"[^\w\s]", " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def _search_semantic_scholar(self, title: str) -> SemanticScholarResult | None:
        """Semantic Scholar でタイトル検索

        Args:
            title: 論文タイトル

        Returns:
            検索結果、見つからなければ None
        """
        max_retries = settings.semantic_scholar_max_retries
        base = settings.semantic_scholar_backoff_base_seconds
        cap = settings.semantic_scholar_backoff_max_seconds
        delay = settings.semantic_scholar_request_delay_seconds

        # レート制限ディレイ
        if self.rate_limiters:
            self.rate_limiters.semantic_scholar.acquire()
        elif delay > 0:
            time.sleep(delay)

        try:
            headers = {}
            if settings.semantic_scholar_api_key:
                headers["x-api-key"] = settings.semantic_scholar_api_key

            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": title,
                "fields": "openAccessPdf,title,year,venue,externalIds",
                "limit": 5,
            }

            last_err: Exception | None = None
            for attempt in range(max(1, max_retries)):
                try:
                    resp = httpx.get(url, params=params, headers=headers, timeout=30.0)

                    if resp.status_code == 429 or resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )

                    resp.raise_for_status()
                    data = resp.json()

                    normalized_query = self._normalize_title_for_matching(title)
                    for paper in data.get("data", []):
                        paper_title = paper.get("title", "")
                        if self._normalize_title_for_matching(paper_title) == normalized_query:
                            pdf_info = paper.get("openAccessPdf") or {}
                            pdf_url = pdf_info.get("url") or None
                            return SemanticScholarResult(
                                paper_id=paper.get("paperId", ""),
                                title=paper_title,
                                year=paper.get("year"),
                                venue=paper.get("venue"),
                                open_access_pdf_url=pdf_url,
                            )

                    # タイトル一致なし
                    return None

                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    last_err = e
                    if attempt >= max_retries - 1:
                        logger.warning(f"Semantic Scholar search failed after {max_retries} retries: {e}")
                        return None

                    sleep_seconds = min(cap, base * (2**attempt))
                    sleep_seconds += random.uniform(0, 1.0)
                    logger.warning(
                        f"Semantic Scholar rate-limited/error; retrying in {sleep_seconds:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(sleep_seconds)

            if last_err:
                logger.warning(f"Semantic Scholar search failed: {last_err}")
            return None
        finally:
            if self.rate_limiters:
                self.rate_limiters.semantic_scholar.release()

    def _download_pdf_from_url(
        self,
        paper_id: str,
        pdf_url: str,
        published_year: int | None,
    ) -> DownloadResult:
        """URL から PDF をダウンロード

        Args:
            paper_id: 論文ID
            pdf_url: PDF の URL
            published_year: 公開年（近似用）

        Returns:
            ダウンロード結果
        """
        paper_dir = self._get_paper_dir(paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "paper.pdf"

        published_date = datetime(published_year, 1, 1) if published_year else None

        last_error = None
        for attempt in range(self.max_retries):
            try:
                with httpx.stream("GET", pdf_url, follow_redirects=True, timeout=60.0) as resp:
                    resp.raise_for_status()
                    with pdf_path.open("wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)

                # PDF バリデーション（マジックバイト確認）
                with pdf_path.open("rb") as f:
                    magic = f.read(4)
                if magic != b"%PDF":
                    pdf_path.unlink(missing_ok=True)
                    raise ValueError("Downloaded file is not a valid PDF")

                self._save_metadata(paper_id, published_date)
                return DownloadResult(
                    paper_id=paper_id,
                    file_path=pdf_path,
                    file_type=FileType.PDF,
                    success=True,
                    published_date=published_date,
                    source=PaperSource.SEMANTIC_SCHOLAR,
                )
            except Exception as e:
                last_error = e
                logger.debug(f"PDF download from URL attempt {attempt + 1} failed: {e}")
                pdf_path.unlink(missing_ok=True)
                if attempt < self.max_retries - 1:
                    time.sleep(self.delay_seconds * (2**attempt))

        return DownloadResult(
            paper_id=paper_id,
            file_path=None,
            file_type=None,
            success=False,
            error_message=f"PDF download from Semantic Scholar failed after {self.max_retries} retries: {last_error}",
            source=PaperSource.SEMANTIC_SCHOLAR,
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
        if self.rate_limiters:
            self.rate_limiters.arxiv.acquire()
        elif self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        # arXiv で検索
        arxiv_failed = False
        try:
            result = self._search_arxiv(title)
        except Exception as e:
            logger.warning(f"arXiv search error for '{title}': {e}")
            result = None
            arxiv_failed = True
        finally:
            if self.rate_limiters:
                self.rate_limiters.arxiv.release()

        if result:
            return self._download_with_retry(paper_id, result)

        # arXiv で見つからない/エラー → Semantic Scholar にフォールバック
        logger.info(f"arXiv {'error' if arxiv_failed else 'not found'} for '{title}', trying Semantic Scholar...")
        s2_result = self._search_semantic_scholar(title)

        if s2_result:
            if s2_result.open_access_pdf_url:
                return self._download_pdf_from_url(
                    paper_id, s2_result.open_access_pdf_url, s2_result.year
                )
            else:
                return DownloadResult(
                    paper_id=paper_id,
                    file_path=None,
                    file_type=None,
                    success=False,
                    error_message=f"Paper found on Semantic Scholar but no open access PDF: {title}",
                )

        return DownloadResult(
            paper_id=paper_id,
            file_path=None,
            file_type=None,
            success=False,
            error_message=f"Paper not found on arXiv or Semantic Scholar: {title}",
        )
