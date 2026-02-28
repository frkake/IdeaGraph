"""評価サービス"""

import asyncio
import json
import logging
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from idea_graph.config import settings
from idea_graph.constants import OUTPUT_CONSTRAINTS
from idea_graph.models.evaluation import (
    AbsoluteMetricScore,
    EvaluationMetric,
    EvaluationProgressEvent,
    EvaluationResult,
    ExperimentMetric,
    ExperimentMetricScore,
    EloRatings,
    IdeaSource,
    MetricScore,
    PairwiseResult,
    RankingEntry,
    SingleEvaluationResult,
    SingleIdeaResult,
    SwapTestRawData,
    TargetPaperExtraction,
    Winner,
)

# 定数のエイリアス（可読性向上）
_C = OUTPUT_CONSTRAINTS

if TYPE_CHECKING:
    from idea_graph.services.proposal import Proposal

logger = logging.getLogger(__name__)


def _create_chat_model(model_name: str, temperature: float = 0.0) -> BaseChatModel:
    """モデル名に基づいて適切なLLMインスタンスを生成する。"""
    if "gemini" in model_name.lower():
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.google_api_key,
            temperature=temperature,
        )
    elif "claude" in model_name.lower():
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
        )
    else:
        return ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key,
            temperature=temperature,
        )


class EloRatingCalculator:
    """ELOレーティング計算機"""

    def __init__(
        self,
        initial_rating: float = 1000.0,
        k_factor: float = 32.0,
    ) -> None:
        """初期化

        Args:
            initial_rating: 初期レーティング値
            k_factor: K-factor（変動率）
        """
        self.initial_rating = initial_rating
        self.k_factor = k_factor

    def _update_rating(
        self,
        rating_a: float,
        rating_b: float,
        score: float,
    ) -> tuple[float, float]:
        """ELOレーティングを更新

        Args:
            rating_a: Aの現在レーティング
            rating_b: Bの現在レーティング
            score: 勝敗スコア（1=A勝ち, 0.5=引き分け, 0=A負け）

        Returns:
            更新後の(A, B)レーティング
        """
        # 期待勝率を計算
        expected_a = 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))
        expected_b = 1.0 - expected_a

        # レーティングを更新
        new_a = rating_a + self.k_factor * (score - expected_a)
        new_b = rating_b + self.k_factor * ((1.0 - score) - expected_b)

        return new_a, new_b

    def calculate(
        self,
        pairwise_results: list[PairwiseResult],
        idea_ids: list[str],
    ) -> EloRatings:
        """ペアワイズ比較結果からELOレーティングを算出

        Args:
            pairwise_results: 全ペアの比較結果
            idea_ids: アイデアIDリスト

        Returns:
            ELOレーティング（各指標および総合）
        """
        # 各指標ごとのレーティングを初期化
        ratings_by_metric: dict[EvaluationMetric, dict[str, float]] = {}
        for metric in EvaluationMetric:
            ratings_by_metric[metric] = {
                idea_id: self.initial_rating for idea_id in idea_ids
            }

        # 各ペアワイズ比較結果を処理
        for result in pairwise_results:
            for score in result.scores:
                metric = score.metric
                winner = score.winner

                # 現在のレーティングを取得
                rating_a = ratings_by_metric[metric][result.idea_a_id]
                rating_b = ratings_by_metric[metric][result.idea_b_id]

                # 勝敗スコアに変換
                elo_score = winner.to_score_for_a()

                # レーティングを更新
                new_a, new_b = self._update_rating(rating_a, rating_b, elo_score)
                ratings_by_metric[metric][result.idea_a_id] = new_a
                ratings_by_metric[metric][result.idea_b_id] = new_b

        # 総合レーティングを計算（各指標の平均）
        overall_ratings: dict[str, float] = {}
        for idea_id in idea_ids:
            total = sum(
                ratings_by_metric[metric][idea_id] for metric in EvaluationMetric
            )
            overall_ratings[idea_id] = total / len(EvaluationMetric)

        return EloRatings(
            ratings_by_metric=ratings_by_metric,
            overall_ratings=overall_ratings,
        )

    def generate_ranking(self, ratings: EloRatings) -> list[RankingEntry]:
        """ELOレーティングからランキング表を生成

        Args:
            ratings: ELOレーティング

        Returns:
            ランキングエントリのリスト（順位順）
        """
        # 総合スコアでソート
        sorted_ids = sorted(
            ratings.overall_ratings.keys(),
            key=lambda x: ratings.overall_ratings[x],
            reverse=True,
        )

        ranking = []
        for rank, idea_id in enumerate(sorted_ids, 1):
            scores_by_metric = {
                metric: ratings.ratings_by_metric[metric][idea_id]
                for metric in EvaluationMetric
                if metric in ratings.ratings_by_metric
            }
            entry = RankingEntry(
                rank=rank,
                idea_id=idea_id,
                overall_score=ratings.overall_ratings[idea_id],
                scores_by_metric=scores_by_metric,
            )
            ranking.append(entry)

        return ranking


class RawComparisonResult(BaseModel):
    """LLMからの生の比較結果（swap test用）"""

    scores: dict[EvaluationMetric, tuple[int, str]] = Field(
        description="各指標の評価結果（スコア, 理由）。スコア: 0=A優位, 1=B優位, 2=同等"
    )


# LLM用の構造化出力モデル
class LLMComparisonOutput(BaseModel):
    """LLMからの構造化出力用モデル"""

    novelty_score: int = Field(description="Novelty score: 0=A wins, 1=B wins, 2=tie")
    novelty_reasoning: str = Field(description="Reasoning for novelty comparison")
    significance_score: int = Field(description="Significance score: 0=A wins, 1=B wins, 2=tie")
    significance_reasoning: str = Field(description="Reasoning for significance comparison")
    feasibility_score: int = Field(description="Feasibility score: 0=A wins, 1=B wins, 2=tie")
    feasibility_reasoning: str = Field(description="Reasoning for feasibility comparison")
    clarity_score: int = Field(description="Clarity score: 0=A wins, 1=B wins, 2=tie")
    clarity_reasoning: str = Field(description="Reasoning for clarity comparison")
    effectiveness_score: int = Field(description="Effectiveness score: 0=A wins, 1=B wins, 2=tie")
    effectiveness_reasoning: str = Field(description="Reasoning for effectiveness comparison")

    def to_raw_comparison_result(self) -> "RawComparisonResult":
        """RawComparisonResultに変換"""
        return RawComparisonResult(
            scores={
                EvaluationMetric.NOVELTY: (self.novelty_score, self.novelty_reasoning),
                EvaluationMetric.SIGNIFICANCE: (self.significance_score, self.significance_reasoning),
                EvaluationMetric.FEASIBILITY: (self.feasibility_score, self.feasibility_reasoning),
                EvaluationMetric.CLARITY: (self.clarity_score, self.clarity_reasoning),
                EvaluationMetric.EFFECTIVENESS: (self.effectiveness_score, self.effectiveness_reasoning),
            }
        )


