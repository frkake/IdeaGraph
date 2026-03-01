"""Main visualizer — dispatch to specialized visualizers or fallback."""

from __future__ import annotations

import re
from pathlib import Path

from ._style import (
    HAS_MPL, METRICS, METRIC_SHORT, METRIC_DISPLAY, METRIC_COLORS,
    safe_mean, safe_std, save_figure, clean_condition, logger,
    FIG_DOUBLE, FIG_DOUBLE_WIDE,
)
from ._loaders import load_single_scores, load_pairwise_wins, load_experiment_meta
from ._registry import get_visualizer
from ._paper_figures import PaperFigureGenerator
from ._paper_tables import PaperTableGenerator

# Import experiment modules to trigger @register decorators
from . import _exp_1xx  # noqa: F401
from . import _exp_2xx  # noqa: F401
from . import _exp_3xx  # noqa: F401


class ExperimentVisualizer:
    """Main entry point: auto-generate charts from a run directory."""

    def visualize(
        self,
        run_dir: str | Path,
        paper_ids: list[str] | None = None,
    ) -> list[Path]:
        if not HAS_MPL:
            logger.warning("matplotlib not installed. Skipping visualization.")
            return []

        from ._loaders import set_paper_filter
        set_paper_filter(paper_ids)
        try:
            return self._visualize_inner(Path(run_dir))
        finally:
            set_paper_filter(None)

    def _visualize_inner(self, run_path: Path) -> list[Path]:
        figures_dir = run_path / "figures"
        meta = load_experiment_meta(run_path)
        exp_id = meta.get("experiment_id", run_path.name.split("_")[0])
        vis_key = meta.get("visualizer_id") or exp_id

        # Look up specialized visualizer
        vis_fn = get_visualizer(vis_key)
        if vis_fn is not None:
            logger.info("Using specialized visualizer for %s (vis_key=%s)", exp_id, vis_key)
            all_paths = vis_fn(run_path, figures_dir, exp_id)
            logger.info("Generated %d figure files in %s", len(all_paths), figures_dir)
            return all_paths

        # Fallback: generic charts
        logger.info("No specialized visualizer for %s (vis_key=%s), using fallback", exp_id, vis_key)
        return self._fallback(run_path, figures_dir, exp_id)

    def generate_paper_figures(
        self,
        output_dir: str | Path | None = None,
        runs_base: str | Path | None = None,
        formats: list[str] | None = None,
    ) -> dict[str, list[Path]]:
        """Generate cross-experiment paper-quality synthesis figures + tables."""
        if not HAS_MPL:
            logger.warning("matplotlib not installed. Skipping paper figures.")
            return {}

        runs = Path(runs_base) if runs_base else Path("experiments/runs")
        out = Path(output_dir) if output_dir else Path("experiments/paper_figures")

        results: dict[str, list[Path]] = {}

        fig_gen = PaperFigureGenerator(runs)
        results.update(fig_gen.generate_all(out, formats))

        tbl_gen = PaperTableGenerator(runs)
        results.update(tbl_gen.generate_all(out))

        return results

    def _fallback(self, run_path: Path, figures_dir: Path, exp_id: str) -> list[Path]:
        """Generic fallback: grouped bar + radar for any single-eval experiment."""
        import matplotlib.pyplot as plt
        import numpy as np

        scores = load_single_scores(run_path)
        all_paths: list[Path] = []

        if not scores:
            logger.info("No single evaluation scores found for visualization.")
            return all_paths

        conditions = list(scores.keys())

        # Grouped bar chart
        if len(conditions) >= 2:
            fig, ax = plt.subplots(figsize=FIG_DOUBLE)
            n_metrics = len(METRICS)
            n_conds = len(conditions)
            bar_width = 0.8 / n_conds
            x_base = np.arange(n_metrics)
            from ._style import color_for
            for c_idx, cond in enumerate(conditions):
                means = [safe_mean(scores[cond].get(m, [])) for m in METRICS]
                sems = [safe_std(scores[cond].get(m, [])) / max(1, len(scores[cond].get(m, []))) ** 0.5 for m in METRICS]
                offset = (c_idx - (n_conds - 1) / 2) * bar_width
                ax.bar(
                    x_base + offset, means, bar_width * 0.88,
                    yerr=sems, capsize=3, color=color_for(cond),
                    alpha=0.85, label=clean_condition(cond), error_kw={"linewidth": 0.8},
                )
            ax.set_xticks(x_base)
            ax.set_xticklabels(
                [METRIC_DISPLAY.get(m, m) for m in METRICS],
                fontsize=8, rotation=30, ha="right",
            )
            ax.set_ylabel("Score (1\u201310)")
            ax.legend(fontsize=8)
            ax.grid(axis="y", alpha=0.3, linewidth=0.5)
            fig.tight_layout()
            all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_grouped_bar"))
            plt.close(fig)

        # Radar chart
        if conditions:
            fig, ax = plt.subplots(figsize=(3.5, 3.5), subplot_kw={"polar": True})
            ax.set_theta_offset(np.pi / 2)   # 0° を上（12時）に
            ax.set_theta_direction(-1)        # 時計回り
            angles = [n / len(METRICS) * 2 * np.pi for n in range(len(METRICS))]
            angles += angles[:1]
            from ._style import color_for
            for cond in conditions:
                values = [safe_mean(scores[cond].get(m, [])) for m in METRICS]
                values += values[:1]
                ax.plot(angles, values, "o-", linewidth=1.5, label=clean_condition(cond), color=color_for(cond), markersize=4)
                ax.fill(angles, values, alpha=0.1, color=color_for(cond))
            ax.set_xticks(angles[:-1])
            ax.set_xticklabels(
                [METRIC_DISPLAY.get(m, m) for m in METRICS],
                fontsize=8, rotation=30, ha="right",
            )
            ax.set_ylim(0, 10)
            ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=7)
            fig.tight_layout()
            all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_2_radar"))
            plt.close(fig)

        # Pairwise win bar
        wins = load_pairwise_wins(run_path)
        if wins:
            fig, ax = plt.subplots(figsize=(3.5, 2.5))
            total = sum(wins.values())
            labels = list(wins.keys())
            values = [wins[l] / total * 100 for l in labels]
            from ._style import color_for
            ax.bar(labels, values, color=[color_for(l) for l in labels], alpha=0.85)
            ax.set_ylabel("Win Rate (%)")
            ax.grid(axis="y", alpha=0.3, linewidth=0.5)
            fig.tight_layout()
            all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_3_winrate"))
            plt.close(fig)

        logger.info("Generated %d figure files in %s", len(all_paths), figures_dir)
        return all_paths

    @staticmethod
    def _detect_parameter_sweep(
        conditions: list[str],
        scores: dict[str, dict[str, list[float]]],
    ) -> tuple[list[float], list[float], list[float]] | None:
        """Detect numeric parameter sweep from condition names."""
        values: list[tuple[float, str]] = []
        for cond in conditions:
            nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
            if nums:
                values.append((float(nums[-1]), cond))
        if len(values) < 3:
            return None
        values.sort(key=lambda x: x[0])
        x_vals = [v[0] for v in values]
        y_means = [safe_mean(scores[v[1]].get("overall", [])) for v in values]
        y_stds = [safe_std(scores[v[1]].get("overall", [])) for v in values]
        return x_vals, y_means, y_stds
