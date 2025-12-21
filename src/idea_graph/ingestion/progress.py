"""パイプライン進捗管理モジュール"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from idea_graph.config import settings

logger = logging.getLogger(__name__)


class PaperProgress(BaseModel):
    """論文の処理進捗"""

    paper_id: str
    title: str
    status: str = "pending"  # pending, downloading, extracting, writing, completed, failed, not_found
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    depth: int = 0  # 探索深度（0=シード論文、1=直接引用、2=引用の引用...）
    source: str = "dataset"  # "dataset" or "citation"


class PipelineProgress(BaseModel):
    """パイプライン全体の進捗"""

    total_papers: int = 0
    processed_papers: int = 0
    failed_papers: int = 0
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())
    papers: dict[str, PaperProgress] = Field(default_factory=dict)


class ProgressManager:
    """進捗管理クラス"""

    def __init__(self, progress_file: Path | None = None):
        """初期化

        Args:
            progress_file: 進捗ファイルパス
        """
        self.progress_file = progress_file or settings.cache_dir / "progress.json"
        self._progress: PipelineProgress | None = None

    @property
    def progress(self) -> PipelineProgress:
        """進捗を取得（遅延ロード）"""
        if self._progress is None:
            self._progress = self._load()
        return self._progress

    def _load(self) -> PipelineProgress:
        """進捗をファイルから読み込み"""
        if self.progress_file.exists():
            try:
                data = json.loads(self.progress_file.read_text())
                return PipelineProgress(**data)
            except Exception as e:
                logger.warning(f"Failed to load progress file: {e}")
        return PipelineProgress()

    def _save(self) -> None:
        """進捗をファイルに保存"""
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        self._progress.last_updated = datetime.now().isoformat()
        self.progress_file.write_text(self._progress.model_dump_json(indent=2))

    def set_total(self, total: int) -> None:
        """総論文数を設定"""
        self.progress.total_papers = total
        self._save()

    def get_pending_papers(self) -> list[str]:
        """未処理の論文IDリストを取得"""
        pending = []
        for paper_id, paper in self.progress.papers.items():
            if paper.status in ("pending", "downloading", "extracting"):
                pending.append(paper_id)
        return pending

    def get_completed_papers(self) -> set[str]:
        """完了済みの論文IDセットを取得"""
        return {
            paper_id
            for paper_id, paper in self.progress.papers.items()
            if paper.status == "completed"
        }

    def is_completed(self, paper_id: str) -> bool:
        """論文が完了済みかどうか"""
        if paper_id not in self.progress.papers:
            return False
        return self.progress.papers[paper_id].status == "completed"

    def register_paper(
        self,
        paper_id: str,
        title: str,
        depth: int = 0,
        source: str = "dataset",
    ) -> None:
        """論文を登録

        Args:
            paper_id: 論文ID
            title: 論文タイトル
            depth: 探索深度（0=シード論文）
            source: ソース（"dataset" or "citation"）
        """
        if paper_id not in self.progress.papers:
            self.progress.papers[paper_id] = PaperProgress(
                paper_id=paper_id,
                title=title,
                depth=depth,
                source=source,
            )
            self._save()

    def update_status(
        self,
        paper_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """論文のステータスを更新"""
        if paper_id not in self.progress.papers:
            logger.warning(f"Paper {paper_id} not registered")
            return

        paper = self.progress.papers[paper_id]
        paper.status = status

        if status == "downloading" and paper.started_at is None:
            paper.started_at = datetime.now().isoformat()

        if status == "completed":
            paper.completed_at = datetime.now().isoformat()
            self.progress.processed_papers += 1

        if status == "failed":
            paper.error_message = error_message
            self.progress.failed_papers += 1

        self._save()

    def get_summary(self) -> dict[str, Any]:
        """進捗サマリーを取得"""
        return {
            "total": self.progress.total_papers,
            "processed": self.progress.processed_papers,
            "failed": self.progress.failed_papers,
            "pending": self.progress.total_papers
            - self.progress.processed_papers
            - self.progress.failed_papers,
            "last_updated": self.progress.last_updated,
        }