class LLMSingleEvaluationOutput(BaseModel):
    """LLMからの単一アイデア単体評価の構造化出力"""

    novelty_score: int = Field(description="Novelty score: 1 (lowest) to 10 (highest)")
    novelty_reasoning: str = Field(description="Reasoning for novelty evaluation")
    significance_score: int = Field(description="Significance score: 1 (lowest) to 10 (highest)")
    significance_reasoning: str = Field(description="Reasoning for significance evaluation")
    feasibility_score: int = Field(description="Feasibility score: 1 (lowest) to 10 (highest)")
    feasibility_reasoning: str = Field(description="Reasoning for feasibility evaluation")
    clarity_score: int = Field(description="Clarity score: 1 (lowest) to 10 (highest)")
    clarity_reasoning: str = Field(description="Reasoning for clarity evaluation")
    effectiveness_score: int = Field(description="Effectiveness score: 1 (lowest) to 10 (highest)")
    effectiveness_reasoning: str = Field(description="Reasoning for effectiveness evaluation")

    def to_absolute_metric_scores(self) -> list[AbsoluteMetricScore]:
        """AbsoluteMetricScoreリストに変換"""
        return [
            AbsoluteMetricScore(metric=EvaluationMetric.NOVELTY, score=self.novelty_score, reasoning=self.novelty_reasoning),
            AbsoluteMetricScore(metric=EvaluationMetric.SIGNIFICANCE, score=self.significance_score, reasoning=self.significance_reasoning),
            AbsoluteMetricScore(metric=EvaluationMetric.FEASIBILITY, score=self.feasibility_score, reasoning=self.feasibility_reasoning),
            AbsoluteMetricScore(metric=EvaluationMetric.CLARITY, score=self.clarity_score, reasoning=self.clarity_reasoning),
            AbsoluteMetricScore(metric=EvaluationMetric.EFFECTIVENESS, score=self.effectiveness_score, reasoning=self.effectiveness_reasoning),
        ]


class SingleIdeaEvaluator:
    """単一アイデアの単体評価サービス"""

    EVALUATION_PROMPT_TEMPLATE = """You are an expert research proposal evaluator. Evaluate the following research idea on an absolute scale from 1 to 10 for each metric.

## Evaluation Metrics

1. **Novelty** (1-10): Is the problem or approach new? Is it a new combination of known techniques? Is the difference from prior work clear?
   - 1-3: Incremental or derivative work with minimal new elements
   - 4-6: Moderate novelty, some new elements or combinations
   - 7-10: Highly novel approach or problem formulation

2. **Significance** (1-10): Is the idea important? Will other researchers use or build upon it? Does it address a meaningful problem?
   - 1-3: Marginal impact, limited applicability
   - 4-6: Moderate impact potential
   - 7-10: High potential for widespread impact

3. **Feasibility** (1-10): Can it be implemented with existing technology? Are there no major technical barriers?
   - 1-3: Major technical challenges, unclear implementation path
   - 4-6: Feasible with some effort and problem-solving
   - 7-10: Clearly implementable with well-defined approach

4. **Clarity** (1-10): Is the description clear and well-organized? Does it inform the reader appropriately?
   - 1-3: Poorly organized, hard to understand
   - 4-6: Adequately clear with some ambiguities
   - 7-10: Exceptionally clear and well-structured

5. **Effectiveness** (1-10): Is the proposed idea likely to work? Is it likely better than existing methods?
   - 1-3: Unlikely to outperform existing methods
   - 4-6: Moderate chance of improvement
   - 7-10: Strong evidence of potential effectiveness

## Research Idea: {idea_title}

**Motivation**: {idea_motivation}

**Method**: {idea_method}

**Key Differences from Existing Work**: {idea_differences}

## Instructions
For each metric, provide:
- A score from 1 to 10
- A brief reasoning (1-2 sentences) explaining your score

Be rigorous and calibrated. A score of 5 means average quality for a research proposal."""

    def __init__(self, model_name: str | None = None) -> None:
        """初期化"""
        self.model_name = model_name or settings.evaluation_model
        self._llm = None

    @property
    def llm(self) -> BaseChatModel:
        """LLMインスタンスを取得"""
        if self._llm is None:
            self._llm = _create_chat_model(self.model_name)
        return self._llm

    def _build_prompt(self, idea: "Proposal") -> str:
        """評価プロンプトを構築"""
        return self.EVALUATION_PROMPT_TEMPLATE.format(
            idea_title=idea.title,
            idea_motivation=idea.motivation,
            idea_method=idea.method,
            idea_differences=", ".join(idea.differences),
        )

    def evaluate(self, idea: "Proposal") -> list[AbsoluteMetricScore]:
        """単一アイデアを単体評価（同期版）"""
        prompt = self._build_prompt(idea)
        structured_llm = self.llm.with_structured_output(LLMSingleEvaluationOutput)
        message = HumanMessage(content=prompt)
        result: LLMSingleEvaluationOutput = structured_llm.invoke([message])
        return result.to_absolute_metric_scores()

    async def evaluate_async(self, idea: "Proposal") -> list[AbsoluteMetricScore]:
        """単一アイデアを単体評価（非同期版）"""
        prompt = self._build_prompt(idea)
        structured_llm = self.llm.with_structured_output(LLMSingleEvaluationOutput)
        message = HumanMessage(content=prompt)
        result: LLMSingleEvaluationOutput = await structured_llm.ainvoke([message])
        return result.to_absolute_metric_scores()


