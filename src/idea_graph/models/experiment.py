"""実験実行設定モデル"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ExperimentCategory(str, Enum):
    SYSTEM_EFFECTIVENESS = "system_effectiveness"
    ABLATION = "ablation"
    COMPARISON = "comparison"
    EVALUATION_VALIDITY = "evaluation_validity"


class PaperSelectionStrategy(str, Enum):
    MANUAL = "manual"
    RANDOM = "random"
    CONNECTIVITY = "connectivity"
    CONNECTIVITY_STRATIFIED = "connectivity_stratified"
    IN_DEGREE = "in_degree"
    IN_DEGREE_STRATIFIED = "in_degree_stratified"


class MethodType(str, Enum):
    IDEAGRAPH = "ideagraph"
    DIRECT_LLM = "direct_llm"
    COI = "coi"
    TARGET_PAPER = "target_paper"


class CandidateScope(str, Enum):
    ALL = "all"
    DATASET = "dataset"


class EvaluationMode(str, Enum):
    PAIRWISE = "pairwise"
    SINGLE = "single"
    BOTH = "both"


class ExperimentMeta(BaseModel):
    id: str
    name: str
    category: ExperimentCategory = ExperimentCategory.SYSTEM_EFFECTIVENESS
    description: str = ""
    visualizer_id: str | None = None


class SeedConfig(BaseModel):
    paper_selection: int = 20260207
    evaluation_shuffle: int = 20260207


class TargetsConfig(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    selection_strategy: PaperSelectionStrategy = PaperSelectionStrategy.MANUAL
    candidate_scope: CandidateScope = CandidateScope.ALL
    connectivity_tier_filter: str | None = None
    count: int = 15

    @field_validator("connectivity_tier_filter")
    @classmethod
    def _validate_tier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"high", "medium", "low"}:
            raise ValueError("connectivity_tier_filter must be one of: high, medium, low")
        return normalized


class AnalysisConfig(BaseModel):
    max_hops: int = Field(default=3, ge=1, le=10)
    top_k: int | None = Field(default=10, description="Noneの場合は制限なし（全パスを返す）")

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("top_k must be >= 1 if specified")
        return value


class PromptConfig(BaseModel):
    graph_format: str = "mermaid"
    scope: str = "path"
    max_paths: int = Field(default=10, ge=1)
    max_nodes: int = Field(default=50, ge=1)
    max_edges: int = Field(default=100, ge=1)
    neighbor_k: int = Field(default=2, ge=1)
    include_inline_edges: bool = True
    include_target_paper: bool = False
    exclude_future_papers: bool = True

    @field_validator("graph_format")
    @classmethod
    def _validate_graph_format(cls, value: str) -> str:
        if value not in {"mermaid", "paths"}:
            raise ValueError("graph_format must be 'mermaid' or 'paths'")
        return value

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, value: str) -> str:
        if value not in {"path", "k_hop", "path_plus_k_hop"}:
            raise ValueError("scope must be path | k_hop | path_plus_k_hop")
        return value


class GenerationConfig(BaseModel):
    num_proposals: int = Field(default=3, ge=1)
    model: str = "gpt-5.2-2025-12-11"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class ConditionConfig(BaseModel):
    name: str
    method: MethodType
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    analysis: AnalysisConfig | None = None
    prompt: PromptConfig | None = None


class EvaluationConfig(BaseModel):
    mode: EvaluationMode = EvaluationMode.BOTH
    model: str = "gpt-5.2-2025-12-11"
    """評価（ペア比較・絶対評価）に使うLLM"""
    extraction_model: str | None = None
    """ターゲット論文からの研究アイデア抽出に使うLLM。未指定時は model を使う"""
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    include_experiment: bool = True
    include_target: bool = False
    repeat: int = Field(default=1, ge=1)
    models: list[str] | None = None


class OutputConfig(BaseModel):
    base_dir: str = "experiments/runs"


class ExperimentConfig(BaseModel):
    experiment: ExperimentMeta
    seed: SeedConfig = Field(default_factory=SeedConfig)
    targets: TargetsConfig = Field(default_factory=TargetsConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    prompt: PromptConfig = Field(default_factory=PromptConfig)
    conditions: list[ConditionConfig]
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def _validate_conditions(self) -> "ExperimentConfig":
        if not self.conditions:
            raise ValueError("conditions must contain at least one item")
        names = [c.name for c in self.conditions]
        if len(names) != len(set(names)):
            raise ValueError("condition names must be unique")
        return self


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    """YAML設定ファイルを読み込んで検証する。"""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    try:
        import yaml
    except Exception as exc:
        raise RuntimeError("PyYAML is required to load experiment configs") from exc

    data: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("experiment config must be a mapping")
    return ExperimentConfig.model_validate(data)
