"""200-series: Ablation experiment visualizations (EXP-201 to EXP-208).

EXP-201: Multi-hop depth ablation
EXP-202: Graph format ablation (mermaid vs paths)
EXP-203: Prompt scope ablation (path, k_hop, path_plus_k_hop)
EXP-204: Max paths ablation (3, 5, 10, 20)
EXP-205: Graph size effect
EXP-206: Proposal count ablation
EXP-207: Quality-cost tradeoff (Pareto frontier)
EXP-208: Connectivity stability (degree-score correlation)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._registry import register
from ._style import (
    HAS_MPL,
    METRICS,
    METRIC_SHORT,
    METRIC_DISPLAY,
    METRIC_COLORS,
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
    SINGLE_COL,
    DOUBLE_COL,
    color_for,
    display_name,
    clean_condition,
    p_stars,
    safe_mean,
    safe_std,
    safe_sem,
    save_figure,
    logger,
    PALETTE,
)
from ._loaders import (
    load_single_scores,
    load_single_scores_per_paper,
    load_experiment_meta,
    load_paper_degrees,
)

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# ======================================================================
# Shared helpers
# ======================================================================


def _extract_sweep(
    conditions: list[str],
) -> tuple[list[float], list[str]] | None:
    """Extract numeric parameters from condition names and return sorted.

    Returns (x_values, sorted_conditions) or None if fewer than 2 numeric
    conditions are found.
    """
    values: list[tuple[float, str]] = []
    for cond in conditions:
        nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
        if nums:
            values.append((float(nums[-1]), cond))
    if len(values) < 2:
        return None
    values.sort(key=lambda x: x[0])
    return [v[0] for v in values], [v[1] for v in values]


def _sweep_figures(
    run_dir: Path,
    figures_dir: Path,
    exp_id: str,
    xlabel: str,
) -> list[Path]:
    """Generic sweep visualizer producing multi-line plot + heatmap + tables.

    Used by EXP-201, EXP-204, EXP-205.
    """
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    sweep = _extract_sweep(conditions)
    if not sweep:
        logger.warning(
            "%s: Could not detect parameter sweep in condition names", exp_id,
        )
        return all_paths
    x_values, sorted_conds = sweep

    # -- Fig 1: Multi-line sweep (one line per metric) --
    fig1, ax1 = plt.subplots(figsize=FIG_DOUBLE)
    all_metrics = METRICS + ["overall"]

    for metric in all_metrics:
        means = [safe_mean(scores[c].get(metric, [])) for c in sorted_conds]
        sems = [safe_sem(scores[c].get(metric, [])) for c in sorted_conds]
        x_arr = np.array(x_values[: len(means)])
        m_arr = np.array(means)
        s_arr = np.array(sems)

        color = METRIC_COLORS.get(metric, TOL_GREY)
        label = METRIC_DISPLAY.get(metric, metric.capitalize())
        lw = 2.5 if metric == "overall" else 1.5
        ls = "-" if metric == "overall" else "--"

        ax1.plot(
            x_arr, m_arr, marker="o", linestyle=ls, color=color,
            linewidth=lw, label=label, markersize=5,
        )
        if len(x_arr) > 1:
            ax1.fill_between(
                x_arr, m_arr - s_arr, m_arr + s_arr,
                alpha=0.12, color=color,
            )

        # Star on optimal point (overall only)
        if metric == "overall" and len(m_arr) > 0:
            best_idx = int(np.argmax(m_arr))
            ax1.plot(
                x_arr[best_idx], m_arr[best_idx], "*",
                color=color, markersize=14, zorder=5,
            )

    ax1.set_xlabel(xlabel, fontsize=9)
    ax1.set_ylabel("Score (1\u201310)", fontsize=9)
    ax1.tick_params(axis="both", labelsize=8)
    ax1.legend(fontsize=8, ncol=2)
    ax1.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig1.tight_layout()
    all_paths.extend(save_figure(fig1, figures_dir, f"fig_{exp_id}_1_sweep"))
    plt.close(fig1)

    # -- Fig 2: Heatmap (parameter x metrics) --
    fig2, ax2 = plt.subplots(figsize=FIG_DOUBLE_WIDE)
    data = []
    for cond in sorted_conds:
        row = [safe_mean(scores[cond].get(m, [])) for m in METRICS]
        data.append(row)
    arr = np.array(data)
    col_labels = [METRIC_DISPLAY.get(m, m) for m in METRICS]
    row_labels = [
        str(int(x)) if x == int(x) else f"{x:.1f}" for x in x_values
    ]

    im = ax2.imshow(arr, cmap="YlOrRd", aspect="auto")
    ax2.set_xticks(range(len(col_labels)))
    ax2.set_xticklabels(col_labels, fontsize=8)
    ax2.set_yticks(range(len(row_labels)))
    ax2.set_yticklabels(row_labels, fontsize=8)

    # Cell value annotations
    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            ax2.text(
                j, i, f"{arr[i, j]:.1f}",
                ha="center", va="center", fontsize=8, fontweight="bold",
            )

    # Green border around column-best
    for j in range(arr.shape[1]):
        best_i = int(np.argmax(arr[:, j]))
        ax2.add_patch(plt.Rectangle(
            (j - 0.5, best_i - 0.5), 1, 1,
            fill=False, edgecolor=TOL_GREEN, linewidth=2.5,
        ))

    fig2.colorbar(im, ax=ax2, label="Score", shrink=0.8)
    ax2.set_xlabel("Metric", fontsize=9)
    ax2.set_ylabel(xlabel, fontsize=9)
    ax2.tick_params(axis="both", labelsize=8)
    fig2.tight_layout()
    all_paths.extend(save_figure(fig2, figures_dir, f"fig_{exp_id}_2_heatmap"))
    plt.close(fig2)

    # -- Tables (Markdown + LaTeX) --
    _generate_sweep_tables(
        sorted_conds, x_values, scores, figures_dir, exp_id, xlabel,
    )

    return all_paths


def _grouped_bar_figure(
    run_dir: Path,
    figures_dir: Path,
    exp_id: str,
    figsize: tuple[float, float] | None = None,
) -> list[Path]:
    """Generic grouped bar chart for categorical (non-numeric) conditions.

    Used by EXP-202, EXP-203.
    """
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if len(conditions) < 2:
        return all_paths

    size = figsize or FIG_DOUBLE

    fig, ax = plt.subplots(figsize=size)
    n_metrics = len(METRICS)
    n_conds = len(conditions)
    bar_width = 0.8 / max(n_conds, 1)
    x_base = np.arange(n_metrics)

    for c_idx, cond in enumerate(conditions):
        means = [safe_mean(scores[cond].get(m, [])) for m in METRICS]
        sems = [safe_sem(scores[cond].get(m, [])) for m in METRICS]
        offset = (c_idx - (n_conds - 1) / 2) * bar_width
        color = PALETTE[c_idx % len(PALETTE)]
        ax.bar(
            x_base + offset, means, bar_width * 0.88,
            yerr=sems, capsize=3, color=color, alpha=0.85,
            label=clean_condition(cond), error_kw={"linewidth": 1},
        )

    ax.set_xticks(x_base)
    ax.set_xticklabels(
        [METRIC_DISPLAY.get(m, m) for m in METRICS], fontsize=8,
    )
    ax.set_ylabel("Score (1\u201310)", fontsize=9)
    ax.tick_params(axis="both", labelsize=8)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig.tight_layout()
    all_paths.extend(
        save_figure(fig, figures_dir, f"fig_{exp_id}_1_grouped_bar"),
    )
    plt.close(fig)

    return all_paths


# ======================================================================
# Table generation
# ======================================================================


def _generate_sweep_tables(
    sorted_conds: list[str],
    x_values: list[float],
    scores: dict[str, dict[str, list[float]]],
    output_dir: Path,
    exp_id: str,
    xlabel: str,
) -> None:
    """Generate Markdown and LaTeX tables for parameter sweep experiments.

    LaTeX uses booktabs and bolds best value per column.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    display_metrics = METRICS + ["overall"]

    # Compute mean scores per condition/metric
    mean_grid: list[list[float]] = []
    for cond in sorted_conds:
        row = [safe_mean(scores[cond].get(m, [])) for m in display_metrics]
        mean_grid.append(row)

    # Identify column-best indices
    best_per_col: list[int] = []
    for j in range(len(display_metrics)):
        col_vals = [mean_grid[i][j] for i in range(len(sorted_conds))]
        best_per_col.append(
            int(max(range(len(col_vals)), key=lambda k: col_vals[k]))
            if col_vals else 0
        )

    # -- Markdown --
    header = (
        f"| {xlabel} | "
        + " | ".join(METRIC_SHORT.get(m, m) for m in display_metrics)
        + " |"
    )
    sep = "|-------:|" + "|".join("--------:" for _ in display_metrics) + "|"
    rows: list[str] = []
    for i, (x, cond) in enumerate(zip(x_values, sorted_conds)):
        x_label = str(int(x)) if x == int(x) else f"{x:.1f}"
        cells: list[str] = []
        for j, m in enumerate(display_metrics):
            val = mean_grid[i][j]
            cell = f"{val:.2f}"
            if i == best_per_col[j]:
                cell = f"**{cell}**"
            cells.append(cell)
        rows.append(f"| {x_label} | " + " | ".join(cells) + " |")

    md = (
        f"## {exp_id}: {xlabel} Ablation\n\n"
        f"{header}\n{sep}\n" + "\n".join(rows) + "\n"
    )
    (output_dir / f"table_{exp_id}.md").write_text(md, encoding="utf-8")

    # -- LaTeX (booktabs, bold best) --
    col_spec = "r" + "r" * len(display_metrics)
    header_tex = (
        " & ".join(
            [xlabel] + [METRIC_SHORT.get(m, m) for m in display_metrics]
        )
        + r" \\"
    )
    tex_rows: list[str] = []
    for i, (x, cond) in enumerate(zip(x_values, sorted_conds)):
        x_label = str(int(x)) if x == int(x) else f"{x:.1f}"
        cells: list[str] = []
        for j, m in enumerate(display_metrics):
            val = mean_grid[i][j]
            cell = f"{val:.2f}"
            if i == best_per_col[j]:
                cell = rf"\textbf{{{cell}}}"
            cells.append(cell)
        tex_rows.append(f"  {x_label} & " + " & ".join(cells) + r" \\")

    tex = (
        r"\begin{table}[htbp]" + "\n"
        r"  \centering" + "\n"
        f"  \\caption{{{exp_id}: {xlabel} Ablation Results}}\n"
        f"  \\begin{{tabular}}{{{col_spec}}}\n"
        r"    \toprule" + "\n"
        f"    {header_tex}\n"
        r"    \midrule" + "\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        r"    \bottomrule" + "\n"
        r"  \end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")


