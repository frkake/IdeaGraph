"""100-series: System effectiveness experiments (EXP-101 through EXP-106).

EXP-101: 3-method pairwise comparison (IdeaGraph vs Direct LLM vs CoI-Agent) -- ELO
EXP-102: Generated ideas vs original paper -- Pairwise ELO
EXP-103: IdeaGraph single evaluation (absolute 1-10 scores)
EXP-104: Direct LLM single evaluation
EXP-105: CoI-Agent single evaluation
EXP-106: Target Paper single evaluation
"""

from __future__ import annotations

import json
from pathlib import Path

from ._registry import register
from ._loaders import (
    load_pairwise_elo_by_source,
    load_single_scores,
    load_single_scores_per_paper,
    load_pairwise_details,
    load_pairwise_wins,
)
from ._stats import StatsHelper
from ._style import (
    HAS_MPL,
    METRICS,
    METRIC_SHORT,
    METRIC_DISPLAY,
    METRIC_COLORS,
    METHOD_COLORS,
    PALETTE,
    TOL_BLUE,
    TOL_RED,
    TOL_GREEN,
    TOL_YELLOW,
    TOL_CYAN,
    TOL_PURPLE,
    TOL_GREY,
    FIG_SINGLE,
    FIG_SINGLE_TALL,
    FIG_DOUBLE,
    FIG_DOUBLE_TALL,
    FIG_DOUBLE_WIDE,
    color_for,
    display_name,
    p_stars,
    safe_mean,
    safe_std,
    safe_sem,
    overlay_strip,
    annotate_n,
    annotate_n_header,
    save_figure,
    logger,
)

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# ======================================================================
# Shared helpers
# ======================================================================


def _load_source_elo_summary(
    run_dir: Path,
) -> dict[str, dict[str, tuple[float, float]]]:
    """Return {source: {metric: (mean_elo, sem_elo)}} from pairwise data."""
    elo_by_source = load_pairwise_elo_by_source(run_dir)
    summary: dict[str, dict[str, tuple[float, float]]] = {}
    for source, metrics in elo_by_source.items():
        summary[source] = {}
        for m, vals in metrics.items():
            summary[source][m] = (safe_mean(vals), safe_sem(vals))
    return summary


def _single_score_bar(
    run_dir: Path,
    figures_dir: Path,
    exp_id: str,
    condition_name: str,
) -> list[Path]:
    """Grouped bar chart of single-evaluation scores for one condition.

    Shows 5 metrics + overall with SEM error bars.  Used by EXP-103..106.
    """
    if not HAS_MPL:
        return []

    all_scores = load_single_scores(run_dir)
    cond_scores = all_scores.get(condition_name)

    # If exact name not found, try partial match
    if cond_scores is None:
        for key in all_scores:
            if condition_name.lower() in key.lower():
                cond_scores = all_scores[key]
                condition_name = key
                break

    if not cond_scores:
        logger.warning(
            "%s: No single scores found for condition '%s'", exp_id, condition_name,
        )
        return []

    display_metrics = METRICS + ["overall"]
    means = [safe_mean(cond_scores.get(m, [])) for m in display_metrics]
    sems = [safe_sem(cond_scores.get(m, [])) for m in display_metrics]
    labels = [METRIC_DISPLAY.get(m, m.capitalize()) for m in display_metrics]

    fig, ax = plt.subplots(figsize=FIG_SINGLE)
    x = np.arange(len(display_metrics))
    colors = [METRIC_COLORS.get(m, TOL_GREY) for m in display_metrics]

    bars = ax.bar(
        x, means, width=0.6,
        yerr=sems, capsize=3,
        color=colors, alpha=0.85,
        edgecolor="white", linewidth=0.5,
        error_kw={"linewidth": 0.8, "capthick": 0.8},
    )

    # Overlay individual data points as strip dots
    for i, m in enumerate(display_metrics):
        raw_vals = cond_scores.get(m, [])
        if raw_vals:
            overlay_strip(
                ax, x[i], raw_vals, colors[i],
                width=0.25, size=12, alpha=0.45, seed=42 + i,
            )

    # Annotate sample size in upper-right corner
    first_metric_vals = cond_scores.get(display_metrics[0], [])
    if first_metric_vals:
        annotate_n_header(ax, len(first_metric_vals))

    # Value labels on bars
    for bar, val in zip(bars, means):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.15,
            f"{val:.1f}",
            ha="center", va="bottom", fontsize=7, fontweight="bold",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8, rotation=30, ha="right")
    ax.set_ylabel("Score (1\u201310)", fontsize=9)
    ax.set_ylim(0, 10.5)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig.tight_layout()

    all_paths = save_figure(fig, figures_dir, f"fig_{exp_id}_1_scores")
    plt.close(fig)

    # --- Tables ---
    _generate_single_tables(cond_scores, display_metrics, condition_name, figures_dir, exp_id)

    return all_paths


