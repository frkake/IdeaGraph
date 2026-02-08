"""全実験横断データローダー — experiments/runs/ 以下をスキャンして統合データを提供"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ._style import METRICS, _safe_mean, _safe_std, logger
from ._loaders import (
    load_single_scores,
    load_pairwise_wins,
    load_pairwise_details,
    load_single_scores_per_paper,
    load_aggregate,
    load_experiment_meta,
    load_metadata,
    load_repeat_scores,
    load_pairwise_swap_data,
    load_multi_model_scores,
)
from ._stats import StatsHelper


@dataclass
class ExperimentData:
    """単一実験のロード済みデータ。"""

    exp_id: str
    run_dir: Path
    meta: dict
    single_scores: dict[str, dict[str, list[float]]]
    pairwise_wins: dict[str, int]
    per_paper: dict[str, dict[str, dict[str, float]]]
    aggregate: dict
    stats: StatsHelper | None = None


@dataclass
class CrossExperimentData:
    """全実験横断のデータコンテナ。"""

    experiments: dict[str, ExperimentData] = field(default_factory=dict)
    available: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)

    def get(self, exp_id: str) -> ExperimentData | None:
        return self.experiments.get(exp_id)

    def has(self, exp_id: str) -> bool:
        return exp_id in self.experiments


class CrossExperimentLoader:
    """experiments/runs/ 以下を横断スキャンして CrossExperimentData を構築する。"""

    ALL_EXP_IDS = [
        "EXP-101", "EXP-102", "EXP-103",
        "EXP-201", "EXP-202", "EXP-203", "EXP-204",
        "EXP-205", "EXP-206", "EXP-207", "EXP-208", "EXP-209",
        "EXP-301", "EXP-302", "EXP-303", "EXP-304", "EXP-305", "EXP-306",
    ]

    def __init__(self, runs_base: str | Path) -> None:
        self.runs_base = Path(runs_base)

    def load(self, required: list[str] | None = None) -> CrossExperimentData:
        target_ids = required or self.ALL_EXP_IDS
        latest = self._find_latest_runs()

        data = CrossExperimentData()
        for exp_id in target_ids:
            run_dir = latest.get(exp_id)
            if run_dir is None:
                data.missing.add(exp_id)
                continue
            try:
                exp = self._load_experiment(exp_id, run_dir)
                data.experiments[exp_id] = exp
                data.available.add(exp_id)
            except Exception as e:
                logger.warning("Failed to load %s from %s: %s", exp_id, run_dir, e)
                data.missing.add(exp_id)

        logger.info(
            "CrossExperimentLoader: %d available, %d missing",
            len(data.available), len(data.missing),
        )
        return data

    def _find_latest_runs(self) -> dict[str, Path]:
        """各 exp_id の最新 run ディレクトリを返す。"""
        if not self.runs_base.exists():
            return {}

        latest: dict[str, Path] = {}
        dirs = sorted(self.runs_base.iterdir(), reverse=True)

        for d in dirs:
            if not d.is_dir():
                continue
            # ディレクトリ名: EXP-101_20250208T123456
            parts = d.name.split("_", 1)
            exp_id = parts[0]
            if exp_id not in latest:
                latest[exp_id] = d

        return latest

    def _load_experiment(self, exp_id: str, run_dir: Path) -> ExperimentData:
        meta = load_experiment_meta(run_dir)
        single_scores = load_single_scores(run_dir)
        pairwise_wins = load_pairwise_wins(run_dir)
        per_paper = load_single_scores_per_paper(run_dir)
        aggregate = load_aggregate(run_dir)

        stats = None
        if single_scores:
            try:
                stats = StatsHelper(run_dir)
            except Exception:
                pass

        return ExperimentData(
            exp_id=exp_id,
            run_dir=run_dir,
            meta=meta,
            single_scores=single_scores,
            pairwise_wins=pairwise_wins,
            per_paper=per_paper,
            aggregate=aggregate,
            stats=stats,
        )