def _generate_correlation_tables(
    all_metric_pairs: dict[str, tuple[list[float], list[float]]],
    plot_metrics: list[str],
    output_dir: Path,
    exp_id: str,
    spearman_fn,
    pearson_fn,
) -> None:
    """Generate correlation summary tables for EXP-208."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # -- Markdown --
    header = "| Metric | Spearman rho | Pearson r | n |"
    sep = "|--------|----------:|----------:|--:|"
    rows: list[str] = []
    for m in plot_metrics:
        dx, dy = all_metric_pairs[m]
        if len(dx) >= 3:
            rho = spearman_fn(dx, dy)
            r = pearson_fn(dx, dy)
            rows.append(
                f"| {METRIC_SHORT.get(m, m)} | {rho:.3f} | {r:.3f} | {len(dx)} |"
            )

    if rows:
        md = (
            f"## {exp_id}: Degree-Score Correlations\n\n"
            f"{header}\n{sep}\n" + "\n".join(rows) + "\n"
        )
        (output_dir / f"table_{exp_id}.md").write_text(md, encoding="utf-8")

    # -- LaTeX --
    if rows:
        tex_rows: list[str] = []
        for m in plot_metrics:
            dx, dy = all_metric_pairs[m]
            if len(dx) >= 3:
                rho = spearman_fn(dx, dy)
                r = pearson_fn(dx, dy)
                tex_rows.append(
                    f"  {METRIC_SHORT.get(m, m)} & {rho:.3f} & {r:.3f} & {len(dx)}"
                    + r" \\"
                )

        tex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            f"  \\caption{{{exp_id}: Degree-Score Correlations}}\n"
            r"  \begin{tabular}{lrrr}" + "\n"
            r"    \toprule" + "\n"
            r"    Metric & Spearman $\rho$ & Pearson $r$ & $n$ \\" + "\n"
            r"    \midrule" + "\n"
            + "\n".join(f"    {r}" for r in tex_rows) + "\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )
        (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")


# ======================================================================
# EXP-201: Multi-hop Depth Ablation
# Conditions: hops_1, hops_2, hops_3, hops_4, hops_5
# ======================================================================


@register("EXP-201")
def vis_exp_201(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Multi-hop depth ablation: sweep + heatmap + tables."""
    if not HAS_MPL:
        return []
    return _sweep_figures(run_dir, figures_dir, exp_id, xlabel="Max Hops")


