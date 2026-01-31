"""出力形式の制約定数"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputConstraints:
    """アイデア生成・抽出時の出力文字数制限

    proposal.py と evaluation.py で共通で使用する。
    比較評価時に同等の詳細度を保証するため、両者で同じ制限を適用する。
    """

    # タイトル
    TITLE: str = "1-2 sentences"

    # 主要テキストフィールド（語数）
    MOTIVATION_WORDS: str = "200-300 words"
    METHOD_WORDS: str = "200-300 words"
    RATIONALE_WORDS: str = "200-300 words"
    RESEARCH_TRENDS_WORDS: str = "200-300 words"
    EXPECTED_RESULTS_WORDS: str = "100-150 words"
    MAIN_RESULTS_WORDS: str = "100-150 words"
    FAILURE_INTERPRETATION_WORDS: str = "50-100 words"

    # リスト項目（項目数と各項目の語数）
    DIFFERENCES_COUNT: str = "3-5 items"
    DIFFERENCES_WORDS_EACH: str = "30-50 words"

    DATASETS_COUNT: str = "3-5 items"
    DATASETS_WORDS_EACH: str = "5-15 words"

    BASELINES_COUNT: str = "3-5 items"
    BASELINES_WORDS_EACH: str = "5-15 words"

    METRICS_COUNT: str = "3-5 items"
    METRICS_WORDS_EACH: str = "5-15 words"

    ABLATIONS_COUNT: str = "2-4 items"
    ABLATIONS_WORDS_EACH: str = "20-40 words"

    # ヘルパーメソッド：リスト項目の説明を生成
    def list_constraint(self, count: str, words_each: str) -> str:
        """リスト項目の制約文字列を生成"""
        return f"({count}, each {words_each})"

    def differences_constraint(self) -> str:
        return self.list_constraint(self.DIFFERENCES_COUNT, self.DIFFERENCES_WORDS_EACH)

    def datasets_constraint(self) -> str:
        return self.list_constraint(self.DATASETS_COUNT, self.DATASETS_WORDS_EACH)

    def baselines_constraint(self) -> str:
        return self.list_constraint(self.BASELINES_COUNT, self.BASELINES_WORDS_EACH)

    def metrics_constraint(self) -> str:
        return self.list_constraint(self.METRICS_COUNT, self.METRICS_WORDS_EACH)

    def ablations_constraint(self) -> str:
        return self.list_constraint(self.ABLATIONS_COUNT, self.ABLATIONS_WORDS_EACH)


# シングルトンインスタンス
OUTPUT_CONSTRAINTS = OutputConstraints()