class PairwiseComparator:
    """ペアワイズ比較サービス"""

    EVALUATION_PROMPT_TEMPLATE = """You are an expert research proposal evaluator. Compare two research ideas and determine which is better for each evaluation metric.

## Evaluation Metrics

1. **Novelty**: Is the problem or approach new? Is it a new combination of known techniques? Is the difference from prior work clear?
2. **Significance**: Is the idea important? Will other researchers use or build upon it? Does it solve a difficult problem better?
3. **Feasibility**: Can it be implemented with existing technology? Are there no major technical difficulties? Is the logic clear and implementable?
4. **Clarity**: Is the description clear and well-organized? Does it appropriately inform the reader?
5. **Effectiveness**: Is the proposed idea likely to work? Is it better than existing methods?

## IMPORTANT: Position Bias Warning
Do NOT let the order of presentation influence your judgment. Evaluate each idea on its own merits regardless of whether it is presented first or second.

## Idea A: {idea_a_title}

**Motivation**: {idea_a_motivation}

**Method**: {idea_a_method}

**Key Differences from Existing Work**: {idea_a_differences}

## Idea B: {idea_b_title}

**Motivation**: {idea_b_motivation}

**Method**: {idea_b_method}

**Key Differences from Existing Work**: {idea_b_differences}

## Instructions
For each metric, provide:
- A score: 0 if Idea A is better, 1 if Idea B is better, 2 if they are equal
- A brief reasoning (1-2 sentences) explaining your decision

Focus on substantive differences, not superficial ones."""

    def __init__(self, model_name: str | None = None) -> None:
        """初期化

        Args:
            model_name: 使用するLLMモデル名
        """
        self.model_name = model_name or settings.evaluation_model
        self._llm = None

    @property
    def llm(self) -> BaseChatModel:
        """LLMインスタンスを取得"""
        if self._llm is None:
            self._llm = _create_chat_model(self.model_name)
        return self._llm

    def _build_evaluation_prompt(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
    ) -> str:
        """評価プロンプトを構築

        Args:
            idea_a: 1つ目のアイデア
            idea_b: 2つ目のアイデア

        Returns:
            評価プロンプト
        """
        return self.EVALUATION_PROMPT_TEMPLATE.format(
            idea_a_title=idea_a.title,
            idea_a_motivation=idea_a.motivation,
            idea_a_method=idea_a.method,
            idea_a_differences=", ".join(idea_a.differences),
            idea_b_title=idea_b.title,
            idea_b_motivation=idea_b.motivation,
            idea_b_method=idea_b.method,
            idea_b_differences=", ".join(idea_b.differences),
        )

    def _evaluate_pair(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
    ) -> RawComparisonResult:
        """単一順序での評価実行

        Args:
            idea_a: 1つ目のアイデア
            idea_b: 2つ目のアイデア

        Returns:
            生の比較結果
        """
        prompt = self._build_evaluation_prompt(idea_a, idea_b)
        structured_llm = self.llm.with_structured_output(LLMComparisonOutput)
        message = HumanMessage(content=prompt)
        result: LLMComparisonOutput = structured_llm.invoke([message])
        return result.to_raw_comparison_result()

    def _resolve_swap_test(
        self,
        result_ab: RawComparisonResult,
        result_ba: RawComparisonResult,
        idea_a_id: str,
        idea_b_id: str,
    ) -> PairwiseResult:
        """swap test結果を統合、不一致時はtie

        Args:
            result_ab: A→Bの順序での評価結果
            result_ba: B→Aの順序での評価結果
            idea_a_id: アイデアAのID
            idea_b_id: アイデアBのID

        Returns:
            統合されたペアワイズ比較結果
        """
        scores = []
        ab_raw: dict[str, int] = {}
        ba_raw: dict[str, int] = {}

        for metric in EvaluationMetric:
            score_ab, reasoning_ab = result_ab.scores[metric]
            score_ba, reasoning_ba = result_ba.scores[metric]

            # 生スコアを保存
            ab_raw[metric.value] = score_ab
            ba_raw[metric.value] = score_ba

            # swap testの解決
            # score_ab: 0=A wins, 1=B wins, 2=tie
            # score_ba: 0=B wins (in swapped order), 1=A wins (in swapped order), 2=tie
            # つまり、score_baを元の順序に変換: 0→1, 1→0, 2→2
            if score_ba == 0:
                score_ba_normalized = 1  # Bが勝ち = Aが負け
            elif score_ba == 1:
                score_ba_normalized = 0  # Aが勝ち
            else:
                score_ba_normalized = 2  # tie

            # 一貫性チェック
            if score_ab == score_ba_normalized:
                # 一貫している場合
                if score_ab == 0:
                    winner = Winner.IDEA_A
                elif score_ab == 1:
                    winner = Winner.IDEA_B
                else:
                    winner = Winner.TIE
                reasoning = reasoning_ab
            else:
                # 不一致の場合はTIE
                winner = Winner.TIE
                reasoning = f"Inconsistent results (AB: {reasoning_ab}, BA: {reasoning_ba})"

            scores.append(
                MetricScore(
                    metric=metric,
                    winner=winner,
                    reasoning=reasoning,
                )
            )

        return PairwiseResult(
            idea_a_id=idea_a_id,
            idea_b_id=idea_b_id,
            scores=scores,
            swap_test_raw=SwapTestRawData(ab_scores=ab_raw, ba_scores=ba_raw),
        )

    def compare(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
        idea_a_id: str,
        idea_b_id: str,
    ) -> PairwiseResult:
        """2つのアイデアを5指標で比較（swap test付き）

        Args:
            idea_a: 1つ目のアイデア
            idea_b: 2つ目のアイデア
            idea_a_id: アイデアAのID
            idea_b_id: アイデアBのID

        Returns:
            比較結果（各指標の勝敗、理由）
        """
        logger.info(f"Comparing {idea_a_id} vs {idea_b_id}")

        # 順序A→Bで評価
        result_ab = self._evaluate_pair(idea_a, idea_b)

        # 順序B→Aで評価（swap test）
        result_ba = self._evaluate_pair(idea_b, idea_a)

        # swap test結果を統合
        return self._resolve_swap_test(result_ab, result_ba, idea_a_id, idea_b_id)

    async def _evaluate_pair_async(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
    ) -> RawComparisonResult:
        """単一順序での評価実行（非同期版）"""
        prompt = self._build_evaluation_prompt(idea_a, idea_b)
        structured_llm = self.llm.with_structured_output(LLMComparisonOutput)
        message = HumanMessage(content=prompt)
        result: LLMComparisonOutput = await structured_llm.ainvoke([message])
        return result.to_raw_comparison_result()

    async def compare_async(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
        idea_a_id: str,
        idea_b_id: str,
    ) -> PairwiseResult:
        """2つのアイデアを5指標で比較（非同期版、swap test並列実行）

        Args:
            idea_a: 1つ目のアイデア
            idea_b: 2つ目のアイデア
            idea_a_id: アイデアAのID
            idea_b_id: アイデアBのID

        Returns:
            比較結果（各指標の勝敗、理由）
        """
        logger.info(f"Comparing async {idea_a_id} vs {idea_b_id}")

        # swap testを並列実行
        result_ab, result_ba = await asyncio.gather(
            self._evaluate_pair_async(idea_a, idea_b),
            self._evaluate_pair_async(idea_b, idea_a),
        )

        # swap test結果を統合
        return self._resolve_swap_test(result_ab, result_ba, idea_a_id, idea_b_id)


class LLMExperimentComparisonOutput(BaseModel):
    """実験計画比較用のLLM構造化出力"""

    feasibility_score: int = Field(description="Feasibility score: 0=A wins, 1=B wins, 2=tie")
    feasibility_reasoning: str = Field(description="Reasoning for feasibility comparison")
    quality_score: int = Field(description="Quality score: 0=A wins, 1=B wins, 2=tie")
    quality_reasoning: str = Field(description="Reasoning for quality comparison")
    clarity_score: int = Field(description="Clarity score: 0=A wins, 1=B wins, 2=tie")
    clarity_reasoning: str = Field(description="Reasoning for clarity comparison")