def _generate_single_tables(
    scores: dict[str, list[float]],
    display_metrics: list[str],
    condition_name: str,
    output_dir: Path,
    exp_id: str,
) -> None:
    """Generate Markdown + LaTeX tables for a single condition's scores."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect data
    rows_data: list[tuple[str, float, float, int]] = []
    for m in display_metrics:
        vals = scores.get(m, [])
        rows_data.append((
            METRIC_DISPLAY.get(m, m.capitalize()),
            safe_mean(vals),
            safe_sem(vals),
            len(vals),
        ))

    # Find best values per column (mean)
    best_mean = max(r[1] for r in rows_data) if rows_data else 0.0

    # --- Markdown ---
    md_lines = [
        f"## {exp_id}: {display_name(condition_name)} Single Evaluation Scores",
        "",
        "| Metric | Mean | SEM | N |",
        "|--------|-----:|----:|--:|",
    ]
    for label, mean, sem, n in rows_data:
        bold = "**" if mean == best_mean else ""
        md_lines.append(f"| {label} | {bold}{mean:.2f}{bold} | {sem:.2f} | {n} |")

    (output_dir / f"table_{exp_id}.md").write_text(
        "\n".join(md_lines) + "\n", encoding="utf-8",
    )

    # --- LaTeX ---
    tex_rows = []
    for label, mean, sem, n in rows_data:
        val_str = f"{mean:.2f} $\\pm$ {sem:.2f}"
        if mean == best_mean:
            val_str = f"\\textbf{{{mean:.2f}}} $\\pm$ {sem:.2f}"
        tex_rows.append(f"  {label} & {val_str} & {n}" + r" \\")

    tex = (
        r"\begin{table}[htbp]" + "\n"
        r"  \centering" + "\n"
        f"  \\caption{{{exp_id}: {display_name(condition_name)} Single Evaluation Scores}}\n"
        r"  \begin{tabular}{lrr}" + "\n"
        r"    \toprule" + "\n"
        r"    Metric & Score (Mean $\pm$ SEM) & $N$ \\" + "\n"
        r"    \midrule" + "\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        r"    \bottomrule" + "\n"
        r"  \end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")


# ======================================================================
# EXP-101: 3-Method Comparison (Pairwise ELO)
# ======================================================================


@register("EXP-101")
def vis_exp_101(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-101: IdeaGraph vs Direct LLM vs CoI-Agent -- Pairwise ELO."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    elo_summary = _load_source_elo_summary(run_dir)
    if not elo_summary:
        logger.warning("EXP-101: No pairwise ELO data found")
        return all_paths

    # Load raw ELO data for strip overlay
    elo_by_source = load_pairwise_elo_by_source(run_dir)

    sources = sorted(elo_summary.keys())
    display_metrics = METRICS + ["overall"]

    # ------------------------------------------------------------------
    # Fig 1: Grouped bar chart -- ELO by metric, one bar per method
    # ------------------------------------------------------------------
    fig1, ax1 = plt.subplots(figsize=FIG_DOUBLE)
    n_metrics = len(display_metrics)
    n_sources = len(sources)
    bar_width = 0.8 / max(n_sources, 1)
    x_base = np.arange(n_metrics)

    for s_idx, source in enumerate(sources):
        means = []
        errs = []
        for m in display_metrics:
            m_mean, m_sem = elo_summary[source].get(m, (1000.0, 0.0))
            means.append(m_mean)
            errs.append(m_sem)
        offset = (s_idx - (n_sources - 1) / 2) * bar_width
        ax1.bar(
            x_base + offset, means, bar_width * 0.88,
            yerr=errs, capsize=2,
            color=color_for(source), alpha=0.85,
            label=display_name(source),
            error_kw={"linewidth": 0.8, "capthick": 0.8},
        )

        # Overlay individual ELO values as strip dots
        src_color = color_for(source)
        for m_idx, m in enumerate(display_metrics):
            raw_elos = elo_by_source.get(source, {}).get(m, [])
            if raw_elos:
                overlay_strip(
                    ax1, x_base[m_idx] + offset, raw_elos, src_color,
                    width=bar_width * 0.3, size=12, alpha=0.45,
                    seed=42 + s_idx * 100 + m_idx,
                )

    # Annotate sample size
    _n_papers = 0
    for source in sources:
        for m in display_metrics:
            vals = elo_by_source.get(source, {}).get(m, [])
            if vals:
                _n_papers = len(vals)
                break
        if _n_papers:
            break
    if _n_papers:
        annotate_n_header(ax1, _n_papers)

    # Zoom Y axis to data range
    all_means = [
        elo_summary[s].get(m, (1000, 0))[0]
        for s in sources for m in display_metrics
    ]
    all_sems = [
        elo_summary[s].get(m, (1000, 0))[1]
        for s in sources for m in display_metrics
    ]
    y_min = min(m - e for m, e in zip(all_means, all_sems)) - 30
    y_max = max(m + e for m, e in zip(all_means, all_sems)) + 30
    ax1.set_ylim(y_min, y_max)

    # Baseline at ELO=1000
    ax1.axhline(1000, color="gray", linestyle="--", linewidth=0.7, alpha=0.5)

    ax1.set_xticks(x_base)
    ax1.set_xticklabels(
        [METRIC_DISPLAY.get(m, m.capitalize()) for m in display_metrics],
        fontsize=8,
    )
    ax1.set_ylabel("ELO Rating", fontsize=9)
    ax1.tick_params(axis="y", labelsize=8)
    ax1.legend(fontsize=8, loc="upper right")
    ax1.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig1.tight_layout()
    all_paths.extend(save_figure(fig1, figures_dir, f"fig_{exp_id}_1_elo_comparison"))
    plt.close(fig1)

    # ------------------------------------------------------------------
    # Fig 2: Win rate horizontal bar chart
    # ------------------------------------------------------------------
    pairwise_dir = run_dir / "evaluations" / "pairwise"
    if pairwise_dir.exists():
        source_wins: dict[str, int] = {}
        total_papers = 0
        for f in sorted(pairwise_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ranking = data.get("ranking", [])
                if ranking:
                    winner = str(ranking[0].get("source", "unknown"))
                    source_wins[winner] = source_wins.get(winner, 0) + 1
                    total_papers += 1
            except Exception:
                continue

        if source_wins and total_papers > 0:
            fig2, ax2 = plt.subplots(figsize=FIG_SINGLE)

            # Sort by win rate descending
            sorted_sources = sorted(
                source_wins.keys(),
                key=lambda s: source_wins.get(s, 0),
                reverse=True,
            )
            win_pcts = [source_wins.get(s, 0) / total_papers * 100 for s in sorted_sources]
            bar_colors = [color_for(s) for s in sorted_sources]
            bar_labels = [display_name(s) for s in sorted_sources]

            bars = ax2.barh(
                range(len(bar_labels)), win_pcts,
                color=bar_colors, alpha=0.85,
                edgecolor="white", linewidth=0.5,
                height=0.6,
            )

            # Value labels on bars
            for bar, pct in zip(bars, win_pcts):
                ax2.text(
                    bar.get_width() + 1.0,
                    bar.get_y() + bar.get_height() / 2,
                    f"{pct:.0f}%",
                    ha="left", va="center", fontsize=8, fontweight="bold",
                )

            ax2.set_yticks(range(len(bar_labels)))
            ax2.set_yticklabels(bar_labels, fontsize=8)
            ax2.set_xlabel("Win Rate (%)", fontsize=9)
            ax2.tick_params(axis="x", labelsize=8)
            ax2.set_xlim(0, max(win_pcts) * 1.2)
            ax2.invert_yaxis()
            ax2.grid(axis="x", alpha=0.3, linewidth=0.5)
            annotate_n_header(ax2, total_papers)
            fig2.tight_layout()
            all_paths.extend(save_figure(fig2, figures_dir, f"fig_{exp_id}_2_win_rate"))
            plt.close(fig2)

    # ------------------------------------------------------------------
    # Fig 3: ELO heatmap (rows=methods, cols=metrics)
    # ------------------------------------------------------------------
    fig3, ax3 = plt.subplots(figsize=FIG_DOUBLE_WIDE)

    col_labels = [METRIC_DISPLAY.get(m, m.capitalize()) for m in display_metrics]
    row_labels = [display_name(s) for s in sources]

    matrix = []
    for source in sources:
        row = [elo_summary[source].get(m, (1000, 0))[0] for m in display_metrics]
        matrix.append(row)
    arr = np.array(matrix)

    im = ax3.imshow(
        arr, cmap="RdYlGn", aspect="auto",
        vmin=arr.min() - 10, vmax=arr.max() + 10,
    )

    ax3.set_xticks(range(len(col_labels)))
    ax3.set_xticklabels(col_labels, fontsize=8)
    ax3.set_yticks(range(len(row_labels)))
    ax3.set_yticklabels(row_labels, fontsize=8)

    # Cell values as integers
    for i in range(len(sources)):
        for j in range(len(display_metrics)):
            val = arr[i, j]
            ax3.text(
                j, i, f"{val:.0f}",
                ha="center", va="center", fontsize=8, fontweight="bold",
            )

    # Green border around best value per column
    for j in range(arr.shape[1]):
        best_i = int(np.argmax(arr[:, j]))
        ax3.add_patch(plt.Rectangle(
            (j - 0.5, best_i - 0.5), 1, 1,
            fill=False, edgecolor=TOL_GREEN, linewidth=2.5,
        ))

    fig3.colorbar(im, ax=ax3, label="ELO Rating", shrink=0.8)
    if _n_papers:
        annotate_n_header(ax3, _n_papers)
    fig3.tight_layout()
    all_paths.extend(save_figure(fig3, figures_dir, f"fig_{exp_id}_3_elo_heatmap"))
    plt.close(fig3)

    # ------------------------------------------------------------------
    # Fig 4: Radar / spider chart (5 metric axes, one line per method)
    # ------------------------------------------------------------------
    n_metrics = len(METRICS)
    angles = [i / n_metrics * 2 * np.pi for i in range(n_metrics)]
    angles += angles[:1]  # close polygon

    fig4, ax4 = plt.subplots(
        figsize=FIG_SINGLE_TALL, subplot_kw={"polar": True},
    )
    ax4.set_theta_offset(np.pi / 2)   # 0° を上（12時）に
    ax4.set_theta_direction(-1)        # 時計回り

    for source in sources:
        values = [elo_summary[source].get(m, (1000, 0))[0] for m in METRICS]
        values += values[:1]
        c = color_for(source)
        ax4.plot(
            angles, values, "o-",
            linewidth=1.8, label=display_name(source),
            color=c, markersize=4,
        )
        ax4.fill(angles, values, alpha=0.12, color=c)

    ax4.set_xticks(angles[:-1])
    ax4.set_xticklabels(
        [METRIC_DISPLAY.get(m, m) for m in METRICS], fontsize=8,
    )

    # Tighten radial limits to data range
    radar_vals = [
        elo_summary[s].get(m, (1000, 0))[0]
        for s in sources for m in METRICS
    ]
    if radar_vals:
        ax4.set_ylim(min(radar_vals) - 30, max(radar_vals) + 30)

    ax4.tick_params(axis="y", labelsize=7)
    if _n_papers:
        annotate_n_header(ax4, _n_papers)
    ax4.legend(
        fontsize=8, loc="upper right",
        bbox_to_anchor=(1.30, 1.08), framealpha=0.9,
    )
    fig4.tight_layout()
    all_paths.extend(save_figure(fig4, figures_dir, f"fig_{exp_id}_4_radar"))
    plt.close(fig4)

    # ------------------------------------------------------------------
    # Tables: Markdown + LaTeX (ELO +/- SEM, bold best per column)
    # ------------------------------------------------------------------
    _generate_exp101_tables(elo_summary, sources, figures_dir, exp_id)

    return all_paths


# ======================================================================
# EXP-102: Generated Ideas vs Original Paper (Pairwise ELO)
# ======================================================================


@register("EXP-102")
def vis_exp_102(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-102: IdeaGraph ideas vs Target Paper -- radar + ELO ranking."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    elo_summary = _load_source_elo_summary(run_dir)
    if not elo_summary:
        logger.warning("EXP-102: No pairwise ELO data found")
        return all_paths

    # Load raw ELO data for strip overlay and sample count
    elo_by_source = load_pairwise_elo_by_source(run_dir)

    # Determine paper count from raw data
    _n_papers_102 = 0
    for source in sorted(elo_summary.keys()):
        for m in METRICS + ["overall"]:
            vals = elo_by_source.get(source, {}).get(m, [])
            if vals:
                _n_papers_102 = len(vals)
                break
        if _n_papers_102:
            break

    sources = sorted(elo_summary.keys())

    # ------------------------------------------------------------------
    # Fig 1: Radar / spider chart (5 metric axes)
    # ------------------------------------------------------------------
    fig1, ax1 = plt.subplots(
        figsize=FIG_SINGLE_TALL, subplot_kw={"polar": True},
    )
    ax1.set_theta_offset(np.pi / 2)   # 0° を上（12時）に
    ax1.set_theta_direction(-1)        # 時計回り

    n_metrics = len(METRICS)
    angles = [i / n_metrics * 2 * np.pi for i in range(n_metrics)]
    angles += angles[:1]  # close polygon

    for source in sources:
        values = [elo_summary[source].get(m, (1000, 0))[0] for m in METRICS]
        values += values[:1]
        c = color_for(source)
        ax1.plot(
            angles, values, "o-",
            linewidth=1.5, label=display_name(source),
            color=c, markersize=4,
        )
        ax1.fill(angles, values, alpha=0.12, color=c)

    ax1.set_xticks(angles[:-1])
    ax1.set_xticklabels(
        [METRIC_DISPLAY.get(m, m.capitalize()) for m in METRICS],
        fontsize=8, fontweight="bold",
    )

    # Adjust radial range to data
    all_vals = [
        elo_summary[s].get(m, (1000, 0))[0]
        for s in sources for m in METRICS
    ]
    if all_vals:
        r_min = min(all_vals) - 30
        r_max = max(all_vals) + 30
        ax1.set_ylim(r_min, r_max)

    ax1.tick_params(axis="y", labelsize=7)
    if _n_papers_102:
        annotate_n_header(ax1, _n_papers_102)
    ax1.legend(
        fontsize=8, loc="upper right",
        bbox_to_anchor=(1.25, 1.05),
    )
    fig1.tight_layout()
    all_paths.extend(save_figure(fig1, figures_dir, f"fig_{exp_id}_1_radar"))
    plt.close(fig1)

    # ------------------------------------------------------------------
    # Fig 2: Horizontal bar chart sorted by overall ELO
    # ------------------------------------------------------------------
    fig2, ax2 = plt.subplots(figsize=FIG_SINGLE)

    overall_elos = [
        (s, elo_summary[s].get("overall", (1000.0, 0.0)))
        for s in sources
    ]
    overall_elos.sort(key=lambda x: x[1][0], reverse=True)

    bar_labels = [display_name(s) for s, _ in overall_elos]
    bar_vals = [v[0] for _, v in overall_elos]
    bar_sems = [v[1] for _, v in overall_elos]
    bar_colors = []
    for s, _ in overall_elos:
        if "target" in s.lower() or "paper" in s.lower():
            bar_colors.append(TOL_YELLOW)
        else:
            bar_colors.append(color_for(s))

    bars = ax2.barh(
        range(len(bar_labels)), bar_vals,
        xerr=bar_sems, capsize=3,
        color=bar_colors, alpha=0.85,
        edgecolor="white", linewidth=0.5,
        height=0.55,
        error_kw={"linewidth": 0.8, "capthick": 0.8},
    )

    # Overlay individual overall ELO values as horizontal strip dots
    for bar_idx, (source, _) in enumerate(overall_elos):
        raw_overall = elo_by_source.get(source, {}).get("overall", [])
        if raw_overall:
            rng = np.random.default_rng(42 + bar_idx)
            jitter = rng.uniform(-0.12, 0.12, size=len(raw_overall))
            ax2.scatter(
                raw_overall,
                [bar_idx + j for j in jitter],
                s=12, alpha=0.45,
                color=bar_colors[bar_idx],
                edgecolors="white", linewidth=0.3, zorder=4,
            )

    ax2.set_yticks(range(len(bar_labels)))
    ax2.set_yticklabels(bar_labels, fontsize=8)
    ax2.set_xlabel("Overall ELO Rating", fontsize=9)
    ax2.tick_params(axis="x", labelsize=8)

    # Baseline line
    ax2.axvline(1000, color="gray", linestyle="--", linewidth=0.7, alpha=0.5)

    # Zoom x-axis to data range
    x_min = min(v - e for v, e in zip(bar_vals, bar_sems)) - 30
    x_max = max(v + e for v, e in zip(bar_vals, bar_sems)) + 30
    ax2.set_xlim(x_min, x_max)

    # Value labels
    for bar, val in zip(bars, bar_vals):
        ax2.text(
            val + (x_max - x_min) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{val:.0f}",
            va="center", fontsize=8, fontweight="bold",
        )

    ax2.invert_yaxis()
    ax2.grid(axis="x", alpha=0.3, linewidth=0.5)
    if _n_papers_102:
        annotate_n_header(ax2, _n_papers_102)
    fig2.tight_layout()
    all_paths.extend(save_figure(fig2, figures_dir, f"fig_{exp_id}_2_elo_ranking"))
    plt.close(fig2)

    # ------------------------------------------------------------------
    # Tables: Markdown + LaTeX
    # ------------------------------------------------------------------
    _generate_exp102_tables(elo_summary, sources, figures_dir, exp_id)

    return all_paths


# ======================================================================
# EXP-103..106: Single evaluation scores (one per method)
# ======================================================================


@register("EXP-103")
def vis_exp_103(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-103: IdeaGraph single evaluation scores."""
    return _single_score_bar(run_dir, figures_dir, exp_id, "ideagraph")


