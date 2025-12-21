"""HuggingFace データセット読み込みモジュール"""

import hashlib
import unicodedata
from typing import Iterator

from datasets import load_dataset
from pydantic import BaseModel


class PaperMetadata(BaseModel):
    """論文メタデータ"""

    paper_id: str
    title: str
    references: list[str]
    local_path: str | None = None


def normalize_title(title: str) -> str:
    """タイトルを正規化

    Args:
        title: 論文タイトル

    Returns:
        正規化されたタイトル
    """
    # Unicode 正規化 (NFC)
    normalized = unicodedata.normalize("NFC", title)
    # 小文字化
    normalized = normalized.lower()
    # 空白のトリムと複数空白の圧縮
    normalized = " ".join(normalized.split())
    return normalized


def generate_paper_id(title: str) -> str:
    """タイトルから論文IDを生成

    Args:
        title: 論文タイトル

    Returns:
        16文字のハッシュベースID
    """
    normalized = normalize_title(title)
    hash_obj = hashlib.sha256(normalized.encode("utf-8"))
    return hash_obj.hexdigest()[:16]


class DatasetLoaderService:
    """HuggingFace データセットローダー"""

    def __init__(self, dataset_name: str = "yanshengqiu/AI_Idea_Bench_2025"):
        """初期化

        Args:
            dataset_name: HuggingFace データセット名
        """
        self.dataset_name = dataset_name

    def load(self) -> Iterator[PaperMetadata]:
        """データセットを読み込み、論文メタデータのイテレータを返す

        Yields:
            PaperMetadata: 各論文のメタデータ
        """
        dataset = load_dataset(self.dataset_name)
        seen_ids: set[str] = set()

        # データセットの利用可能なスプリットを検出
        available_splits = list(dataset.keys())
        split_name = "train" if "train" in available_splits else available_splits[0]

        for item in dataset[split_name]:
            title = item.get("target_paper", "")

            # 空のタイトルをスキップ
            if not title or not title.strip():
                continue

            paper_id = generate_paper_id(title)

            # 重複をスキップ
            if paper_id in seen_ids:
                continue
            seen_ids.add(paper_id)

            # 引用情報の抽出
            find_cite = item.get("find_cite")
            references = []
            if find_cite and isinstance(find_cite, dict):
                top_refs = find_cite.get("top_references")
                if isinstance(top_refs, dict):
                    # top_references が dict の場合は title キーからリストを取得
                    references = top_refs.get("title", []) or []
                elif isinstance(top_refs, list):
                    # top_references が直接リストの場合
                    references = top_refs

            # ローカルパスの抽出
            local_path = item.get("paper_local_path")

            yield PaperMetadata(
                paper_id=paper_id,
                title=title,
                references=references,
                local_path=local_path,
            )
