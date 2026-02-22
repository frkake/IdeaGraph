"""Statistical helpers for visualization annotations.

Wraps aggregator.py functions for easy use in chart code.
"""

from __future__ import annotations

from pathlib import Path

from ._style import METRICS, p_stars, safe_mean
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
    """Compute statistical annotations from experiment run data."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self._scores = load_single_scores(run_dir)
        self._aggregate = load_aggregate(run_dir)

    def per_metric_significance(
        self, cond_a: str, cond_b: str,
    ) -> list[dict]:
        """Return per-metric significance test results.

        Returns list of {metric, cond_a, cond_b, p, d, stars, significant}.
        """
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
            a_t, b_t = a[:n], b[:n]
            p = paired_permutation_pvalue(a_t, b_t)
            d = cohen_d(a_t, b_t)
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
                "stars": p_stars(info["p"]),
                "significant": corrected.get(metric, False),
            })
        return results

    def correlation(self, x: list[float], y: list[float]) -> dict[str, float]:
        """Compute Pearson r and Spearman rho."""
        return {
            "pearson_r": pearson(x, y),
            "spearman_rho": spearman(x, y),
            "n": float(len(x)),
        }

    def irr_alphas(self) -> dict[str, dict[str, float]]:
        """Get Krippendorff's alpha from aggregate.json."""
        irr = self._aggregate.get("inter_rater_reliability", {})
        result: dict[str, dict[str, float]] = {}
        for cond, data in irr.items():
            alphas = data.get("krippendorffs_alpha", {})
            result[cond] = alphas
        return result

    def condition_means(self, cond: str) -> dict[str, float]:
        """Return per-metric means for a condition."""
        s = self._scores.get(cond, {})
        return {m: safe_mean(s.get(m, [])) for m in METRICS + ["overall"]}
