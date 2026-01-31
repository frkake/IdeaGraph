"""アンカー論文フィルタリング

CoI-Agent実行時にアンカー論文の内容をプロンプトから除外するためのフィルタ。
PDFからタイトルのみを抽出し、論文本文がLLMに渡らないようにする。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# scipdfはcoiグループにのみ含まれるため、遅延インポート用にモジュールレベルで参照
# テスト時にモックできるようにする
try:
    import scipdf
except ImportError:
    scipdf = None  # type: ignore

logger = logging.getLogger(__name__)


class AnchorFilterError(Exception):
    """アンカー論文フィルタリングエラー"""

    pass


@dataclass
class AnchorFilterResult:
    """フィルタリング結果"""

    topic: str
    """処理後のトピック（タイトル含む場合あり）"""

    anchor_paper_path: str | None
    """フィルタ後のパス（除外時はNone）"""

    anchor_title: str | None
    """抽出されたアンカー論文タイトル（除外時のみ）"""


class AnchorFilter:
    """アンカー論文フィルタ

    PDFからタイトルのみを抽出し、論文内容を除外した状態で
    CoI-Agent実行を準備する。
    """

    def filter_anchor(
        self,
        topic: str,
        anchor_paper_path: str | None,
        exclude_anchor_content: bool = True,
    ) -> AnchorFilterResult:
        """アンカー論文のフィルタリング処理

        Args:
            topic: 研究トピック
            anchor_paper_path: アンカー論文PDFパス
            exclude_anchor_content: 内容除外フラグ

        Returns:
            フィルタ結果（処理後のtopicとanchor_paper_path）

        Raises:
            AnchorFilterError: フィルタリング失敗時
        """
        # パス未指定時は従来動作を維持
        if anchor_paper_path is None:
            logger.debug("No anchor paper path specified, using original topic")
            return AnchorFilterResult(
                topic=topic,
                anchor_paper_path=None,
                anchor_title=None,
            )

        # 除外しない場合は元のパスをそのまま返す
        if not exclude_anchor_content:
            logger.debug("exclude_anchor_content=False, keeping original path")
            return AnchorFilterResult(
                topic=topic,
                anchor_paper_path=anchor_paper_path,
                anchor_title=None,
            )

        # 除外する場合：タイトルを抽出してパスをNoneにする
        logger.info(f"Extracting title from anchor paper: {anchor_paper_path}")
        anchor_title = self.extract_title_from_pdf(anchor_paper_path)

        # トピックとタイトルを組み合わせる
        combined_topic = f"{topic} (Related to: {anchor_title})"
        logger.info(f"Anchor paper title extracted: {anchor_title}")
        logger.info(f"Combined topic: {combined_topic}")

        return AnchorFilterResult(
            topic=combined_topic,
            anchor_paper_path=None,
            anchor_title=anchor_title,
        )

    def extract_title_from_pdf(self, pdf_path: str) -> str:
        """PDFからタイトルのみを抽出

        Args:
            pdf_path: PDFファイルのパス

        Returns:
            抽出されたタイトル

        Raises:
            AnchorFilterError: 抽出失敗時
        """
        # ファイル存在確認
        path = Path(pdf_path)
        if not path.exists():
            error_msg = f"Anchor paper file not found: {pdf_path}"
            logger.error(error_msg)
            raise AnchorFilterError(error_msg)

        # scipdfでPDFをパース
        try:
            if scipdf is None:
                raise ImportError("scipdf is not installed. Install with: uv sync --group coi")
            article_dict = scipdf.parse_pdf_to_dict(str(path))
        except Exception as e:
            error_msg = f"Failed to parse anchor paper PDF. Ensure Grobid is running. Error: {e}"
            logger.error(error_msg)
            raise AnchorFilterError(error_msg)

        # パース結果の確認
        if article_dict is None:
            error_msg = "Failed to parse anchor paper PDF. Ensure Grobid is running."
            logger.error(error_msg)
            raise AnchorFilterError(error_msg)

        # タイトルの抽出
        title = article_dict.get("title")
        if not title:
            error_msg = "Failed to extract title from anchor paper"
            logger.error(error_msg)
            raise AnchorFilterError(error_msg)

        return title
