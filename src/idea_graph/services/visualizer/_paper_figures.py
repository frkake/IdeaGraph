"""Publication-quality cross-experiment synthesis figures for the research paper.

Each figure method corresponds to one numbered figure in the paper.
Missing experiment data is handled gracefully — the figure is skipped
with a log message and an empty path list is returned.

Output: PNG (300 DPI) + SVG per figure via save_figure().
"""

from __future__ import annotations

import re
from pathlib import Path

from ._style import (
    HAS_MPL,
    METRICS,
    METRIC_SHORT,
    METRIC_DISPLAY,
    METRIC_COLORS,
    METHOD_COLORS,
    PALETTE,
    FIG_SINGLE,
    FIG_SINGLE_TALL,
    FIG_DOUBLE,
    FIG_DOUBLE_TALL,
    FIG_DOUBLE_WIDE,
    DOUBLE_COL,
    color_for,
    display_name,
    clean_condition,
    p_stars,
    safe_mean,
    safe_std,
    safe_sem,
    save_figure,
    overlay_strip,
    annotate_n,
    annotate_n_header,
    logger,
)
from ._cross_loader import CrossExperimentLoader, CrossExperimentData
from ._loaders import (
    load_pairwise_elo_by_source,
    load_pairwise_elo_per_paper,
    load_paper_degrees,
    load_single_scores_per_paper,
    load_single_scores,
    load_repeat_scores,
)

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _extract_sweep(conditions: list[str]) -> tuple[list[float], list[str]] | None:
    """Extract numeric parameter values from condition names and sort."""
    values: list[tuple[float, str]] = []
    for cond in conditions:
        nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
        if nums:
            values.append((float(nums[-1]), cond))
    if len(values) < 2:
        return None
    values.sort(key=lambda x: x[0])
    return [v[0] for v in values], [v[1] for v in values]


# ═══════════════════════════════════════════════════════════════════════════
# PaperFigureGenerator
# ═══════════════════════════════════════════════════════════════════════════


