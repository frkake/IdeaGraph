"""ProgressManager のテスト"""

import tempfile
from pathlib import Path

import pytest

from idea_graph.ingestion.progress import ProgressManager, PipelineProgress


class TestProgressManager:
    """ProgressManager のテスト"""

    def test_init_creates_empty_progress(self):
        """初期化時に空の進捗が作成されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            assert manager.progress.total_papers == 0
            assert manager.progress.processed_papers == 0
            assert len(manager.progress.papers) == 0

    def test_set_total(self):
        """総論文数を設定できること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.set_total(100)
            assert manager.progress.total_papers == 100

    def test_register_paper(self):
        """論文を登録できること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.register_paper("paper1", "Test Paper 1")

            assert "paper1" in manager.progress.papers
            assert manager.progress.papers["paper1"].title == "Test Paper 1"
            assert manager.progress.papers["paper1"].status == "pending"

    def test_update_status(self):
        """ステータスを更新できること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.register_paper("paper1", "Test Paper 1")
            manager.update_status("paper1", "downloading")

            assert manager.progress.papers["paper1"].status == "downloading"
            assert manager.progress.papers["paper1"].started_at is not None

    def test_update_status_completed(self):
        """完了時にカウンターが増加すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.register_paper("paper1", "Test Paper 1")
            manager.update_status("paper1", "completed")

            assert manager.progress.papers["paper1"].status == "completed"
            assert manager.progress.papers["paper1"].completed_at is not None
            assert manager.progress.processed_papers == 1

    def test_update_status_failed(self):
        """失敗時にエラーメッセージが保存されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.register_paper("paper1", "Test Paper 1")
            manager.update_status("paper1", "failed", error_message="Download failed")

            assert manager.progress.papers["paper1"].status == "failed"
            assert manager.progress.papers["paper1"].error_message == "Download failed"
            assert manager.progress.failed_papers == 1

    def test_is_completed(self):
        """完了判定が正しく動作すること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.register_paper("paper1", "Test Paper 1")
            assert manager.is_completed("paper1") is False

            manager.update_status("paper1", "completed")
            assert manager.is_completed("paper1") is True

    def test_get_completed_papers(self):
        """完了済み論文セットを取得できること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.register_paper("paper1", "Test Paper 1")
            manager.register_paper("paper2", "Test Paper 2")
            manager.register_paper("paper3", "Test Paper 3")

            manager.update_status("paper1", "completed")
            manager.update_status("paper3", "completed")

            completed = manager.get_completed_papers()
            assert completed == {"paper1", "paper3"}

    def test_persistence(self):
        """進捗がファイルに永続化されること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"

            # 最初のインスタンスで進捗を設定
            manager1 = ProgressManager(progress_file=progress_file)
            manager1.set_total(100)
            manager1.register_paper("paper1", "Test Paper 1")
            manager1.update_status("paper1", "completed")

            # 新しいインスタンスで進捗を読み込み
            manager2 = ProgressManager(progress_file=progress_file)

            assert manager2.progress.total_papers == 100
            assert manager2.progress.processed_papers == 1
            assert "paper1" in manager2.progress.papers
            assert manager2.progress.papers["paper1"].status == "completed"

    def test_get_summary(self):
        """サマリーを取得できること"""
        with tempfile.TemporaryDirectory() as tmpdir:
            progress_file = Path(tmpdir) / "progress.json"
            manager = ProgressManager(progress_file=progress_file)

            manager.set_total(10)
            manager.register_paper("paper1", "Paper 1")
            manager.register_paper("paper2", "Paper 2")
            manager.register_paper("paper3", "Paper 3")

            manager.update_status("paper1", "completed")
            manager.update_status("paper2", "failed", "Error")

            summary = manager.get_summary()

            assert summary["total"] == 10
            assert summary["processed"] == 1
            assert summary["failed"] == 1
            assert summary["pending"] == 8