class ExperimentComparator:
    """実験計画の比較サービス"""

    EXPERIMENT_PROMPT_TEMPLATE = """You are an expert research proposal evaluator. Compare the experiment plans of two research ideas and determine which is better for each metric.

## Evaluation Metrics

1. **Feasibility**: Can the experiment be technically executed? Are the required resources, datasets, and computational requirements realistic?
2. **Quality**: Is the experiment design logical and rigorous? Does it properly test the hypothesis? Are there appropriate controls and baselines?
3. **Clarity**: Is the experiment plan clearly described with sufficient detail? Can it be reproduced from the description?

## IMPORTANT: Position Bias Warning
Do NOT let the order of presentation influence your judgment. Evaluate each experiment plan on its own merits.

## Experiment Plan A: {idea_a_title}

**Datasets**: {idea_a_datasets}
**Baselines**: {idea_a_baselines}
**Metrics**: {idea_a_metrics}
**Ablation Studies**: {idea_a_ablations}
**Expected Results**: {idea_a_expected}

## Experiment Plan B: {idea_b_title}

**Datasets**: {idea_b_datasets}
**Baselines**: {idea_b_baselines}
**Metrics**: {idea_b_metrics}
**Ablation Studies**: {idea_b_ablations}
**Expected Results**: {idea_b_expected}

## Instructions
For each metric, provide:
- A score: 0 if Experiment A is better, 1 if Experiment B is better, 2 if they are equal
- A brief reasoning (1-2 sentences) explaining your decision"""

    def __init__(self, model_name: str | None = None) -> None:
        """初期化"""
        self.model_name = model_name or settings.evaluation_model
        self._llm = None

    @property
    def llm(self) -> BaseChatModel:
        """LLMインスタンスを取得"""
        if self._llm is None:
            self._llm = _create_chat_model(self.model_name)
        return self._llm

    def _build_experiment_prompt(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
    ) -> str:
        """実験計画比較プロンプトを構築"""
        return self.EXPERIMENT_PROMPT_TEMPLATE.format(
            idea_a_title=idea_a.title,
            idea_a_datasets=", ".join(idea_a.experiment.datasets),
            idea_a_baselines=", ".join(idea_a.experiment.baselines),
            idea_a_metrics=", ".join(idea_a.experiment.metrics),
            idea_a_ablations=", ".join(idea_a.experiment.ablations),
            idea_a_expected=idea_a.experiment.expected_results,
            idea_b_title=idea_b.title,
            idea_b_datasets=", ".join(idea_b.experiment.datasets),
            idea_b_baselines=", ".join(idea_b.experiment.baselines),
            idea_b_metrics=", ".join(idea_b.experiment.metrics),
            idea_b_ablations=", ".join(idea_b.experiment.ablations),
            idea_b_expected=idea_b.experiment.expected_results,
        )

    def compare(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
    ) -> list[ExperimentMetricScore]:
        """2つのアイデアの実験計画を3指標で比較

        Args:
            idea_a: 1つ目のアイデア
            idea_b: 2つ目のアイデア

        Returns:
            実験計画の評価スコアリスト
        """
        logger.info(f"Comparing experiment plans: {idea_a.title} vs {idea_b.title}")

        # 順序A→Bで評価
        prompt_ab = self._build_experiment_prompt(idea_a, idea_b)
        structured_llm = self.llm.with_structured_output(LLMExperimentComparisonOutput)
        result_ab: LLMExperimentComparisonOutput = structured_llm.invoke([HumanMessage(content=prompt_ab)])

        # 順序B→Aで評価（swap test）
        prompt_ba = self._build_experiment_prompt(idea_b, idea_a)
        result_ba: LLMExperimentComparisonOutput = structured_llm.invoke([HumanMessage(content=prompt_ba)])

        # swap test結果を統合
        scores = []
        for metric, (score_ab, reasoning_ab), (score_ba, reasoning_ba) in [
            (ExperimentMetric.FEASIBILITY,
             (result_ab.feasibility_score, result_ab.feasibility_reasoning),
             (result_ba.feasibility_score, result_ba.feasibility_reasoning)),
            (ExperimentMetric.QUALITY,
             (result_ab.quality_score, result_ab.quality_reasoning),
             (result_ba.quality_score, result_ba.quality_reasoning)),
            (ExperimentMetric.CLARITY,
             (result_ab.clarity_score, result_ab.clarity_reasoning),
             (result_ba.clarity_score, result_ba.clarity_reasoning)),
        ]:
            # score_baを正規化
            if score_ba == 0:
                score_ba_normalized = 1
            elif score_ba == 1:
                score_ba_normalized = 0
            else:
                score_ba_normalized = 2

            if score_ab == score_ba_normalized:
                if score_ab == 0:
                    winner = Winner.IDEA_A
                elif score_ab == 1:
                    winner = Winner.IDEA_B
                else:
                    winner = Winner.TIE
                reasoning = reasoning_ab
            else:
                winner = Winner.TIE
                reasoning = f"Inconsistent results"

            scores.append(
                ExperimentMetricScore(
                    metric=metric,
                    winner=winner,
                    reasoning=reasoning,
                )
            )

        return scores

    async def compare_async(
        self,
        idea_a: "Proposal",
        idea_b: "Proposal",
    ) -> list[ExperimentMetricScore]:
        """2つのアイデアの実験計画を3指標で比較（非同期版）"""
        logger.info(f"Comparing experiment plans async: {idea_a.title} vs {idea_b.title}")

        # 順序A→B、B→Aで並列評価
        prompt_ab = self._build_experiment_prompt(idea_a, idea_b)
        prompt_ba = self._build_experiment_prompt(idea_b, idea_a)
        structured_llm = self.llm.with_structured_output(LLMExperimentComparisonOutput)

        result_ab, result_ba = await asyncio.gather(
            structured_llm.ainvoke([HumanMessage(content=prompt_ab)]),
            structured_llm.ainvoke([HumanMessage(content=prompt_ba)]),
        )

        # swap test結果を統合
        scores = []
        for metric, (score_ab, reasoning_ab), (score_ba, reasoning_ba) in [
            (ExperimentMetric.FEASIBILITY,
             (result_ab.feasibility_score, result_ab.feasibility_reasoning),
             (result_ba.feasibility_score, result_ba.feasibility_reasoning)),
            (ExperimentMetric.QUALITY,
             (result_ab.quality_score, result_ab.quality_reasoning),
             (result_ba.quality_score, result_ba.quality_reasoning)),
            (ExperimentMetric.CLARITY,
             (result_ab.clarity_score, result_ab.clarity_reasoning),
             (result_ba.clarity_score, result_ba.clarity_reasoning)),
        ]:
            if score_ba == 0:
                score_ba_normalized = 1
            elif score_ba == 1:
                score_ba_normalized = 0
            else:
                score_ba_normalized = 2

            if score_ab == score_ba_normalized:
                if score_ab == 0:
                    winner = Winner.IDEA_A
                elif score_ab == 1:
                    winner = Winner.IDEA_B
                else:
                    winner = Winner.TIE
                reasoning = reasoning_ab
            else:
                winner = Winner.TIE
                reasoning = "Inconsistent results"

            scores.append(
                ExperimentMetricScore(
                    metric=metric,
                    winner=winner,
                    reasoning=reasoning,
                )
            )

        return scores


class LLMIdeaExtraction(BaseModel):
    """論文からのアイデア抽出用の構造化出力"""

    title: str = Field(description=f"The main idea/contribution of the paper in {_C.TITLE}")
    motivation: str = Field(
        description=f"The problem being addressed and why it matters ({_C.MOTIVATION_WORDS})"
    )
    method: str = Field(description=f"The proposed approach/solution ({_C.METHOD_WORDS})")
    differences: list[str] = Field(
        description=f"Key differences from prior work {_C.differences_constraint()}"
    )
    # 実験計画フィールド
    datasets: list[str] = Field(
        description=f"Datasets used in experiments {_C.datasets_constraint()} describing the dataset"
    )
    baselines: list[str] = Field(
        description=f"Baseline methods compared against {_C.baselines_constraint()} describing the method"
    )
    metrics: list[str] = Field(
        description=f"Evaluation metrics used {_C.metrics_constraint()} describing the metric"
    )
    ablations: list[str] = Field(
        description=f"Ablation studies conducted {_C.ablations_constraint()} describing what is tested"
    )
    expected_results: str = Field(
        description=f"Key experimental results and findings ({_C.MAIN_RESULTS_WORDS})"
    )
    rationale: str = Field(
        description=f"Why the authors propose this specific approach ({_C.RATIONALE_WORDS})"
    )
    research_trends: str = Field(
        description=f"Related research context and trends ({_C.RESEARCH_TRENDS_WORDS})"
    )
    failure_interpretation: str = Field(
        description=f"Acknowledged limitations and failure modes ({_C.FAILURE_INTERPRETATION_WORDS})"
    )


