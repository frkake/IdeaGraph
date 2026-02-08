"""統計アノテーションブリッジ — aggregator.py の関数をチャート向けに包む"""

from __future__ import annotations

from pathlib import Path

from ._style import METRICS, _p_label, _safe_mean
from ._loaders import load_single_scores, load_aggregate

from idea_graph.services.aggregator import (
    cohen_d,
    paired_permutation_pvalue,
    pearson,
    spearman,
    krippendorffs_alpha,
    holm_bonferroni,
)


class StatsHelper:
    """実験ディレクトリのスコアを対象に統計量を計算する。"""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._scores = load_single_scores(run_dir)
        self._aggregate = load_aggregate(run_dir)

    def per_metric_significance(
        self, cond_a: str, cond_b: str,
    ) -> list[dict]:
        """指標ごとの p 値、Cohen's d、有意差ラベルを返す。"""
        results = []
        a_scores = self._scores.get(cond_a, {})
        b_scores = self._scores.get(cond_b, {})

        pvalues: dict[str, float] = {}
        raw: dict[str, dict] = {}

        for metric in METRICS + ["overall"]:
            a = a_scores.get(metric, [])
            b = b_scores.get(metric, [])
            n = min(len(a), len(b))
            if n == 0:
                continue
            a_trunc = a[:n]
            b_trunc = b[:n]
            p = paired_permutation_pvalue(a_trunc, b_trunc)
            d = cohen_d(a_trunc, b_trunc)
            pvalues[metric] = p
            raw[metric] = {"p": p, "d": d, "n": n}

        corrected = holm_bonferroni(pvalues) if pvalues else {}

        for metric, info in raw.items():
            results.append({
                "metric": metric,
                "cond_a": cond_a,
                "cond_b": cond_b,
                "p": info["p"],
                "d": info["d"],
                "label": _p_label(info["p"]),
                "significant": corrected.get(metric, False),
            })

        return results

    def correlation(
        self, x: list[float], y: list[float],
    ) -> dict[str, float]:
        return {
            "pearson_r": pearson(x, y),
            "spearman_rho": spearman(x, y),
            "n": float(len(x)),
        }

    def irr_alphas(self) -> dict[str, dict[str, float]]:
        """aggregate.json から Krippendorff's alpha を取得する。"""
        irr = self._aggregate.get("inter_rater_reliability", {})
        result: dict[str, dict[str, float]] = {}
        for condition, data in irr.items():
            alphas = data.get("krippendorffs_alpha", {})
            result[condition] = alphas
        return result

    def condition_means(self, cond: str) -> dict[str, float]:
        """条件の指標別平均を返す。"""
        s = self._scores.get(cond, {})
        return {m: _safe_mean(s.get(m, [])) for m in METRICS + ["overall"]}
