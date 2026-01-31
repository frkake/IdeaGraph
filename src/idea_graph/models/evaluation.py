"""評価機能のデータモデル"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from idea_graph.services.proposal import Proposal


class IdeaSource(str, Enum):
    """アイデアのソース（生成元）"""

    IDEAGRAPH = "ideagraph"
    COI = "coi"
    TARGET_PAPER = "target_paper"


class EvaluationMetric(str, Enum):
    """評価指標（5つのアイデア評価指標）"""

    NOVELTY = "novelty"
    SIGNIFICANCE = "significance"
    FEASIBILITY = "feasibility"
    CLARITY = "clarity"
    EFFECTIVENESS = "effectiveness"


class ExperimentMetric(str, Enum):
    """実験計画の評価指標（3つ）"""

    FEASIBILITY = "feasibility"
    QUALITY = "quality"
    CLARITY = "clarity"


class Winner(int, Enum):
    """ペアワイズ比較の勝者（CoI論文仕様: 0=A優位, 1=B優位, 2=同等）"""

    IDEA_A = 0
    IDEA_B = 1
    TIE = 2

    def to_score_for_a(self) -> float:
        """ELOスコア計算用にAの得点に変換

        Returns:
            Aの得点（1.0=勝ち, 0.5=引き分け, 0.0=負け）
        """
        if self == Winner.IDEA_A:
            return 1.0
        elif self == Winner.IDEA_B:
            return 0.0
        else:
            return 0.5


class MetricScore(BaseModel):
    """指標ごとの評価スコア"""

    metric: EvaluationMetric = Field(description="評価指標")
    winner: Winner = Field(description="勝者")
    reasoning: str = Field(description="評価理由")


class ExperimentMetricScore(BaseModel):
    """実験計画の指標ごとの評価スコア"""

    metric: ExperimentMetric = Field(description="実験計画評価指標")
    winner: Winner = Field(description="勝者")
    reasoning: str = Field(description="評価理由")


class PairwiseResult(BaseModel):
    """ペアワイズ比較結果"""

    idea_a_id: str = Field(description="アイデアAのID")
    idea_b_id: str = Field(description="アイデアBのID")
    scores: list[MetricScore] = Field(description="各指標の評価スコア")
    experiment_scores: list[ExperimentMetricScore] | None = Field(
        default=None, description="実験計画の評価スコア（オプション）"
    )


class EloRatings(BaseModel):
    """ELOレーティング"""

    ratings_by_metric: dict[EvaluationMetric, dict[str, float]] = Field(
        description="指標ごとのレーティング（idea_id -> score）"
    )
    overall_ratings: dict[str, float] = Field(
        description="総合レーティング（idea_id -> score）"
    )


class RankingEntry(BaseModel):
    """ランキングエントリ"""

    rank: int = Field(description="順位")
    idea_id: str = Field(description="アイデアID")
    idea_title: str | None = Field(default=None, description="アイデアのタイトル")
    overall_score: float = Field(description="総合スコア")
    scores_by_metric: dict[EvaluationMetric, float] = Field(
        description="指標ごとのスコア"
    )
    is_target_paper: bool = Field(
        default=False, description="ターゲット論文のアイデアかどうか"
    )
    source: IdeaSource = Field(
        default=IdeaSource.IDEAGRAPH,
        description="アイデアのソース（ideagraph, coi, target_paper）"
    )


class TargetPaperExtraction(BaseModel):
    """ターゲット論文から抽出されたアイデア情報"""

    paper_id: str | None = Field(default=None, description="ターゲット論文のID")
    paper_title: str | None = Field(default=None, description="ターゲット論文のタイトル")
    extracted_title: str = Field(description="抽出されたアイデアのタイトル")
    motivation: str = Field(description="動機・問題設定")
    method: str = Field(description="提案手法")
    key_differences: list[str] = Field(description="既存研究との主要な差異")
    # 実験計画フィールド（後方互換性のためデフォルト値を設定）
    datasets: list[str] = Field(default_factory=list, description="使用データセット")
    baselines: list[str] = Field(default_factory=list, description="比較ベースライン")
    metrics: list[str] = Field(default_factory=list, description="評価指標")
    ablations: list[str] = Field(default_factory=list, description="アブレーション実験")
    main_results: str = Field(default="", description="主要な実験結果")
    extracted_at: datetime = Field(description="抽出日時")
    extraction_model: str = Field(description="抽出に使用したLLMモデル名")


class EvaluationResult(BaseModel):
    """評価結果（評価セッション全体）"""

    evaluated_at: datetime = Field(description="評価実行日時")
    model_name: str = Field(description="使用したLLMモデル名")
    proposals: list = Field(description="評価対象のProposalリスト")
    pairwise_results: list[PairwiseResult] = Field(description="ペアワイズ比較結果")
    elo_ratings: EloRatings = Field(description="ELOレーティング")
    ranking: list[RankingEntry] = Field(description="ランキング表")
    target_paper_extraction: TargetPaperExtraction | None = Field(
        default=None,
        description="ターゲット論文から抽出されたアイデア情報",
    )
