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
        # カウンタは「状態から再計算」してズレ/二重カウントを防ぐ
        processed, failed = self._recompute_counters()
        self._progress.processed_papers = processed
        self._progress.failed_papers = failed
        self._progress.last_updated = datetime.now().isoformat()
        self.progress_file.write_text(self._progress.model_dump_json(indent=2))

    def _recompute_counters(self) -> tuple[int, int]:
        """papers の状態から processed/failed を再計算する。

        注: ここでの processed/failed は主に dataset の進捗表示用途のため、
        dataset と citation を分けた詳細集計は get_summary() 側で返す。
        """
        processed = 0
        failed = 0
        for p in self.progress.papers.values():
            if p.source != "dataset":
                continue
            if p.status == "completed":
                processed += 1
            elif p.status in ("failed", "not_found"):
                failed += 1
        return processed, failed

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
        prev_status = paper.status
        paper.status = status

        if status == "downloading" and paper.started_at is None:
            paper.started_at = datetime.now().isoformat()

        if status == "completed" and paper.completed_at is None:
            paper.completed_at = datetime.now().isoformat()

        if status in ("failed", "not_found"):
            paper.error_message = error_message
        else:
            # 失敗からの復旧などで error_message が残るのを避ける
            if prev_status in ("failed", "not_found") and status not in ("failed", "not_found"):
                paper.error_message = None

        self._save()

    def get_summary(self) -> dict[str, Any]:
        """進捗サマリーを取得"""
        # dataset（元データセット）を「主進捗」としつつ、citation を含む全体も返す
        by_source: dict[str, dict[str, int]] = {}
        for p in self.progress.papers.values():
            src = p.source or "unknown"
            if src not in by_source:
                by_source[src] = {
                    "total_known": 0,
                    "completed": 0,
                    "failed": 0,
                    "not_found": 0,
                    "in_progress": 0,
                    "pending": 0,
                }
            s = by_source[src]
            s["total_known"] += 1
            if p.status == "completed":
                s["completed"] += 1
            elif p.status == "failed":
                s["failed"] += 1
            elif p.status == "not_found":
                s["not_found"] += 1
            elif p.status in ("downloading", "extracting", "writing"):
                s["in_progress"] += 1
            else:
                s["pending"] += 1

        dataset = by_source.get("dataset", {})
        dataset_processed = int(dataset.get("completed", 0))
        dataset_failed = int(dataset.get("failed", 0)) + int(dataset.get("not_found", 0))
        dataset_total = int(self.progress.total_papers)
        dataset_pending = max(0, dataset_total - dataset_processed - dataset_failed)

        known_total = sum(v["total_known"] for v in by_source.values()) if by_source else 0
        known_completed = sum(v["completed"] for v in by_source.values()) if by_source else 0
        known_failed = sum(v["failed"] for v in by_source.values()) if by_source else 0
        known_not_found = sum(v["not_found"] for v in by_source.values()) if by_source else 0
        known_in_progress = sum(v["in_progress"] for v in by_source.values()) if by_source else 0
        known_pending = sum(v["pending"] for v in by_source.values()) if by_source else 0

        return {
            # 互換キー（従来通り dataset の進捗）
            "total": dataset_total,
            "processed": dataset_processed,
            "failed": dataset_failed,
            "pending": dataset_pending,
            "last_updated": self.progress.last_updated,
            # 追加情報（citation を含む全体）
            "known_total": known_total,
            "known_completed": known_completed,
            "known_failed": known_failed,
            "known_not_found": known_not_found,
            "known_in_progress": known_in_progress,
            "known_pending": known_pending,
            "by_source": by_source,
        }