class IdeaExtractor:
    """論文からアイデアを抽出するサービス（比較評価用）"""

    def __init__(self, model_name: str | None = None) -> None:
        """初期化"""
        self.model_name = model_name or settings.evaluation_model
        self._llm = None

    @property
    def llm(self) -> BaseChatModel:
        """LLMインスタンスを取得"""
        if self._llm is None:
            self._llm = _create_chat_model(self.model_name)
        return self._llm

    def _build_extraction_prompt(self, content: str) -> str:
        """論文抽出用プロンプトを構築"""
        return f"""You are an expert AI research paper analyzer. Extract and elaborate the core research idea from the following paper.

For each field, provide comprehensive, detailed content that fully explains the research idea.

1. **title**: A concise description of the main contribution ({_C.TITLE})
2. **motivation**: The problem being addressed and its significance ({_C.MOTIVATION_WORDS})
   - What specific gap or limitation exists in current approaches?
   - Why is this problem important for the research community?
   - What are the real-world implications of solving this problem?
   - What prior attempts have been made and why were they insufficient?
3. **method**: The proposed approach or solution ({_C.METHOD_WORDS})
   - What is the core technical innovation?
   - How does the proposed method work step by step?
   - What are the key components or modules of the approach?
   - How do the components interact to achieve the desired outcome?
4. **differences**: How this work differs from prior approaches {_C.differences_constraint()}
5. **datasets**: List of datasets used in experiments {_C.datasets_constraint()} describing the dataset
6. **baselines**: Methods compared against in experiments {_C.baselines_constraint()} describing the method
7. **metrics**: Evaluation metrics used {_C.metrics_constraint()} describing the metric
8. **ablations**: Ablation studies conducted {_C.ablations_constraint()} describing what is tested
9. **expected_results**: Key experimental findings and improvements over baselines ({_C.MAIN_RESULTS_WORDS})
10. **rationale**: Why the authors propose this specific approach ({_C.RATIONALE_WORDS})
    - What theoretical or empirical motivation led to this direction?
    - What insight from related work inspired this approach?
    - Why was this approach chosen over other possible directions?
    - What evidence supports the viability of this direction?
11. **research_trends**: Related research context and trends ({_C.RESEARCH_TRENDS_WORDS})
    - What technologies or methods are evolving and in which direction?
    - What is the lineage of related techniques?
    - Where is the research heading based on recent developments?
    - How does this paper fit into the broader research landscape?
12. **failure_interpretation**: Limitations and failure modes ({_C.FAILURE_INTERPRETATION_WORDS})
    - Under what conditions might the proposed method underperform?
    - What assumptions could be violated in practice?

CRITICAL: Each field MUST meet its minimum word count. Do NOT produce short summaries or single-sentence answers. Provide thorough, detailed explanations for every field.

Paper content:
{content}

Extract the research idea:"""

    def extract_from_text(self, paper_content: str) -> LLMIdeaExtraction:
        """論文テキストからアイデアを抽出

        Args:
            paper_content: 論文の本文テキスト

        Returns:
            抽出されたアイデア情報
        """
        # テキストを適切な長さに制限
        max_chars = 50000
        if len(paper_content) > max_chars:
            paper_content = paper_content[:max_chars]

        prompt = self._build_extraction_prompt(paper_content)
        structured_llm = self.llm.with_structured_output(LLMIdeaExtraction)
        message = HumanMessage(content=prompt)

        return structured_llm.invoke([message])


def convert_extraction_to_proposal(
    extraction: LLMIdeaExtraction,
    paper_title: str | None = None,
) -> "Proposal":
    """LLMIdeaExtractionをProposal形式に変換

    Args:
        extraction: 抽出されたアイデア情報
        paper_title: 論文タイトル（オプション）

    Returns:
        Proposal形式に変換されたアイデア
    """
    from idea_graph.services.proposal import Proposal, Experiment, Grounding

    return Proposal(
        title=paper_title or extraction.title,
        rationale=extraction.rationale,
        research_trends=extraction.research_trends,
        motivation=extraction.motivation,
        method=extraction.method,
        experiment=Experiment(
            datasets=extraction.datasets,
            baselines=extraction.baselines,
            metrics=extraction.metrics,
            ablations=extraction.ablations,
            expected_results=extraction.expected_results,
            failure_interpretation=extraction.failure_interpretation,
        ),
        grounding=Grounding(
            papers=[],
            entities=[],
            path_mermaid="graph LR\n  A[Target Paper]",
        ),
        differences=extraction.differences,
    )


# ターゲット論文のアイデアを識別するための定数
TARGET_PAPER_IDEA_ID = "target_paper"


