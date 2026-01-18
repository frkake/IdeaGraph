"""分析結果・提案の保存・読み込みサービス"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from idea_graph.config import settings


class SavedAnalysis(BaseModel):
    """保存された分析結果"""

    id: str
    target_paper_id: str
    target_paper_title: str | None = None
    multihop_k: int
    candidates_count: int
    total_paths: int | None = None
    total_paper_paths: int | None = None
    total_entity_paths: int | None = None
    saved_at: str
    data: dict[str, Any]


class SavedProposal(BaseModel):
    """保存された提案"""

    id: str
    target_paper_id: str
    target_paper_title: str | None = None
    analysis_id: str | None = None
    title: str
    proposal_type: str | None = None
    prompt: str | None = None
    rating: int | None = None
    notes: str | None = None
    saved_at: str
    data: dict[str, Any]


class StorageService:
    """分析・提案の保存・読み込みを管理するサービス"""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(settings.cache_dir)
        self.analyses_dir = self.base_dir / "analyses"
        self.proposals_dir = self.base_dir / "proposals"
        self.idea_graph_dir = self.proposals_dir / "idea-graph"
        self.target_proposals_dir = self.proposals_dir / "target"

        # ディレクトリ作成
        self.analyses_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.idea_graph_dir.mkdir(parents=True, exist_ok=True)
        self.target_proposals_dir.mkdir(parents=True, exist_ok=True)

    def _safe_paper_id(self, paper_id: str) -> str:
        return paper_id.replace("/", "_").replace(":", "_")

    def _proposal_root_dir(self, proposal_type: str) -> Path:
        if proposal_type == "idea-graph":
            return self.idea_graph_dir
        if proposal_type == "target":
            return self.target_proposals_dir
        return self.proposals_dir

    def _iter_proposal_files(self) -> list[Path]:
        files: list[Path] = []
        for root in (self.idea_graph_dir, self.target_proposals_dir):
            if root.exists():
                files.extend(root.rglob("*.json"))
        if self.proposals_dir.exists():
            files.extend(self.proposals_dir.glob("*.json"))
        return files

    def _find_proposal_file(self, proposal_id: str) -> Path | None:
        legacy = self.proposals_dir / f"{proposal_id}.json"
        if legacy.exists():
            return legacy
        for root in (self.idea_graph_dir, self.target_proposals_dir):
            if not root.exists():
                continue
            matches = list(root.rglob(f"{proposal_id}.json"))
            if matches:
                return matches[0]
        return None

    # ========== 分析 ==========

    def save_analysis(
        self,
        target_paper_id: str,
        analysis_result: dict[str, Any],
        target_paper_title: str | None = None,
    ) -> SavedAnalysis:
        """分析結果を保存"""
        analysis_id = str(uuid4())[:8]
        saved_at = datetime.now().isoformat()

        saved = SavedAnalysis(
            id=analysis_id,
            target_paper_id=target_paper_id,
            target_paper_title=target_paper_title,
            multihop_k=analysis_result.get("multihop_k", 0),
            candidates_count=len(analysis_result.get("candidates", [])),
            total_paths=analysis_result.get("total_paths"),
            total_paper_paths=analysis_result.get("total_paper_paths"),
            total_entity_paths=analysis_result.get("total_entity_paths"),
            saved_at=saved_at,
            data=analysis_result,
        )

        # ファイルに保存
        file_path = self.analyses_dir / f"{analysis_id}.json"
        file_path.write_text(saved.model_dump_json(indent=2), encoding="utf-8")

        return saved

    def load_analysis(self, analysis_id: str) -> SavedAnalysis | None:
        """分析結果を読み込み"""
        file_path = self.analyses_dir / f"{analysis_id}.json"
        if not file_path.exists():
            return None

        data = json.loads(file_path.read_text(encoding="utf-8"))
        return SavedAnalysis(**data)

    def list_analyses(
        self, target_paper_id: str | None = None, limit: int = 50
    ) -> list[SavedAnalysis]:
        """保存された分析結果の一覧を取得"""
        analyses = []

        for file_path in sorted(
            self.analyses_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                saved = SavedAnalysis(**data)

                if target_paper_id is None or saved.target_paper_id == target_paper_id:
                    analyses.append(saved)

                if len(analyses) >= limit:
                    break
            except Exception:
                continue

        return analyses

    def delete_analysis(self, analysis_id: str) -> bool:
        """分析結果を削除"""
        file_path = self.analyses_dir / f"{analysis_id}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    # ========== 提案 ==========

    def save_proposal(
        self,
        target_paper_id: str,
        proposal: dict[str, Any],
        target_paper_title: str | None = None,
        analysis_id: str | None = None,
        prompt: str | None = None,
        rating: int | None = None,
        notes: str | None = None,
        proposal_type: str = "idea-graph",
    ) -> SavedProposal:
        """提案を保存"""
        proposal_id = str(uuid4())[:8]
        saved_at = datetime.now().isoformat()

        saved = SavedProposal(
            id=proposal_id,
            target_paper_id=target_paper_id,
            target_paper_title=target_paper_title,
            analysis_id=analysis_id,
            title=proposal.get("title", "Untitled"),
            proposal_type=proposal_type,
            prompt=prompt,
            rating=rating,
            notes=notes,
            saved_at=saved_at,
            data=proposal,
        )

        # ファイルに保存
        paper_dir = self._proposal_root_dir(proposal_type) / self._safe_paper_id(target_paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)
        file_path = paper_dir / f"{proposal_id}.json"
        file_path.write_text(saved.model_dump_json(indent=2), encoding="utf-8")

        return saved

    def load_proposal(self, proposal_id: str) -> SavedProposal | None:
        """提案を読み込み"""
        file_path = self._find_proposal_file(proposal_id)
        if file_path is None:
            return None

        data = json.loads(file_path.read_text(encoding="utf-8"))
        return SavedProposal(**data)

    def list_proposals(
        self, target_paper_id: str | None = None, limit: int = 50
    ) -> list[SavedProposal]:
        """保存された提案の一覧を取得"""
        proposals = []

        seen_ids: set[str] = set()
        for file_path in sorted(
            self._iter_proposal_files(), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                saved = SavedProposal(**data)

                if saved.id in seen_ids:
                    continue
                seen_ids.add(saved.id)

                if target_paper_id is None or saved.target_paper_id == target_paper_id:
                    proposals.append(saved)

                if len(proposals) >= limit:
                    break
            except Exception:
                continue

        return proposals

    def update_proposal(
        self,
        proposal_id: str,
        rating: int | None = None,
        notes: str | None = None,
    ) -> SavedProposal | None:
        """提案の評価・メモを更新"""
        saved = self.load_proposal(proposal_id)
        if saved is None:
            return None

        if rating is not None:
            saved.rating = rating
        if notes is not None:
            saved.notes = notes

        # ファイルを更新
        file_path = self._find_proposal_file(proposal_id)
        if file_path is None:
            return None
        file_path.write_text(saved.model_dump_json(indent=2), encoding="utf-8")

        return saved

    def delete_proposal(self, proposal_id: str) -> bool:
        """提案を削除"""
        file_path = self._find_proposal_file(proposal_id)
        if file_path and file_path.exists():
            file_path.unlink()
            return True
        return False

    # ========== エクスポート ==========

    def export_proposals_markdown(
        self, proposal_ids: list[str] | None = None, target_paper_id: str | None = None
    ) -> str:
        """提案をMarkdown形式でエクスポート"""
        if proposal_ids:
            proposals = [self.load_proposal(pid) for pid in proposal_ids]
            proposals = [p for p in proposals if p is not None]
        else:
            proposals = self.list_proposals(target_paper_id=target_paper_id)

        if not proposals:
            return "# 提案なし\n\n保存された提案がありません。"

        md = "# 研究提案\n\n"
        md += f"エクスポート日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        md += "---\n\n"

        for i, saved in enumerate(proposals, 1):
            proposal = saved.data
            md += f"## 提案 {i}: {proposal.get('title', 'Untitled')}\n\n"
            md += f"- **対象論文**: {saved.target_paper_id}\n"
            if saved.rating:
                md += f"- **評価**: {'★' * saved.rating}{'☆' * (5 - saved.rating)}\n"
            if saved.notes:
                md += f"- **メモ**: {saved.notes}\n"
            md += f"- **保存日時**: {saved.saved_at}\n\n"

            if saved.prompt:
                md += "### 生成プロンプト\n"
                md += "```text\n"
                md += f"{saved.prompt}\n"
                md += "```\n\n"

            md += f"### 動機\n{proposal.get('motivation', 'N/A')}\n\n"
            md += f"### 手法\n{proposal.get('method', 'N/A')}\n\n"

            if "experiment" in proposal:
                exp = proposal["experiment"]
                md += "### 実験計画\n"
                md += f"- **データセット**: {', '.join(exp.get('datasets', []))}\n"
                md += f"- **ベースライン**: {', '.join(exp.get('baselines', []))}\n"
                md += f"- **評価指標**: {', '.join(exp.get('metrics', []))}\n"
                md += f"- **アブレーション**: {', '.join(exp.get('ablations', []))}\n"
                md += f"- **期待結果**: {exp.get('expected_results', 'N/A')}\n"
                md += f"- **失敗時の解釈**: {exp.get('failure_interpretation', 'N/A')}\n\n"

            if "differences" in proposal:
                md += "### 既存研究との差異\n"
                for diff in proposal["differences"]:
                    md += f"- {diff}\n"
                md += "\n"

            if "grounding" in proposal:
                grounding = proposal["grounding"]
                md += "### 根拠\n"
                md += f"- **関連論文**: {', '.join(grounding.get('papers', []))}\n"
                md += f"- **関連エンティティ**: {', '.join(grounding.get('entities', []))}\n\n"

            md += "---\n\n"

        return md

    def export_proposals_json(
        self, proposal_ids: list[str] | None = None, target_paper_id: str | None = None
    ) -> str:
        """提案をJSON形式でエクスポート"""
        if proposal_ids:
            proposals = [self.load_proposal(pid) for pid in proposal_ids]
            proposals = [p for p in proposals if p is not None]
        else:
            proposals = self.list_proposals(target_paper_id=target_paper_id)

        export_data = {
            "exported_at": datetime.now().isoformat(),
            "proposals": [p.model_dump() for p in proposals],
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)