class PaperFigureGenerator:
    """Generate the main numbered figures for the research paper.

    All figures follow IEEE double-column style:
    - No figure titles (captions provided in LaTeX)
    - Consistent method colours via color_for()
    - Error bars use SEM
    - Clean, minimal axes (top/right spines already removed by rcParams)
    """

    def __init__(self, runs_base: str | Path) -> None:
        self.runs_base = Path(runs_base)
        self._data: CrossExperimentData | None = None

    # -- data access --------------------------------------------------------

    def _ensure_data(self) -> CrossExperimentData:
        if self._data is None:
            self._data = CrossExperimentLoader(self.runs_base).load()
        return self._data

    # -- public entry point -------------------------------------------------

    def generate_all(
        self,
        output_dir: str | Path,
        formats: list[str] | None = None,
    ) -> dict[str, list[Path]]:
        """Generate every paper figure and return ``{name: [paths]}``."""
        if not HAS_MPL:
            logger.warning("matplotlib not available — skipping paper figures")
            return {}

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        data = self._ensure_data()

        results: dict[str, list[Path]] = {}
        generators = [
            ("fig1_main_results", self._fig1_main_results),
            ("fig2_radar_profile", self._fig2_radar_profile),
            ("fig3_ablation_summary", self._fig3_ablation_summary),
            ("fig4_evaluation_validity", self._fig4_evaluation_validity),
            ("fig5_connectivity", self._fig5_connectivity),
        ]

        for name, gen_fn in generators:
            try:
                paths = gen_fn(data, out)
                if paths:
                    results[name] = paths
                    logger.info("Generated paper figure: %s (%d files)", name, len(paths))
                else:
                    logger.info("Skipped %s (insufficient data)", name)
            except Exception as e:
                logger.warning("Failed to generate %s: %s", name, e, exc_info=True)

        return results

    # ======================================================================
    # Fig 1 — Method Comparison: ELO Grouped Bar
    # ======================================================================

    def _fig1_main_results(
        self, data: CrossExperimentData, output_dir: Path,
    ) -> list[Path]:
        """EXP-101 pairwise ELO — grouped bar across 5 metrics + overall."""
        exp = data.get("EXP-101")
        if exp is None:
            return []

        elo = load_pairwise_elo_by_source(exp.run_dir)
        if not elo:
            return []

        sources = sorted(elo.keys())
        display_metrics = METRICS + ["overall"]
        n_metrics = len(display_metrics)
        n_sources = len(sources)
        bar_w = 0.72 / max(n_sources, 1)

        fig, ax = plt.subplots(figsize=FIG_DOUBLE)
        x = np.arange(n_metrics)

        for s_idx, src in enumerate(sources):
            means = [safe_mean(elo[src].get(m, [])) for m in display_metrics]
            sems = [safe_sem(elo[src].get(m, [])) for m in display_metrics]
            offset = (s_idx - (n_sources - 1) / 2) * bar_w
            ax.bar(
                x + offset,
                means,
                bar_w * 0.88,
                yerr=sems,
                capsize=2,
                color=color_for(src),
                label=display_name(src),
                error_kw={"linewidth": 0.8},
            )
            # Overlay individual ELO values as strip dots
            for m_idx, m in enumerate(display_metrics):
                raw_vals = elo[src].get(m, [])
                bar_x = x[m_idx] + offset
                overlay_strip(
                    ax, bar_x, raw_vals, color_for(src),
                    width=bar_w * 0.3, size=10, alpha=0.4,
                    seed=42 + s_idx * 10 + m_idx,
                )

        # Sample size annotation
        sample_n = max(
            (len(elo[s].get(m, [])) for s in sources for m in display_metrics),
            default=0,
        )
        if sample_n > 0:
            annotate_n_header(ax, sample_n)

        # ELO=1000 baseline
        ax.axhline(1000, color="#888888", linestyle="--", linewidth=0.7, zorder=0)

        # Zoom y-axis to data range
        all_vals = [
            safe_mean(elo[s].get(m, []))
            for s in sources for m in display_metrics
        ]
        if all_vals:
            lo = min(all_vals)
            hi = max(all_vals)
            margin = max((hi - lo) * 0.2, 20)
            ax.set_ylim(min(lo - margin, 990), hi + margin)

        ax.set_xticks(x)
        ax.set_xticklabels(
            [METRIC_DISPLAY.get(m, m) for m in display_metrics],
        )
        ax.set_ylabel("ELO Rating")
        ax.legend(loc="best", ncol=n_sources)
        ax.grid(axis="y", alpha=0.25, linewidth=0.4)
        fig.tight_layout()

        paths = save_figure(fig, output_dir, "fig1_main_results")
        plt.close(fig)
        return paths

    # ======================================================================
    # Fig 2 — Metric Profile Radar
    # ======================================================================

    def _fig2_radar_profile(
        self, data: CrossExperimentData, output_dir: Path,
    ) -> list[Path]:
        """EXP-101 ELO — 5-axis radar chart, one line per method."""
        exp = data.get("EXP-101")
        if exp is None:
            return []

        elo = load_pairwise_elo_by_source(exp.run_dir)
        if not elo:
            return []

        sources = sorted(elo.keys())
        n = len(METRICS)
        angles = [i / n * 2 * np.pi for i in range(n)]
        angles += angles[:1]  # close polygon

        fig, ax = plt.subplots(figsize=FIG_SINGLE_TALL, subplot_kw={"polar": True})
        ax.set_theta_offset(np.pi / 2)   # 0° を上（12時）に
        ax.set_theta_direction(-1)        # 時計回り

        for src in sources:
            vals = [safe_mean(elo[src].get(m, [])) for m in METRICS]
            vals += vals[:1]
            c = color_for(src)
            ax.plot(
                angles, vals, "o-",
                linewidth=1.8, markersize=4, color=c,
                label=display_name(src),
            )
            ax.fill(angles, vals, alpha=0.12, color=c)

        # Overlay individual paper values along each radar axis
        for m_idx, m in enumerate(METRICS):
            angle = angles[m_idx]
            for src in sources:
                raw = elo[src].get(m, [])
                for val in raw:
                    ax.scatter(
                        [angle], [val], s=6, alpha=0.2,
                        color=color_for(src), edgecolors="none", zorder=2,
                    )

        # Sample size annotation
        sample_n = max(
            (len(elo[s].get(m, [])) for s in sources for m in METRICS),
            default=0,
        )
        if sample_n > 0:
            annotate_n_header(ax, sample_n)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([METRIC_DISPLAY.get(m, m) for m in METRICS])

        # Tighten radial limits
        flat = [safe_mean(elo[s].get(m, [])) for s in sources for m in METRICS]
        if flat:
            ax.set_ylim(min(flat) - 30, max(flat) + 30)

        ax.legend(
            loc="upper left", bbox_to_anchor=(-0.30, 1.08),
            framealpha=0.9,
        )
        fig.tight_layout()

        paths = save_figure(fig, output_dir, "fig2_radar_profile")
        plt.close(fig)
        return paths

    # ======================================================================
    # Fig 3 — Key Ablation Results (1x3 multi-panel)
    # ======================================================================

    def _fig3_ablation_summary(
        self, data: CrossExperimentData, output_dir: Path,
    ) -> list[Path]:
        """EXP-201 (hops), EXP-202 (format), EXP-203 (scope) — 1x3 panels."""
        exp201 = data.get("EXP-201")
        exp202 = data.get("EXP-202")
        exp203 = data.get("EXP-203")

        # Need at least one panel to proceed
        if not any([exp201, exp202, exp203]):
            return []

        fig, axes = plt.subplots(1, 3, figsize=(DOUBLE_COL, 2.5))

        # -- Panel 1: Hops line plot ------------------------------------------
        ax1 = axes[0]
        if exp201 is not None:
            scores201 = load_single_scores(exp201.run_dir)
            sweep = _extract_sweep(list(scores201.keys()))
            if sweep is not None:
                x_vals, sorted_conds = sweep
                means = [safe_mean(scores201[c].get("overall", [])) for c in sorted_conds]
                sems = [safe_sem(scores201[c].get("overall", [])) for c in sorted_conds]
                x_arr = np.array(x_vals)
                m_arr = np.array(means)
                s_arr = np.array(sems)
                ax1.plot(x_arr, m_arr, "o-", color=METRIC_COLORS["overall"], linewidth=1.5, markersize=4)
                ax1.fill_between(x_arr, m_arr - s_arr, m_arr + s_arr, alpha=0.15, color=METRIC_COLORS["overall"])
                # Overlay individual paper scores
                for idx, c in enumerate(sorted_conds):
                    raw = scores201[c].get("overall", [])
                    if raw:
                        jitter = np.random.default_rng(42 + idx).uniform(-0.15, 0.15, len(raw))
                        ax1.scatter(
                            [x_vals[idx] + j for j in jitter], raw,
                            s=6, alpha=0.3, color=METRIC_COLORS["overall"],
                            edgecolors="none", zorder=2,
                        )
                # Mark optimal
                if len(m_arr) > 0:
                    best = int(np.argmax(m_arr))
                    ax1.plot(x_arr[best], m_arr[best], "*", color=METRIC_COLORS["overall"], markersize=10, zorder=5)
                # n annotation
                n1 = max((len(scores201[c].get("overall", [])) for c in sorted_conds), default=0)
                if n1 > 0:
                    annotate_n_header(ax1, n1)
                ax1.set_xlabel("Max Hops")
            else:
                ax1.text(0.5, 0.5, "N/A", transform=ax1.transAxes, ha="center", va="center")
        else:
            ax1.text(0.5, 0.5, "N/A", transform=ax1.transAxes, ha="center", va="center")
        ax1.set_ylabel("Overall Score")
        ax1.set_title("(a) Hop Depth", fontsize=9, pad=4)
        ax1.grid(axis="y", alpha=0.25, linewidth=0.4)

        # -- Panel 2: Format bar chart ----------------------------------------
        ax2 = axes[1]
        if exp202 is not None:
            scores202 = load_single_scores(exp202.run_dir)
            conds = list(scores202.keys())
            if conds:
                labels = [clean_condition(c) for c in conds]
                means = [safe_mean(scores202[c].get("overall", [])) for c in conds]
                sems = [safe_sem(scores202[c].get("overall", [])) for c in conds]
                colors = [PALETTE[i % len(PALETTE)] for i in range(len(conds))]
                bars = ax2.bar(labels, means, yerr=sems, capsize=2, color=colors, error_kw={"linewidth": 0.8})
                if means:
                    best_idx = int(np.argmax(means))
                    bars[best_idx].set_edgecolor("#222222")
                    bars[best_idx].set_linewidth(1.5)
                # Overlay individual paper scores
                for idx, c in enumerate(conds):
                    raw = scores202[c].get("overall", [])
                    overlay_strip(ax2, idx, raw, colors[idx], width=0.2, size=8, alpha=0.4, seed=42 + idx)
                # n annotation
                n2 = max((len(scores202[c].get("overall", [])) for c in conds), default=0)
                if n2 > 0:
                    annotate_n_header(ax2, n2)
            else:
                ax2.text(0.5, 0.5, "N/A", transform=ax2.transAxes, ha="center", va="center")
        else:
            ax2.text(0.5, 0.5, "N/A", transform=ax2.transAxes, ha="center", va="center")
        ax2.set_title("(b) Graph Format", fontsize=9, pad=4)
        ax2.grid(axis="y", alpha=0.25, linewidth=0.4)
        for tick in ax2.get_xticklabels():
            tick.set_rotation(15)
            tick.set_ha("right")

        # -- Panel 3: Scope bar chart -----------------------------------------
        ax3 = axes[2]
        if exp203 is not None:
            scores203 = load_single_scores(exp203.run_dir)
            conds = list(scores203.keys())
            if conds:
                labels = [clean_condition(c) for c in conds]
                means = [safe_mean(scores203[c].get("overall", [])) for c in conds]
                sems = [safe_sem(scores203[c].get("overall", [])) for c in conds]
                colors = [PALETTE[i % len(PALETTE)] for i in range(len(conds))]
                bars = ax3.bar(labels, means, yerr=sems, capsize=2, color=colors, error_kw={"linewidth": 0.8})
                if means:
                    best_idx = int(np.argmax(means))
                    bars[best_idx].set_edgecolor("#222222")
                    bars[best_idx].set_linewidth(1.5)
                # Overlay individual paper scores
                for idx, c in enumerate(conds):
                    raw = scores203[c].get("overall", [])
                    overlay_strip(ax3, idx, raw, colors[idx], width=0.2, size=8, alpha=0.4, seed=42 + idx)
                # n annotation
                n3 = max((len(scores203[c].get("overall", [])) for c in conds), default=0)
                if n3 > 0:
                    annotate_n_header(ax3, n3)
            else:
                ax3.text(0.5, 0.5, "N/A", transform=ax3.transAxes, ha="center", va="center")
        else:
            ax3.text(0.5, 0.5, "N/A", transform=ax3.transAxes, ha="center", va="center")
        ax3.set_title("(c) Prompt Scope", fontsize=9, pad=4)
        ax3.grid(axis="y", alpha=0.25, linewidth=0.4)
        # Rotate long labels in scope panel
        for tick in ax3.get_xticklabels():
            tick.set_rotation(15)
            tick.set_ha("right")

        # Zoom y-axes to data range (not 0-based) for visible differences
        data_means: list[float] = []
        for exp_data, exp_scores_fn in [
            (exp201, lambda: load_single_scores(exp201.run_dir) if exp201 else {}),
            (exp202, lambda: load_single_scores(exp202.run_dir) if exp202 else {}),
            (exp203, lambda: load_single_scores(exp203.run_dir) if exp203 else {}),
        ]:
            if exp_data is not None:
                sc = exp_scores_fn()
                for c in sc.values():
                    m = safe_mean(c.get("overall", []))
                    if m > 0:
                        data_means.append(m)
        if data_means:
            lo = min(data_means)
            hi = max(data_means)
            margin = max((hi - lo) * 0.5, 0.3)
            y_lo = max(0, lo - margin)
            y_hi = hi + margin
            for ax in axes:
                ax.set_ylim(y_lo, y_hi)

        fig.tight_layout()
        paths = save_figure(fig, output_dir, "fig3_ablation_summary")
        plt.close(fig)
        return paths

    # ======================================================================
    # Fig 4 — Evaluation Validity (1x2 multi-panel)
    # ======================================================================

    def _fig4_evaluation_validity(
        self, data: CrossExperimentData, output_dir: Path,
    ) -> list[Path]:
        """EXP-302 reproducibility (box) + EXP-301 mode consistency (scatter)."""
        exp302 = data.get("EXP-302")
        exp301 = data.get("EXP-301")

        if exp302 is None and exp301 is None:
            return []

        fig, axes = plt.subplots(1, 2, figsize=FIG_DOUBLE)

        # -- Panel 1: Reproducibility box plot (EXP-302) ----------------------
        ax1 = axes[0]
        if exp302 is not None:
            repeat = load_repeat_scores(exp302.run_dir)
            if repeat:
                # Flatten: collect per-repeat overall means
                box_data: list[list[float]] = []
                box_labels: list[str] = []
                for cond, metrics_by_repeat in repeat.items():
                    overall_repeats = metrics_by_repeat.get("overall", [])
                    for r_idx, scores_list in enumerate(overall_repeats):
                        if scores_list:
                            box_data.append(scores_list)
                            box_labels.append(f"R{r_idx + 1}")

                if box_data:
                    bp = ax1.boxplot(
                        box_data,
                        labels=box_labels,
                        patch_artist=True,
                        widths=0.5,
                        medianprops={"color": "#222222", "linewidth": 1.2},
                        whiskerprops={"linewidth": 0.8},
                        capprops={"linewidth": 0.8},
                        flierprops={"markersize": 3, "alpha": 0.5},
                    )
                    for patch in bp["boxes"]:
                        patch.set_facecolor(METRIC_COLORS.get("overall", "#AAAAAA"))
                        patch.set_alpha(0.5)
                    # Overlay individual points inside boxes
                    for idx, scores_list in enumerate(box_data):
                        overlay_strip(
                            ax1, idx + 1, scores_list,
                            METRIC_COLORS.get("overall", "#AAAAAA"),
                            width=0.15, size=6, alpha=0.4, seed=42 + idx,
                        )
                    # n annotation
                    n_box = max((len(sl) for sl in box_data), default=0)
                    if n_box > 0:
                        annotate_n_header(ax1, n_box)
                    ax1.set_ylabel("Overall Score")
                else:
                    ax1.text(0.5, 0.5, "N/A", transform=ax1.transAxes, ha="center", va="center")
            else:
                ax1.text(0.5, 0.5, "N/A", transform=ax1.transAxes, ha="center", va="center")
        else:
            ax1.text(0.5, 0.5, "N/A", transform=ax1.transAxes, ha="center", va="center")
        ax1.set_title("(a) Reproducibility", fontsize=9, pad=4)
        ax1.grid(axis="y", alpha=0.25, linewidth=0.4)

        # -- Panel 2: Mode consistency scatter (EXP-301) ----------------------
        ax2 = axes[1]
        if exp301 is not None:
            per_paper = load_single_scores_per_paper(exp301.run_dir)
            pw_per_paper = load_pairwise_elo_per_paper(exp301.run_dir)

            single_vals: list[float] = []
            pairwise_vals: list[float] = []

            # Match per-paper: single score vs pairwise ELO for same condition
            for cond, papers in per_paper.items():
                for paper_id, scores in papers.items():
                    s_overall = scores.get("overall")
                    if s_overall is None:
                        continue
                    pw_paper = pw_per_paper.get(paper_id, {})
                    for src, pw_val in pw_paper.items():
                        if src in cond or cond in src:
                            single_vals.append(s_overall)
                            pairwise_vals.append(pw_val)
                            break

            if len(single_vals) >= 3:
                try:
                    from idea_graph.services.aggregator import spearman
                    rho = spearman(single_vals, pairwise_vals)
                except ImportError:
                    rho = 0.0

                ax2.scatter(
                    single_vals, pairwise_vals,
                    s=25, alpha=0.7, color=METRIC_COLORS.get("novelty", "#4477AA"),
                    edgecolors="white", linewidth=0.5, zorder=3,
                )

                # Regression line
                x_arr = np.array(single_vals)
                y_arr = np.array(pairwise_vals)
                if len(set(x_arr)) >= 2:
                    coeffs = np.polyfit(x_arr, y_arr, 1)
                    x_line = np.linspace(x_arr.min(), x_arr.max(), 50)
                    ax2.plot(x_line, np.polyval(coeffs, x_line), "--", color="#888888", linewidth=1.0)

                ax2.text(
                    0.05, 0.95,
                    f"Spearman $\\rho$ = {rho:.3f}\nn = {len(single_vals)}",
                    transform=ax2.transAxes, fontsize=7, va="top",
                    bbox={"boxstyle": "round,pad=0.3", "facecolor": "white",
                          "edgecolor": "#CCCCCC", "alpha": 0.9},
                )
                ax2.set_xlabel("Independent Score")
                ax2.set_ylabel("Pairwise Score")
            else:
                ax2.text(0.5, 0.5, "N/A", transform=ax2.transAxes, ha="center", va="center")
        else:
            ax2.text(0.5, 0.5, "N/A", transform=ax2.transAxes, ha="center", va="center")
        ax2.set_title("(b) Mode Consistency", fontsize=9, pad=4)
        ax2.grid(alpha=0.25, linewidth=0.4)

        fig.tight_layout()
        paths = save_figure(fig, output_dir, "fig4_evaluation_validity")
        plt.close(fig)
        return paths

    # ======================================================================
    # Fig 5 — Connectivity: Degree vs Quality Scatter
    # ======================================================================

    def _fig5_connectivity(
        self, data: CrossExperimentData, output_dir: Path,
    ) -> list[Path]:
        """EXP-208: scatter + regression + 95% CI band + Spearman rho."""
        exp = data.get("EXP-208")
        if exp is None:
            return []

        degrees = load_paper_degrees(exp.run_dir)
        per_paper = load_single_scores_per_paper(exp.run_dir)
        if not degrees or not per_paper:
            return []

        # Collect (degree, overall) pairs across all conditions
        deg_vals: list[float] = []
        score_vals: list[float] = []
        for _cond, papers in per_paper.items():
            for paper_id, scores in papers.items():
                deg = degrees.get(paper_id)
                overall = scores.get("overall")
                if deg is not None and overall is not None:
                    deg_vals.append(float(deg))
                    score_vals.append(float(overall))

        if not deg_vals:
            return []

        try:
            from idea_graph.services.aggregator import spearman
        except ImportError:
            spearman = lambda x, y: 0.0  # noqa: E731

        fig, ax = plt.subplots(figsize=FIG_SINGLE)
        x_arr = np.array(deg_vals)
        y_arr = np.array(score_vals)

        ax.scatter(
            x_arr, y_arr, s=30, alpha=0.7,
            color=METRIC_COLORS.get("novelty", "#4477AA"),
            edgecolors="white", linewidth=0.5, zorder=3,
        )

        # Regression + 95% CI
        if len(x_arr) >= 2 and len(set(x_arr)) >= 2:
            coeffs = np.polyfit(x_arr, y_arr, 1)
            x_line = np.linspace(x_arr.min() - 0.5, x_arr.max() + 0.5, 200)
            y_line = np.polyval(coeffs, x_line)
            ax.plot(x_line, y_line, "-", color=METRIC_COLORS.get("significance", "#EE6677"),
                    linewidth=1.2, label="Linear fit")

            residuals = y_arr - np.polyval(coeffs, x_arr)
            se = float(np.std(residuals))
            ax.fill_between(
                x_line, y_line - 1.96 * se, y_line + 1.96 * se,
                alpha=0.10, color=METRIC_COLORS.get("significance", "#EE6677"),
                label="95% CI",
            )

        # Spearman annotation
        n = len(deg_vals)
        rho = spearman(deg_vals, score_vals) if n >= 3 else 0.0
        ax.text(
            0.05, 0.95,
            f"Spearman $\\rho$ = {rho:.3f}\nn = {n}",
            transform=ax.transAxes, fontsize=7, va="top",
            bbox={"boxstyle": "round,pad=0.3", "facecolor": "white",
                  "edgecolor": "#CCCCCC", "alpha": 0.9},
        )

        ax.set_xlabel("Degree (connections)")
        ax.set_ylabel("Overall Score")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="lower right", framealpha=0.9)
        ax.grid(alpha=0.25, linewidth=0.4)
        fig.tight_layout()

        paths = save_figure(fig, output_dir, "fig5_connectivity")
        plt.close(fig)
        return paths