class EvaluationService:
    """評価サービス（オーケストレーション）"""

    def __init__(
        self,
        model_name: str | None = None,
        output_dir: Path | None = None,
    ) -> None:
        """初期化

        Args:
            model_name: 使用するLLMモデル名
            output_dir: 評価結果の出力ディレクトリ
        """
        self.model_name = model_name or settings.evaluation_model
        self.output_dir = output_dir or (settings.cache_dir / "evaluations")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # ターゲット論文抽出の保存ディレクトリ
        self.target_extractions_dir = settings.cache_dir / "proposals" / "target"
        self.target_extractions_dir.mkdir(parents=True, exist_ok=True)

        self._comparator = None
        self._experiment_comparator = None
        self._elo_calculator = None
        self._single_evaluator = None

    @property
    def comparator(self) -> PairwiseComparator:
        """ペアワイズ比較器を取得"""
        if self._comparator is None:
            self._comparator = PairwiseComparator(model_name=self.model_name)
        return self._comparator

    @property
    def experiment_comparator(self) -> ExperimentComparator:
        """実験計画比較器を取得"""
        if self._experiment_comparator is None:
            self._experiment_comparator = ExperimentComparator(model_name=self.model_name)
        return self._experiment_comparator

    @property
    def elo_calculator(self) -> EloRatingCalculator:
        """ELOレーティング計算機を取得"""
        if self._elo_calculator is None:
            self._elo_calculator = EloRatingCalculator()
        return self._elo_calculator

    @property
    def single_evaluator(self) -> SingleIdeaEvaluator:
        """単一アイデア評価器を取得"""
        if self._single_evaluator is None:
            self._single_evaluator = SingleIdeaEvaluator(model_name=self.model_name)
        return self._single_evaluator

    def _generate_idea_id(self, index: int, proposal: "Proposal") -> str:
        """アイデアIDを生成"""
        # タイトルから安全なID部分を生成
        safe_title = "".join(c if c.isalnum() else "_" for c in proposal.title[:30])
        return f"idea_{index}_{safe_title}"

    def evaluate(
        self,
        proposals: list["Proposal"],
        include_experiment: bool = True,
        target_paper_content: str | None = None,
        target_paper_title: str | None = None,
        target_paper_id: str | None = None,
        proposal_sources: list[str] | None = None,
        target_paper_extraction_model: str | None = None,
    ) -> EvaluationResult:
        """提案群を評価してランキングを生成

        Args:
            proposals: 評価対象のProposalリスト
            include_experiment: 実験計画評価を含めるかどうか
            target_paper_content: ターゲット論文の全文テキスト（オプション）
            target_paper_title: ターゲット論文のタイトル（オプション）
            target_paper_id: ターゲット論文のID（例：arxiv ID）（オプション）
            proposal_sources: 各提案のソース（ideagraph, coi）のリスト（オプション）
            target_paper_extraction_model: ターゲット論文からのアイデア抽出に使うLLM。
                未指定時は評価用の self.model_name を使用する。

        Returns:
            評価結果
        """
        # 提案リストをコピー（元のリストを変更しない）
        all_proposals = list(proposals)
        target_paper_idea_id: str | None = None
        target_paper_extraction: TargetPaperExtraction | None = None

        extraction_model = target_paper_extraction_model or self.model_name

        # ターゲット論文がある場合、アイデアを抽出して追加
        if target_paper_content:
            logger.info("Extracting idea from target paper for comparison")
            extractor = IdeaExtractor(model_name=extraction_model)
            extraction = extractor.extract_from_text(target_paper_content)

            # Proposal形式に変換
            target_proposal = convert_extraction_to_proposal(
                extraction, paper_title=target_paper_title
            )

            # 抽出データを保存用に変換（dataにProposalを格納）
            target_paper_extraction = TargetPaperExtraction(
                paper_id=target_paper_id or TARGET_PAPER_IDEA_ID,
                paper_title=target_paper_title,
                extracted_at=datetime.now(),
                extraction_model=extraction_model,
                data=target_proposal,
            )

            # 抽出結果をファイルに保存
            self.save_target_extraction(target_paper_extraction)

            all_proposals.append(target_proposal)
            target_paper_idea_id = TARGET_PAPER_IDEA_ID
            logger.info(f"Added target paper idea: {target_proposal.title}")

        logger.info(f"Starting evaluation of {len(all_proposals)} proposals")

        # アイデアIDを生成
        idea_ids = []
        for i, p in enumerate(all_proposals):
            # ターゲット論文の場合は特別なIDを使用
            if i == len(all_proposals) - 1 and target_paper_idea_id:
                idea_ids.append(target_paper_idea_id)
            else:
                idea_ids.append(self._generate_idea_id(i, p))

        proposal_map = dict(zip(idea_ids, all_proposals))

        # ラウンドロビン方式で全ペア比較
        pairwise_results: list[PairwiseResult] = []
        pairs = list(combinations(enumerate(zip(idea_ids, all_proposals)), 2))

        for (i, (id_a, proposal_a)), (j, (id_b, proposal_b)) in pairs:
            logger.info(f"Comparing pair {i+1} vs {j+1} ({len(pairwise_results)+1}/{len(pairs)})")

            # アイデア比較
            result = self.comparator.compare(proposal_a, proposal_b, id_a, id_b)

            # 実験計画比較（オプション）
            # ターゲット論文も実験計画情報を抽出しているため比較対象に含める
            if include_experiment:
                exp_scores = self.experiment_comparator.compare(proposal_a, proposal_b)
                result.experiment_scores = exp_scores

            pairwise_results.append(result)

        # ELOレーティングを計算
        elo_ratings = self.elo_calculator.calculate(pairwise_results, idea_ids)

        # ランキングを生成
        ranking = self.elo_calculator.generate_ranking(elo_ratings)

        # idea_idからインデックスへのマップを作成（proposal_sourcesの参照用）
        idea_id_to_index = {idea_id: i for i, idea_id in enumerate(idea_ids)}

        # タイトル、is_target_paperフラグ、sourceを設定
        for entry in ranking:
            if entry.idea_id in proposal_map:
                entry.idea_title = proposal_map[entry.idea_id].title
            # ターゲット論文の場合はフラグとソースを設定
            if entry.idea_id == TARGET_PAPER_IDEA_ID:
                entry.is_target_paper = True
                entry.source = IdeaSource.TARGET_PAPER
            # proposal_sourcesが提供されている場合、対応するソースを設定
            elif proposal_sources and entry.idea_id in idea_id_to_index:
                idx = idea_id_to_index[entry.idea_id]
                if idx < len(proposal_sources):
                    source_str = proposal_sources[idx]
                    try:
                        entry.source = IdeaSource(source_str)
                    except ValueError:
                        entry.source = IdeaSource.IDEAGRAPH

        # 評価結果を作成
        eval_result = EvaluationResult(
            evaluated_at=datetime.now(),
            model_name=self.model_name,
            proposals=all_proposals,
            pairwise_results=pairwise_results,
            elo_ratings=elo_ratings,
            ranking=ranking,
            target_paper_extraction=target_paper_extraction,
        )

        logger.info(f"Evaluation completed. Top ranked: {ranking[0].idea_title if ranking else 'N/A'}")

        return eval_result

    async def evaluate_streaming(
        self,
        proposals: list["Proposal"],
        include_experiment: bool = True,
        target_paper_content: str | None = None,
        target_paper_title: str | None = None,
        target_paper_id: str | None = None,
        proposal_sources: list[str] | None = None,
        batch_size: int = 2,
        target_paper_extraction_model: str | None = None,
    ) -> AsyncIterator[EvaluationProgressEvent | EvaluationResult]:
        """提案群を評価してランキングを生成（ストリーミング版、バッチ並列実行）

        Args:
            proposals: 評価対象のProposalリスト
            include_experiment: 実験計画評価を含めるかどうか
            target_paper_content: ターゲット論文の全文テキスト（オプション）
            target_paper_title: ターゲット論文のタイトル（オプション）
            target_paper_id: ターゲット論文のID（オプション）
            proposal_sources: 各提案のソース（ideagraph, coi）のリスト（オプション）
            batch_size: 並列実行するバッチサイズ
            target_paper_extraction_model: ターゲット論文からのアイデア抽出に使うLLM。
                未指定時は評価用の self.model_name を使用する。

        Yields:
            EvaluationProgressEvent: 進捗イベント
            EvaluationResult: 最終結果（最後に1回）
        """
        all_proposals = list(proposals)
        target_paper_idea_id: str | None = None
        target_paper_extraction: TargetPaperExtraction | None = None

        extraction_model = target_paper_extraction_model or self.model_name

        # ターゲット論文がある場合、アイデアを抽出して追加
        if target_paper_content:
            yield EvaluationProgressEvent(
                event_type="extracting_target",
                phase="extracting_target",
                message="ターゲット論文からアイデアを抽出中...",
            )

            logger.info("Extracting idea from target paper for comparison")
            extractor = IdeaExtractor(model_name=extraction_model)
            extraction = extractor.extract_from_text(target_paper_content)

            # Proposal形式に変換
            target_proposal = convert_extraction_to_proposal(
                extraction, paper_title=target_paper_title
            )

            # 抽出データを保存用に変換（dataにProposalを格納）
            target_paper_extraction = TargetPaperExtraction(
                paper_id=target_paper_id or TARGET_PAPER_IDEA_ID,
                paper_title=target_paper_title,
                extracted_at=datetime.now(),
                extraction_model=extraction_model,
                data=target_proposal,
            )

            self.save_target_extraction(target_paper_extraction)

            all_proposals.append(target_proposal)
            target_paper_idea_id = TARGET_PAPER_IDEA_ID
            logger.info(f"Added target paper idea: {target_proposal.title}")

        logger.info(f"Starting evaluation of {len(all_proposals)} proposals")

        # アイデアIDを生成
        idea_ids = []
        for i, p in enumerate(all_proposals):
            if i == len(all_proposals) - 1 and target_paper_idea_id:
                idea_ids.append(target_paper_idea_id)
            else:
                idea_ids.append(self._generate_idea_id(i, p))

        proposal_map = dict(zip(idea_ids, all_proposals))

        # 全ペアを生成
        pairs = list(combinations(enumerate(zip(idea_ids, all_proposals)), 2))
        total_comparisons = len(pairs)

        yield EvaluationProgressEvent(
            event_type="progress",
            current_comparison=0,
            total_comparisons=total_comparisons,
            phase="comparing",
            message=f"0/{total_comparisons}件の比較を開始",
        )

        # バッチごとに並列実行
        pairwise_results: list[PairwiseResult] = []

        for batch_start in range(0, len(pairs), batch_size):
            batch = pairs[batch_start:batch_start + batch_size]

            # バッチ内を並列実行
            async def process_pair(pair_data):
                (i, (id_a, proposal_a)), (j, (id_b, proposal_b)) = pair_data
                result = await self.comparator.compare_async(proposal_a, proposal_b, id_a, id_b)
                if include_experiment:
                    exp_scores = await self.experiment_comparator.compare_async(proposal_a, proposal_b)
                    result.experiment_scores = exp_scores
                return result

            batch_results = await asyncio.gather(*[process_pair(pair) for pair in batch])
            pairwise_results.extend(batch_results)

            # 進捗を通知
            current = len(pairwise_results)
            yield EvaluationProgressEvent(
                event_type="progress",
                current_comparison=current,
                total_comparisons=total_comparisons,
                phase="comparing",
                message=f"{current}/{total_comparisons}件の比較完了",
            )

        # ELOレーティング計算フェーズ
        yield EvaluationProgressEvent(
            event_type="progress",
            current_comparison=total_comparisons,
            total_comparisons=total_comparisons,
            phase="calculating_elo",
            message="ELOレーティングを計算中...",
        )

        elo_ratings = self.elo_calculator.calculate(pairwise_results, idea_ids)
        ranking = self.elo_calculator.generate_ranking(elo_ratings)

        idea_id_to_index = {idea_id: i for i, idea_id in enumerate(idea_ids)}

        for entry in ranking:
            if entry.idea_id in proposal_map:
                entry.idea_title = proposal_map[entry.idea_id].title
            if entry.idea_id == TARGET_PAPER_IDEA_ID:
                entry.is_target_paper = True
                entry.source = IdeaSource.TARGET_PAPER
            elif proposal_sources and entry.idea_id in idea_id_to_index:
                idx = idea_id_to_index[entry.idea_id]
                if idx < len(proposal_sources):
                    source_str = proposal_sources[idx]
                    try:
                        entry.source = IdeaSource(source_str)
                    except ValueError:
                        entry.source = IdeaSource.IDEAGRAPH

        eval_result = EvaluationResult(
            evaluated_at=datetime.now(),
            model_name=self.model_name,
            proposals=all_proposals,
            pairwise_results=pairwise_results,
            elo_ratings=elo_ratings,
            ranking=ranking,
            target_paper_extraction=target_paper_extraction,
        )

        logger.info(f"Evaluation completed. Top ranked: {ranking[0].idea_title if ranking else 'N/A'}")

        yield eval_result

    def save_result(self, result: EvaluationResult, filename: str | None = None) -> Path:
        """評価結果をJSONファイルに保存

        Args:
            result: 評価結果
            filename: ファイル名（省略時は日時から生成）

        Returns:
            保存先のパス
        """
        if filename is None:
            timestamp = result.evaluated_at.strftime("%Y%m%d_%H%M%S")
            filename = f"evaluation_{timestamp}.json"

        output_path = self.output_dir / filename
        output_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )

        logger.info(f"Saved evaluation result to {output_path}")
        return output_path

    def load_result(self, path: Path) -> EvaluationResult:
        """評価結果をJSONファイルから読み込み

        Args:
            path: ファイルパス

        Returns:
            評価結果
        """
        return EvaluationResult.model_validate_json(path.read_text(encoding="utf-8"))

    def save_target_extraction(
        self,
        extraction: TargetPaperExtraction,
        filename: str | None = None,
    ) -> Path:
        """ターゲット論文の抽出結果をJSONファイルに保存

        Args:
            extraction: ターゲット論文の抽出結果
            filename: ファイル名（省略時は日時から生成）

        Returns:
            保存先のパス
        """
        safe_paper_id = None
        if extraction.paper_id:
            safe_paper_id = extraction.paper_id.replace("/", "_").replace(":", "_")

        if filename is None:
            timestamp = extraction.extracted_at.strftime("%Y%m%d_%H%M%S")
            filename = f"target_extraction_{timestamp}.json"

        paper_dir = self.target_extractions_dir
        if safe_paper_id:
            paper_dir = self.target_extractions_dir / safe_paper_id
            paper_dir.mkdir(parents=True, exist_ok=True)

        output_path = paper_dir / filename
        output_path.write_text(
            extraction.model_dump_json(indent=2),
            encoding="utf-8",
        )

        logger.info(f"Saved target paper extraction to {output_path}")
        return output_path

    def generate_markdown_report(self, result: EvaluationResult) -> str:
        """評価結果をMarkdownレポートとして生成

        Args:
            result: 評価結果

        Returns:
            Markdownテキスト
        """
        lines = [
            "# Idea Evaluation Report",
            "",
            f"**Evaluated at**: {result.evaluated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Model**: {result.model_name}",
            f"**Number of proposals**: {len(result.proposals)}",
            "",
            "## Rankings",
            "",
            "| Rank | Title | Overall Score |",
            "|------|-------|---------------|",
        ]

        for entry in result.ranking:
            title = entry.idea_title or entry.idea_id
            lines.append(f"| {entry.rank} | {title} | {entry.overall_score:.1f} |")

        lines.extend([
            "",
            "## Detailed Scores by Metric",
            "",
        ])

        for entry in result.ranking:
            title = entry.idea_title or entry.idea_id
            lines.append(f"### {entry.rank}. {title}")
            lines.append("")
            lines.append("| Metric | Score |")
            lines.append("|--------|-------|")
            for metric, score in entry.scores_by_metric.items():
                lines.append(f"| {metric.value.capitalize()} | {score:.1f} |")
            lines.append("")

        lines.extend([
            "## Pairwise Comparison Summary",
            "",
            f"Total comparisons: {len(result.pairwise_results)}",
            "",
        ])

        # ターゲット論文の抽出情報セクション
        if result.target_paper_extraction:
            ext = result.target_paper_extraction
            lines.extend([
                "## Target Paper Extraction",
                "",
                f"**Paper ID**: {ext.paper_id or 'N/A'}",
                f"**Paper Title**: {ext.paper_title or 'N/A'}",
                f"**Extracted at**: {ext.extracted_at.strftime('%Y-%m-%d %H:%M:%S')}",
                f"**Extraction Model**: {ext.extraction_model}",
                "",
                "### Extracted Idea",
                "",
                f"**Title**: {ext.data.title}",
                "",
                "**Motivation**:",
                "",
                ext.data.motivation,
                "",
                "**Method**:",
                "",
                ext.data.method,
                "",
            ])
            if ext.data.rationale:
                lines.extend([
                    "**Rationale**:",
                    "",
                    ext.data.rationale,
                    "",
                ])
            if ext.data.research_trends:
                lines.extend([
                    "**Research Trends**:",
                    "",
                    ext.data.research_trends,
                    "",
                ])
            lines.extend([
                "**Key Differences from Prior Work**:",
                "",
            ])
            for diff in ext.data.differences:
                lines.append(f"- {diff}")
            lines.append("")

            # 実験計画情報セクション
            lines.extend([
                "### Experiment Plan",
                "",
            ])
            if ext.data.experiment.datasets:
                lines.append(f"**Datasets**: {', '.join(ext.data.experiment.datasets)}")
            else:
                lines.append("**Datasets**: N/A")
            lines.append("")

            if ext.data.experiment.baselines:
                lines.append(f"**Baselines**: {', '.join(ext.data.experiment.baselines)}")
            else:
                lines.append("**Baselines**: N/A")
            lines.append("")

            if ext.data.experiment.metrics:
                lines.append(f"**Metrics**: {', '.join(ext.data.experiment.metrics)}")
            else:
                lines.append("**Metrics**: N/A")
            lines.append("")

            if ext.data.experiment.ablations:
                lines.append("**Ablation Studies**:")
                lines.append("")
                for abl in ext.data.experiment.ablations:
                    lines.append(f"- {abl}")
            else:
                lines.append("**Ablation Studies**: N/A")
            lines.append("")

            if ext.data.experiment.expected_results:
                lines.append("**Expected Results**:")
                lines.append("")
                lines.append(ext.data.experiment.expected_results)
            else:
                lines.append("**Expected Results**: N/A")
            lines.append("")

            if ext.data.experiment.failure_interpretation:
                lines.append("**Failure Interpretation**:")
                lines.append("")
                lines.append(ext.data.experiment.failure_interpretation)
                lines.append("")

        return "\n".join(lines)

    def save_markdown_report(self, result: EvaluationResult, filename: str | None = None) -> Path:
        """Markdownレポートを保存

        Args:
            result: 評価結果
            filename: ファイル名（省略時は日時から生成）

        Returns:
            保存先のパス
        """
        if filename is None:
            timestamp = result.evaluated_at.strftime("%Y%m%d_%H%M%S")
            filename = f"evaluation_{timestamp}.md"

        output_path = self.output_dir / filename
        output_path.write_text(
            self.generate_markdown_report(result),
            encoding="utf-8",
        )

        logger.info(f"Saved markdown report to {output_path}")
        return output_path

    # ========== 単体（絶対）評価 ==========

    def _resolve_source(self, index: int, proposal_sources: list[str] | None) -> IdeaSource:
        """proposal_sourcesからIdeaSourceを解決"""
        if proposal_sources and index < len(proposal_sources):
            source_str = proposal_sources[index]
            try:
                return IdeaSource(source_str)
            except ValueError:
                pass
        return IdeaSource.IDEAGRAPH

    def evaluate_single(
        self,
        proposals: list["Proposal"],
        proposal_sources: list[str] | None = None,
    ) -> SingleEvaluationResult:
        """提案群を単体（絶対）評価してランキングを生成

        Args:
            proposals: 評価対象のProposalリスト（1件以上）
            proposal_sources: 各提案のソースリスト（オプション）

        Returns:
            単体評価結果
        """
        logger.info(f"Starting single evaluation of {len(proposals)} proposals")

        idea_results: list[SingleIdeaResult] = []
        for i, proposal in enumerate(proposals):
            idea_id = self._generate_idea_id(i, proposal)
            logger.info(f"Evaluating idea {i + 1}/{len(proposals)}: {proposal.title}")

            scores = self.single_evaluator.evaluate(proposal)
            overall = sum(s.score for s in scores) / len(scores)

            idea_results.append(
                SingleIdeaResult(
                    idea_id=idea_id,
                    idea_title=proposal.title,
                    scores=scores,
                    overall_score=overall,
                    source=self._resolve_source(i, proposal_sources),
                )
            )

        ranking = sorted(idea_results, key=lambda x: x.overall_score, reverse=True)

        result = SingleEvaluationResult(
            evaluated_at=datetime.now(),
            model_name=self.model_name,
            proposals=proposals,
            idea_results=idea_results,
            ranking=ranking,
        )

        logger.info(
            f"Single evaluation completed. Top ranked: "
            f"{ranking[0].idea_title if ranking else 'N/A'}"
        )
        return result

    async def evaluate_single_streaming(
        self,
        proposals: list["Proposal"],
        proposal_sources: list[str] | None = None,
        batch_size: int = 3,
    ) -> AsyncIterator[EvaluationProgressEvent | SingleEvaluationResult]:
        """提案群を単体（絶対）評価（ストリーミング版、バッチ並列実行）

        Args:
            proposals: 評価対象のProposalリスト（1件以上）
            proposal_sources: 各提案のソースリスト（オプション）
            batch_size: 並列実行するバッチサイズ

        Yields:
            EvaluationProgressEvent: 進捗イベント
            SingleEvaluationResult: 最終結果（最後に1回）
        """
        total = len(proposals)
        logger.info(f"Starting single evaluation (streaming) of {total} proposals")

        yield EvaluationProgressEvent(
            event_type="progress",
            current_comparison=0,
            total_comparisons=total,
            phase="evaluating",
            message=f"0/{total}件のアイデアを評価開始",
        )

        idea_results: list[SingleIdeaResult] = []

        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_proposals = [
                (i, proposals[i]) for i in range(batch_start, batch_end)
            ]

            # バッチ内を並列実行
            batch_scores = await asyncio.gather(
                *[self.single_evaluator.evaluate_async(p) for _, p in batch_proposals]
            )

            for (i, proposal), scores in zip(batch_proposals, batch_scores):
                idea_id = self._generate_idea_id(i, proposal)
                overall = sum(s.score for s in scores) / len(scores)

                idea_results.append(
                    SingleIdeaResult(
                        idea_id=idea_id,
                        idea_title=proposal.title,
                        scores=scores,
                        overall_score=overall,
                        source=self._resolve_source(i, proposal_sources),
                    )
                )

            yield EvaluationProgressEvent(
                event_type="progress",
                current_comparison=len(idea_results),
                total_comparisons=total,
                phase="evaluating",
                message=f"{len(idea_results)}/{total}件の評価完了",
            )

        ranking = sorted(idea_results, key=lambda x: x.overall_score, reverse=True)

        result = SingleEvaluationResult(
            evaluated_at=datetime.now(),
            model_name=self.model_name,
            proposals=proposals,
            idea_results=idea_results,
            ranking=ranking,
        )

        logger.info(
            f"Single evaluation completed. Top ranked: "
            f"{ranking[0].idea_title if ranking else 'N/A'}"
        )

        yield result

    def save_single_result(
        self, result: SingleEvaluationResult, filename: str | None = None
    ) -> Path:
        """単体評価結果をJSONファイルに保存"""
        if filename is None:
            timestamp = result.evaluated_at.strftime("%Y%m%d_%H%M%S")
            filename = f"single_evaluation_{timestamp}.json"

        output_path = self.output_dir / filename
        output_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )

        logger.info(f"Saved single evaluation result to {output_path}")
        return output_path

    def generate_single_markdown_report(self, result: SingleEvaluationResult) -> str:
        """単体評価結果をMarkdownレポートとして生成"""
        metric_labels = {
            "novelty": "Novelty",
            "significance": "Significance",
            "feasibility": "Feasibility",
            "clarity": "Clarity",
            "effectiveness": "Effectiveness",
        }

        lines = [
            "# Idea Single Evaluation Report",
            "",
            f"**Evaluated at**: {result.evaluated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Model**: {result.model_name}",
            f"**Number of proposals**: {len(result.proposals)}",
            f"**Evaluation mode**: Single (Absolute)",
            "",
            "## Rankings",
            "",
            "| Rank | Title | Overall | Novelty | Significance | Feasibility | Clarity | Effectiveness |",
            "|------|-------|---------|---------|--------------|-------------|---------|---------------|",
        ]

        for rank, entry in enumerate(result.ranking, 1):
            title = entry.idea_title or entry.idea_id
            scores_dict = {s.metric.value: s.score for s in entry.scores}
            lines.append(
                f"| {rank} | {title} | {entry.overall_score:.1f} "
                f"| {scores_dict.get('novelty', '-')} "
                f"| {scores_dict.get('significance', '-')} "
                f"| {scores_dict.get('feasibility', '-')} "
                f"| {scores_dict.get('clarity', '-')} "
                f"| {scores_dict.get('effectiveness', '-')} |"
            )

        lines.extend(["", "## Detailed Evaluations", ""])

        for rank, entry in enumerate(result.ranking, 1):
            title = entry.idea_title or entry.idea_id
            lines.append(f"### {rank}. {title} (Overall: {entry.overall_score:.1f})")
            lines.append("")
            for s in entry.scores:
                label = metric_labels.get(s.metric.value, s.metric.value)
                lines.append(f"- **{label}** ({s.score}/10): {s.reasoning}")
            lines.append("")

        return "\n".join(lines)