@register("EXP-104")
def vis_exp_104(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-104: Direct LLM single evaluation scores."""
    return _single_score_bar(run_dir, figures_dir, exp_id, "direct_llm")


@register("EXP-105")
def vis_exp_105(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-105: CoI-Agent single evaluation scores."""
    return _single_score_bar(run_dir, figures_dir, exp_id, "coi")


@register("EXP-106")
def vis_exp_106(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-106: Target Paper single evaluation scores."""
    return _single_score_bar(run_dir, figures_dir, exp_id, "target_paper")


# ======================================================================
# Table generation -- EXP-101
# ======================================================================


def _generate_exp101_tables(
    elo_summary: dict[str, dict[str, tuple[float, float]]],
    sources: list[str],
    output_dir: Path,
    exp_id: str,
) -> None:
    """Generate Markdown + LaTeX tables for EXP-101 (ELO +/- SEM, bold best)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    display_metrics = METRICS + ["overall"]

    # Identify best (highest mean) per metric
    best_per_metric: dict[str, float] = {}
    for m in display_metrics:
        vals = [elo_summary[s].get(m, (0, 0))[0] for s in sources]
        best_per_metric[m] = max(vals) if vals else 0.0

    # --- Markdown ---
    header_cols = [METRIC_DISPLAY.get(m, m) for m in display_metrics]
    md_header = "| Method | " + " | ".join(header_cols) + " |"
    md_sep = "|--------|" + "|".join("---------:" for _ in display_metrics) + "|"
    md_rows: list[str] = []
    for s in sources:
        name = display_name(s)
        cells: list[str] = []
        for m in display_metrics:
            mean, sem = elo_summary[s].get(m, (0, 0))
            val_str = f"{mean:.0f} \u00b1 {sem:.0f}"
            if mean == best_per_metric[m]:
                val_str = f"**{val_str}**"
            cells.append(val_str)
        md_rows.append(f"| {name} | " + " | ".join(cells) + " |")

    md_content = (
        f"## {exp_id}: 3-Method ELO Comparison\n\n"
        + md_header + "\n" + md_sep + "\n"
        + "\n".join(md_rows) + "\n"
    )
    (output_dir / f"table_{exp_id}.md").write_text(md_content, encoding="utf-8")

    # --- LaTeX ---
    col_spec = "l" + "r" * len(display_metrics)
    tex_header = (
        " & ".join(["Method"] + [METRIC_DISPLAY.get(m, m) for m in display_metrics])
        + r" \\"
    )
    tex_rows: list[str] = []
    for s in sources:
        name = display_name(s)
        cells: list[str] = []
        for m in display_metrics:
            mean, sem = elo_summary[s].get(m, (0, 0))
            if mean == best_per_metric[m]:
                cells.append(
                    f"\\textbf{{{mean:.0f}}} $\\pm$ {sem:.0f}"
                )
            else:
                cells.append(f"{mean:.0f} $\\pm$ {sem:.0f}")
        tex_rows.append(f"  {name} & " + " & ".join(cells) + r" \\")

    tex = (
        r"\begin{table}[htbp]" + "\n"
        r"  \centering" + "\n"
        f"  \\caption{{{exp_id}: 3-Method ELO Comparison (Mean $\\pm$ SEM)}}\n"
        f"  \\begin{{tabular}}{{{col_spec}}}\n"
        r"    \toprule" + "\n"
        f"    {tex_header}\n"
        r"    \midrule" + "\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        r"    \bottomrule" + "\n"
        r"  \end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")


# ======================================================================
# Table generation -- EXP-102
# ======================================================================


def _generate_exp102_tables(
    elo_summary: dict[str, dict[str, tuple[float, float]]],
    sources: list[str],
    output_dir: Path,
    exp_id: str,
) -> None:
    """Generate Markdown + LaTeX tables for EXP-102 (ELO +/- SEM, bold best)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    display_metrics = METRICS + ["overall"]

    # Identify best per metric
    best_per_metric: dict[str, float] = {}
    for m in display_metrics:
        vals = [elo_summary[s].get(m, (0, 0))[0] for s in sources]
        best_per_metric[m] = max(vals) if vals else 0.0

    # --- Markdown ---
    header_cols = [METRIC_DISPLAY.get(m, m) for m in display_metrics]
    md_header = "| Source | " + " | ".join(header_cols) + " |"
    md_sep = "|--------|" + "|".join("---------:" for _ in display_metrics) + "|"
    md_rows: list[str] = []
    for s in sources:
        name = display_name(s)
        cells: list[str] = []
        for m in display_metrics:
            mean, sem = elo_summary[s].get(m, (0, 0))
            val_str = f"{mean:.0f} \u00b1 {sem:.0f}"
            if mean == best_per_metric[m]:
                val_str = f"**{val_str}**"
            cells.append(val_str)
        md_rows.append(f"| {name} | " + " | ".join(cells) + " |")

    md_content = (
        f"## {exp_id}: IdeaGraph vs Target Paper\n\n"
        + md_header + "\n" + md_sep + "\n"
        + "\n".join(md_rows) + "\n"
    )
    (output_dir / f"table_{exp_id}.md").write_text(md_content, encoding="utf-8")

    # --- LaTeX ---
    col_spec = "l" + "r" * len(display_metrics)
    tex_header = (
        " & ".join(["Source"] + [METRIC_DISPLAY.get(m, m) for m in display_metrics])
        + r" \\"
    )
    tex_rows: list[str] = []
    for s in sources:
        name = display_name(s)
        cells: list[str] = []
        for m in display_metrics:
            mean, sem = elo_summary[s].get(m, (0, 0))
            if mean == best_per_metric[m]:
                cells.append(
                    f"\\textbf{{{mean:.0f}}} $\\pm$ {sem:.0f}"
                )
            else:
                cells.append(f"{mean:.0f} $\\pm$ {sem:.0f}")
        tex_rows.append(f"  {name} & " + " & ".join(cells) + r" \\")

    tex = (
        r"\begin{table}[htbp]" + "\n"
        r"  \centering" + "\n"
        f"  \\caption{{{exp_id}: IdeaGraph vs Target Paper (Mean $\\pm$ SEM)}}\n"
        f"  \\begin{{tabular}}{{{col_spec}}}\n"
        r"    \toprule" + "\n"
        f"    {tex_header}\n"
        r"    \midrule" + "\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        r"    \bottomrule" + "\n"
        r"  \end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")