# ======================================================================
# EXP-202: Graph Format (mermaid vs paths)
# ======================================================================


@register("EXP-202")
def vis_exp_202(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Graph format comparison: grouped bar."""
    if not HAS_MPL:
        return []
    return _grouped_bar_figure(
        run_dir, figures_dir, exp_id, figsize=FIG_SINGLE,
    )


# ======================================================================
# EXP-203: Prompt Scope (path, k_hop, path_plus_k_hop)
# ======================================================================


@register("EXP-203")
def vis_exp_203(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Prompt scope comparison: grouped bar."""
    if not HAS_MPL:
        return []
    return _grouped_bar_figure(
        run_dir, figures_dir, exp_id, figsize=FIG_DOUBLE,
    )


# ======================================================================
# EXP-204: Max Paths (3, 5, 10, 20)
# ======================================================================


@register("EXP-204")
def vis_exp_204(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Max paths ablation: sweep + heatmap + tables."""
    if not HAS_MPL:
        return []
    return _sweep_figures(run_dir, figures_dir, exp_id, xlabel="Max Paths")


# ======================================================================
# EXP-205: Graph Size Effect
# ======================================================================


@register("EXP-205")
def vis_exp_205(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Graph size ablation: sweep + heatmap + tables."""
    if not HAS_MPL:
        return []
    return _sweep_figures(
        run_dir, figures_dir, exp_id, xlabel="Graph Size Limit",
    )


# ======================================================================
# EXP-206: Proposal Count Ablation
# Conditions: proposals_1, proposals_3, proposals_5, proposals_7, proposals_10
# ======================================================================


@register("EXP-206")
def vis_exp_206(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Proposal count ablation: dual-line (mean overall + best-of-N)."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    sweep = _extract_sweep(conditions)
    if not sweep:
        return _grouped_bar_figure(run_dir, figures_dir, exp_id)
    x_values, sorted_conds = sweep

    # Mean overall per condition
    mean_overall = [
        safe_mean(scores[c].get("overall", [])) for c in sorted_conds
    ]
    mean_sem = [
        safe_sem(scores[c].get("overall", [])) for c in sorted_conds
    ]

    # Best-of-N: per paper, take the max overall across proposals
    per_paper = load_single_scores_per_paper(run_dir)
    best_of_n: list[float] = []
    best_sem_list: list[float] = []
    for cond in sorted_conds:
        papers = per_paper.get(cond, {})
        if papers:
            bests = [p.get("overall", 0.0) for p in papers.values()]
            best_of_n.append(max(bests) if bests else 0.0)
            best_sem_list.append(safe_sem(bests))
        else:
            best_of_n.append(0.0)
            best_sem_list.append(0.0)

    x_arr = np.array(x_values)
    mean_arr = np.array(mean_overall)
    mean_sem_arr = np.array(mean_sem)
    best_arr = np.array(best_of_n)
    best_sem_arr = np.array(best_sem_list)

    fig, ax = plt.subplots(figsize=FIG_DOUBLE)

    # Line 1: Mean Overall (blue, solid circles)
    ax.plot(
        x_arr, mean_arr, "o-", color=TOL_BLUE, linewidth=2.5,
        label="Mean Overall", markersize=6,
    )
    ax.fill_between(
        x_arr, mean_arr - mean_sem_arr, mean_arr + mean_sem_arr,
        alpha=0.12, color=TOL_BLUE,
    )

    # Line 2: Best-of-N (red, dashed squares)
    ax.plot(
        x_arr, best_arr, "s--", color=TOL_RED, linewidth=2.5,
        label="Best-of-N", markersize=6,
    )
    ax.fill_between(
        x_arr, best_arr - best_sem_arr, best_arr + best_sem_arr,
        alpha=0.12, color=TOL_RED,
    )

    # Shaded area between the two lines
    ax.fill_between(
        x_arr, mean_arr, best_arr, alpha=0.08, color=TOL_PURPLE,
    )

    ax.set_xlabel("Num Proposals", fontsize=9)
    ax.set_ylabel("Overall Score (1\u201310)", fontsize=9)
    ax.tick_params(axis="both", labelsize=8)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig.tight_layout()
    all_paths.extend(
        save_figure(fig, figures_dir, f"fig_{exp_id}_1_dual_line"),
    )
    plt.close(fig)

    return all_paths


# ======================================================================
# EXP-207: Quality-Cost Tradeoff (Pareto frontier)
# ======================================================================


@register("EXP-207")
def vis_exp_207(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Quality-cost Pareto frontier scatter."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if not conditions:
        return all_paths

    costs: list[float] = []
    overall_scores: list[float] = []
    labels: list[str] = []
    log_dir = run_dir / "execution_logs"

    for cond in conditions:
        overall_scores.append(safe_mean(scores[cond].get("overall", [])))
        labels.append(clean_condition(cond))

        # Try loading actual cost from execution logs
        cost = 0.0
        log_file = log_dir / f"{cond}.json" if log_dir.exists() else None
        if log_file and log_file.exists():
            try:
                cost = float(
                    json.loads(
                        log_file.read_text(encoding="utf-8")
                    ).get("total_cost_usd", 0)
                )
            except Exception:
                pass

        # Fallback: extract numbers from condition name as cost proxy
        if cost == 0:
            nums = re.findall(r"(\d+)", cond)
            cost = (
                sum(float(n) for n in nums) * 0.001 if nums else 0.01
            )
        costs.append(cost)

    fig, ax = plt.subplots(figsize=FIG_DOUBLE)

    # Scatter points
    ax.scatter(
        costs, overall_scores, s=80, color=TOL_BLUE, zorder=5,
        edgecolors="white", linewidth=0.8,
    )
    for i, label in enumerate(labels):
        ax.annotate(
            label, (costs[i], overall_scores[i]),
            fontsize=7, xytext=(6, 6), textcoords="offset points",
        )

    # Pareto front: walk through sorted-by-cost, keep running max
    paired = sorted(zip(costs, overall_scores), key=lambda p: p[0])
    front_x: list[float] = []
    front_y: list[float] = []
    best = -float("inf")
    for c, s in paired:
        if s >= best:
            front_x.append(c)
            front_y.append(s)
            best = s
    ax.plot(
        front_x, front_y, "--", color=TOL_RED, linewidth=2,
        label="Pareto Front", alpha=0.7,
    )

    ax.set_xlabel("Estimated Cost", fontsize=9)
    ax.set_ylabel("Overall Score", fontsize=9)
    ax.tick_params(axis="both", labelsize=8)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig.tight_layout()
    all_paths.extend(
        save_figure(fig, figures_dir, f"fig_{exp_id}_1_pareto"),
    )
    plt.close(fig)

    return all_paths


# ======================================================================
# EXP-208: Connectivity Stability
# Degree (continuous) vs score scatter + regression + correlation summary
# ======================================================================


@register("EXP-208")
def vis_exp_208(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Connectivity stability: degree-score scatter, per-metric panels, correlation bar."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []

    # Load data
    scores = load_single_scores(run_dir)
    if not scores:
        return all_paths

    degrees = load_paper_degrees(run_dir)
    per_paper = load_single_scores_per_paper(run_dir)

    # Build degree-score pairs across all conditions
    degree_vals: list[float] = []
    overall_vals: list[float] = []
    metric_pairs: dict[str, tuple[list[float], list[float]]] = {
        m: ([], []) for m in METRICS
    }

    for cond, papers in per_paper.items():
        for paper_id, paper_scores in papers.items():
            deg = degrees.get(paper_id)
            if deg is None:
                continue
            overall = paper_scores.get("overall")
            if overall is not None:
                degree_vals.append(float(deg))
                overall_vals.append(float(overall))
            for m in METRICS:
                val = paper_scores.get(m)
                if val is not None:
                    metric_pairs[m][0].append(float(deg))
                    metric_pairs[m][1].append(float(val))

    if not degree_vals:
        logger.warning("EXP-208: No degree-score data available")
        return all_paths

    # Safe import of correlation functions
    try:
        from idea_graph.services.aggregator import spearman, pearson
    except ImportError:
        def spearman(x: list[float], y: list[float]) -> float:
            return 0.0
        def pearson(x: list[float], y: list[float]) -> float:
            return 0.0

    # -- Fig 1: Degree x Overall scatter + regression + 95% CI --
    fig1, ax1 = plt.subplots(figsize=FIG_DOUBLE)
    x_arr = np.array(degree_vals)
    y_arr = np.array(overall_vals)

    ax1.scatter(
        x_arr, y_arr, s=50, alpha=0.7, color=TOL_BLUE,
        edgecolors="white", linewidth=0.6, zorder=3,
    )

    # Regression line + 95% CI band
    if len(x_arr) >= 2 and len(set(x_arr)) >= 2:
        coeffs = np.polyfit(x_arr, y_arr, 1)
        x_line = np.linspace(x_arr.min() - 1, x_arr.max() + 1, 100)
        y_line = np.polyval(coeffs, x_line)
        ax1.plot(
            x_line, y_line, "--", color=TOL_RED, linewidth=2,
            label="Linear Fit",
        )

        y_pred = np.polyval(coeffs, x_arr)
        se = np.std(y_arr - y_pred)
        ax1.fill_between(
            x_line, y_line - 1.96 * se, y_line + 1.96 * se,
            alpha=0.12, color=TOL_RED, label="95% CI",
        )

    # Statistics annotation box
    n = len(degree_vals)
    rho = spearman(degree_vals, overall_vals) if n >= 3 else 0.0
    r = pearson(degree_vals, overall_vals) if n >= 3 else 0.0
    annotation = f"n = {n}"
    if n >= 3:
        annotation += f"\nSpearman \u03c1 = {rho:.3f}\nPearson r = {r:.3f}"
    ax1.text(
        0.05, 0.95, annotation, transform=ax1.transAxes,
        fontsize=8, va="top",
        bbox=dict(
            boxstyle="round,pad=0.4", facecolor="white",
            edgecolor="#D1D5DB", alpha=0.9,
        ),
    )

    ax1.set_xlabel("Degree (number of connections)", fontsize=9)
    ax1.set_ylabel("Overall Score", fontsize=9)
    ax1.tick_params(axis="both", labelsize=8)
    handles, handle_labels = ax1.get_legend_handles_labels()
    if handles:
        ax1.legend(fontsize=8)
    ax1.grid(axis="y", alpha=0.3, linewidth=0.5)
    fig1.tight_layout()
    all_paths.extend(
        save_figure(fig1, figures_dir, f"fig_{exp_id}_1_degree_scatter"),
    )
    plt.close(fig1)

    # -- Fig 2: 2x3 per-metric scatter panels --
    plot_metrics = METRICS + ["overall"]
    all_metric_pairs = {
        **metric_pairs,
        "overall": (degree_vals, overall_vals),
    }

    fig2, axes = plt.subplots(2, 3, figsize=FIG_DOUBLE_TALL)

    for idx, m in enumerate(plot_metrics):
        row, col = idx // 3, idx % 3
        ax = axes[row][col]
        dx, dy = all_metric_pairs[m]
        color = METRIC_COLORS.get(m, TOL_GREY)

        if len(dx) < 1:
            ax.text(
                0.5, 0.5, "No data", transform=ax.transAxes,
                ha="center", va="center", fontsize=8,
            )
            ax.set_title(
                METRIC_DISPLAY.get(m, m.capitalize()), fontsize=9,
            )
            continue

        ax.scatter(
            dx, dy, alpha=0.6, color=color, s=30,
            edgecolors="white", linewidth=0.4,
        )

        # Regression line
        if len(dx) >= 2 and len(set(dx)) >= 2:
            x_a = np.array(dx)
            y_a = np.array(dy)
            c = np.polyfit(x_a, y_a, 1)
            xl = np.linspace(x_a.min(), x_a.max(), 50)
            ax.plot(
                xl, np.polyval(c, xl), "--", color=TOL_RED, linewidth=1.5,
            )

        # rho annotation
        if len(dx) >= 3:
            rho_m = spearman(dx, dy)
            ax.text(
                0.05, 0.95, f"\u03c1 = {rho_m:.3f}",
                transform=ax.transAxes, fontsize=7, va="top",
                bbox=dict(
                    boxstyle="round", facecolor="white",
                    edgecolor="#D1D5DB", alpha=0.9,
                ),
            )

        ax.set_title(METRIC_DISPLAY.get(m, m.capitalize()), fontsize=9)
        ax.set_xlabel("Degree", fontsize=8)
        ax.set_ylabel("Score", fontsize=8)
        ax.tick_params(axis="both", labelsize=7)
        ax.grid(axis="y", alpha=0.3, linewidth=0.5)

    fig2.tight_layout()
    all_paths.extend(
        save_figure(fig2, figures_dir, f"fig_{exp_id}_2_metric_panels"),
    )
    plt.close(fig2)

    # -- Fig 3: |rho| bar chart --
    if any(len(all_metric_pairs[m][0]) >= 3 for m in plot_metrics):
        fig3, ax3 = plt.subplots(figsize=FIG_SINGLE)
        metric_labels: list[str] = []
        rho_values: list[float] = []

        for m in plot_metrics:
            dx, dy = all_metric_pairs[m]
            if len(dx) >= 3:
                rho_m = spearman(dx, dy)
                metric_labels.append(METRIC_SHORT.get(m, m.capitalize()))
                rho_values.append(rho_m)

        if metric_labels:
            colors = [
                TOL_GREEN if abs(v) < 0.3 else TOL_RED for v in rho_values
            ]
            bars = ax3.bar(
                metric_labels, [abs(v) for v in rho_values],
                color=colors, alpha=0.85, edgecolor="white",
            )
            ax3.axhline(
                0.3, color=TOL_GREY, linestyle="--", linewidth=1,
                alpha=0.7, label="|\u03c1| = 0.3",
            )

            ax3.set_ylabel("|Spearman \u03c1|", fontsize=9)
            ax3.tick_params(axis="both", labelsize=8)
            ax3.legend(fontsize=8)
            ax3.grid(axis="y", alpha=0.3, linewidth=0.5)
            ax3.set_ylim(
                0,
                max(abs(v) for v in rho_values) * 1.3
                if rho_values else 1.0,
            )

            # Value labels on bars with +/- sign
            for bar, val in zip(bars, rho_values):
                sign = "+" if val >= 0 else "\u2212"
                ax3.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.02,
                    f"{sign}{abs(val):.3f}",
                    ha="center", va="bottom", fontsize=7, fontweight="bold",
                )

            fig3.tight_layout()
            all_paths.extend(
                save_figure(
                    fig3, figures_dir, f"fig_{exp_id}_3_correlation_bar",
                ),
            )
            plt.close(fig3)

    # -- Tables --
    _generate_correlation_tables(
        all_metric_pairs, plot_metrics, figures_dir, exp_id,
        spearman, pearson,
    )

    return all_paths
