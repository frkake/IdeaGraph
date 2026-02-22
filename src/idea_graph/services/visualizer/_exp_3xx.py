"""300-series: Evaluation validity experiments (EXP-301 through EXP-306).

EXP-301: Pairwise vs Single evaluation consistency
EXP-302: LLM reproducibility (repeat=5)
EXP-303: Position bias measurement
EXP-304: Cross-model evaluation consistency
EXP-305: Human-LLM correlation
EXP-306: Traceability assessment
"""

from __future__ import annotations

import json
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
    TOL_PURPLE,
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
    save_figure,
    logger,
    PALETTE,
)
from ._loaders import (
    load_single_scores,
    load_single_scores_per_paper,
    load_pairwise_details,
    load_pairwise_swap_data,
    load_repeat_scores,
    load_multi_model_scores,
    load_aggregate,
    load_experiment_meta,
)
from ._stats import StatsHelper
from idea_graph.services.aggregator import spearman, pearson

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# =====================================================================
# EXP-301: Pairwise vs Single Evaluation Consistency
# =====================================================================


@register("EXP-301")
def vis_exp_301(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Scatter: single overall score vs pairwise ELO rating with Spearman rho."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []

    per_paper = load_single_scores_per_paper(run_dir)
    pairwise_files = load_pairwise_details(run_dir)

    # Build matched (single_overall, pairwise_elo) pairs
    single_vals: list[float] = []
    pairwise_vals: list[float] = []

    for pw_data in pairwise_files:
        ranking = pw_data.get("ranking", [])
        for entry in ranking:
            source = str(entry.get("source", ""))
            elo = entry.get("elo_rating")
            if elo is None:
                overall = entry.get("overall_score")
                if overall is not None:
                    elo = float(overall)
                else:
                    rank = entry.get("rank", 1)
                    elo = 1500 - (rank - 1) * 100

            # Find the matching single-evaluation score
            for cond, papers in per_paper.items():
                if source and source in cond:
                    for _paper_id, paper_scores in papers.items():
                        overall = paper_scores.get("overall")
                        if overall is not None:
                            single_vals.append(overall)
                            pairwise_vals.append(float(elo))
                    break

    if len(single_vals) < 3:
        logger.warning("%s: Insufficient matched data (n=%d)", exp_id, len(single_vals))
        return all_paths

    # ── Fig 1: Scatter ──
    fig, ax = plt.subplots(figsize=FIG_SINGLE)
    x_arr = np.array(single_vals)
    y_arr = np.array(pairwise_vals)

    ax.scatter(
        x_arr, y_arr,
        s=30, alpha=0.7, color=TOL_BLUE,
        edgecolors="white", linewidth=0.4, zorder=3,
    )

    # Regression line (dashed grey)
    if len(x_arr) >= 2 and len(set(x_arr)) >= 2:
        coeffs = np.polyfit(x_arr, y_arr, 1)
        x_line = np.linspace(x_arr.min(), x_arr.max(), 100)
        y_line = np.polyval(coeffs, x_line)
        ax.plot(x_line, y_line, "--", color="grey", linewidth=1.2, alpha=0.7)

    # Spearman rho annotation
    rho = spearman(single_vals, pairwise_vals)
    ax.text(
        0.05, 0.95,
        f"Spearman $\\rho$ = {rho:.3f}\nn = {len(single_vals)}",
        transform=ax.transAxes, fontsize=8, va="top",
        bbox=dict(
            boxstyle="round,pad=0.4", facecolor="white",
            edgecolor="#CCCCCC", alpha=0.9,
        ),
    )

    ax.set_xlabel("Single Overall Score", fontsize=9)
    ax.set_ylabel("Pairwise ELO Rating", fontsize=9)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_scatter"))
    plt.close(fig)

    return all_paths


# =====================================================================
# EXP-302: LLM Reproducibility (repeat=5)
# =====================================================================


@register("EXP-302")
def vis_exp_302(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Box/strip plot of repeat distributions + CV bar chart."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    repeat_data = load_repeat_scores(run_dir)

    # Fallback: if no repeat data, use aggregate single scores
    use_fallback = not repeat_data
    if use_fallback:
        single_scores = load_single_scores(run_dir)
        if not single_scores:
            logger.warning("%s: No repeat or single score data found", exp_id)
            return all_paths

    # Pick the first condition with repeat data (or single fallback)
    if not use_fallback:
        cond_name = next(iter(repeat_data))
        metrics_by_repeat = repeat_data[cond_name]
    else:
        cond_name = next(iter(single_scores))
        metrics_by_repeat = {}

    display_metrics = METRICS + ["overall"]

    # ── Fig 1: Box + strip plot ──
    fig, ax = plt.subplots(figsize=FIG_DOUBLE)

    if not use_fallback and metrics_by_repeat:
        box_data: list[list[float]] = []
        box_labels: list[str] = []
        repeat_means_per_metric: dict[str, list[float]] = {}

        for metric in display_metrics:
            repeats = metrics_by_repeat.get(metric, [])
            if not repeats:
                continue
            # Flatten all repeat scores for the box
            flattened = []
            r_means: list[float] = []
            for r_scores in repeats:
                flattened.extend(r_scores)
                if r_scores:
                    r_means.append(safe_mean(r_scores))
            box_data.append(flattened)
            box_labels.append(METRIC_SHORT.get(metric, metric))
            repeat_means_per_metric[metric] = r_means

        if box_data:
            positions = list(range(1, len(box_data) + 1))
            bp = ax.boxplot(
                box_data, positions=positions, widths=0.5,
                patch_artist=True, showfliers=False,
            )
            for i, patch in enumerate(bp["boxes"]):
                m_key = display_metrics[i] if i < len(display_metrics) else "overall"
                patch.set_facecolor(METRIC_COLORS.get(m_key, TOL_BLUE))
                patch.set_alpha(0.35)
                patch.set_edgecolor(METRIC_COLORS.get(m_key, TOL_BLUE))

            for line_group in ("whiskers", "caps", "medians"):
                for line in bp[line_group]:
                    line.set_color("#555555")
                    line.set_linewidth(0.8)

            # Overlay individual repeat means as strip dots
            for i, metric in enumerate(display_metrics[:len(box_data)]):
                r_means = repeat_means_per_metric.get(metric, [])
                if r_means:
                    jitter = np.random.default_rng(42).uniform(
                        -0.12, 0.12, size=len(r_means),
                    )
                    ax.scatter(
                        [i + 1 + j for j in jitter],
                        r_means,
                        s=18, color=METRIC_COLORS.get(metric, TOL_BLUE),
                        edgecolors="white", linewidth=0.3, zorder=4, alpha=0.9,
                    )

            # CV annotation per metric
            for i, metric in enumerate(display_metrics[:len(box_data)]):
                r_means = repeat_means_per_metric.get(metric, [])
                if len(r_means) >= 2:
                    m = safe_mean(r_means)
                    s = safe_std(r_means)
                    cv = s / m if m > 0 else 0.0
                    ax.text(
                        i + 1, ax.get_ylim()[1] * 0.97,
                        f"CV={cv:.3f}",
                        ha="center", va="top", fontsize=8,
                        color=TOL_GREEN if cv < 0.05 else TOL_RED,
                    )

            ax.set_xticks(positions)
            ax.set_xticklabels(box_labels, fontsize=8)
    else:
        # Fallback: simple bar chart from single scores
        means = [safe_mean(single_scores[cond_name].get(m, [])) for m in display_metrics]
        sems = [safe_sem(single_scores[cond_name].get(m, [])) for m in display_metrics]
        x_pos = np.arange(len(display_metrics))
        colors = [METRIC_COLORS.get(m, TOL_BLUE) for m in display_metrics]
        ax.bar(
            x_pos, means, yerr=sems, capsize=3,
            color=colors, alpha=0.75, edgecolor="white", linewidth=0.5,
        )
        ax.set_xticks(x_pos)
        ax.set_xticklabels(
            [METRIC_SHORT.get(m, m) for m in display_metrics], fontsize=8,
        )

    ax.set_ylabel("Score (1-10)", fontsize=9)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_reproducibility"))
    plt.close(fig)

    # ── Fig 2: CV bar chart ──
    if not use_fallback and metrics_by_repeat:
        cv_labels: list[str] = []
        cv_values: list[float] = []
        for metric in display_metrics:
            repeats = metrics_by_repeat.get(metric, [])
            if not repeats:
                continue
            r_means = [safe_mean(r) for r in repeats if r]
            if len(r_means) >= 2:
                m = safe_mean(r_means)
                s = safe_std(r_means)
                cv = s / m if m > 0 else 0.0
                cv_labels.append(METRIC_SHORT.get(metric, metric))
                cv_values.append(cv)

        if cv_labels:
            fig2, ax2 = plt.subplots(figsize=FIG_SINGLE)
            bar_colors = [TOL_GREEN if v < 0.05 else TOL_RED for v in cv_values]
            bars = ax2.bar(
                cv_labels, cv_values, color=bar_colors,
                alpha=0.85, edgecolor="white", linewidth=0.5,
            )
            ax2.axhline(
                0.05, color="#555555", linestyle="--", linewidth=0.8,
                alpha=0.7, label="CV = 0.05",
            )

            # Value labels
            for bar, val in zip(bars, cv_values):
                ax2.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.002,
                    f"{val:.3f}", ha="center", va="bottom", fontsize=8,
                )

            ax2.set_ylabel("Coefficient of Variation", fontsize=9)
            ax2.legend(fontsize=8)
            ax2.tick_params(labelsize=8)
            ax2.set_ylim(0, max(cv_values) * 1.35 if cv_values else 0.1)
            fig2.tight_layout()
            all_paths.extend(save_figure(fig2, figures_dir, f"fig_{exp_id}_2_cv_bar"))
            plt.close(fig2)

            # ── Tables ──
            _generate_exp302_tables(
                display_metrics, metrics_by_repeat, figures_dir, exp_id,
            )

    return all_paths


def _generate_exp302_tables(
    display_metrics: list[str],
    metrics_by_repeat: dict[str, list[list[float]]],
    output_dir: Path,
    exp_id: str,
) -> None:
    """Generate Markdown and LaTeX reproducibility summary tables."""
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_data: list[dict] = []
    for metric in display_metrics:
        repeats = metrics_by_repeat.get(metric, [])
        if not repeats:
            continue
        r_means = [safe_mean(r) for r in repeats if r]
        if len(r_means) < 2:
            continue
        m = safe_mean(r_means)
        s = safe_std(r_means)
        cv = s / m if m > 0 else 0.0
        rows_data.append({
            "metric": METRIC_SHORT.get(metric, metric),
            "mean": m,
            "std": s,
            "cv": cv,
            "n_repeats": len(r_means),
        })

    if not rows_data:
        return

    # Find best (lowest) CV for bold highlighting
    best_cv = min(r["cv"] for r in rows_data)

    # ── Markdown ──
    md_lines = [
        f"## {exp_id}: Reproducibility Metrics\n",
        "| Metric | Mean | SD | CV | Repeats |",
        "|--------|-----:|----:|----:|--------:|",
    ]
    for r in rows_data:
        md_lines.append(
            f"| {r['metric']} | {r['mean']:.2f} | {r['std']:.3f} "
            f"| {r['cv']:.4f} | {r['n_repeats']} |"
        )
    md_lines.append("")
    (output_dir / f"table_{exp_id}.md").write_text(
        "\n".join(md_lines), encoding="utf-8",
    )

    # ── LaTeX (booktabs, bold best) ──
    tex_rows: list[str] = []
    for r in rows_data:
        cv_str = f"{r['cv']:.4f}"
        if r["cv"] == best_cv:
            cv_str = f"\\textbf{{{cv_str}}}"
        tex_rows.append(
            f"  {r['metric']} & {r['mean']:.2f} & {r['std']:.3f} "
            f"& {cv_str} & {r['n_repeats']} \\\\"
        )

    tex = (
        "\\begin{table}[htbp]\n"
        "  \\centering\n"
        f"  \\caption{{{exp_id}: Reproducibility Metrics}}\n"
        "  \\begin{tabular}{lrrrr}\n"
        "    \\toprule\n"
        "    Metric & Mean & SD & CV & Repeats \\\\\n"
        "    \\midrule\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        "    \\bottomrule\n"
        "  \\end{tabular}\n"
        "\\end{table}\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")


# =====================================================================
# EXP-303: Position Bias Measurement
# =====================================================================


@register("EXP-303")
def vis_exp_303(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Confusion matrix of AB/BA order + per-metric flip rate bar."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    swap_data = load_pairwise_swap_data(run_dir)

    if not swap_data:
        logger.info("%s: No swap_test data found", exp_id)
        return all_paths

    # Collect unique sources
    sources: set[str] = set()
    for _paper_id, info in swap_data.items():
        sources.add(info.get("ab_winner", ""))
        sources.add(info.get("ba_winner", ""))
    sources.discard("")
    source_list = sorted(sources)

    if len(source_list) < 2:
        return all_paths

    # ── Fig 1: Confusion matrix ──
    n = len(source_list)
    matrix = [[0] * n for _ in range(n)]
    total = 0
    consistent = 0

    for _paper_id, info in swap_data.items():
        ab = info.get("ab_winner", "")
        ba = info.get("ba_winner", "")
        if ab in source_list and ba in source_list:
            i = source_list.index(ab)
            j = source_list.index(ba)
            matrix[i][j] += 1
            total += 1
            if ab == ba:
                consistent += 1

    agree_rate = consistent / total * 100 if total > 0 else 0.0

    fig, ax = plt.subplots(figsize=FIG_SINGLE)
    arr = np.array(matrix, dtype=float)
    im = ax.imshow(arr, cmap="Blues", aspect="auto")

    ax.set_xticks(range(n))
    ax.set_xticklabels([display_name(s) for s in source_list], fontsize=8)
    ax.set_yticks(range(n))
    ax.set_yticklabels([display_name(s) for s in source_list], fontsize=8)

    # Cell annotations
    for i in range(n):
        for j in range(n):
            val = int(matrix[i][j])
            text_color = "white" if val > arr.max() * 0.6 else "black"
            ax.text(
                j, i, str(val), ha="center", va="center",
                fontsize=8, fontweight="bold", color=text_color,
            )

    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_xlabel("BA-order winner", fontsize=9)
    ax.set_ylabel("AB-order winner", fontsize=9)

    # Agreement rate annotation below the plot
    ax.text(
        0.5, -0.18,
        f"Agreement: {agree_rate:.1f}% ({consistent}/{total})",
        transform=ax.transAxes, fontsize=8, ha="center",
        bbox=dict(
            boxstyle="round,pad=0.4", facecolor="white",
            edgecolor="#CCCCCC", alpha=0.9,
        ),
    )

    ax.tick_params(labelsize=8)
    fig.tight_layout()
    all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_confusion"))
    plt.close(fig)

    # ── Fig 2: Per-metric flip rate ──
    pw_details = load_pairwise_details(run_dir)
    metric_flips: dict[str, int] = {m: 0 for m in METRICS}
    metric_totals: dict[str, int] = {m: 0 for m in METRICS}

    for pw in pw_details:
        swap = pw.get("swap_test", {})
        metrics_swap = swap.get("metrics", {})
        for metric in METRICS:
            if metric in metrics_swap:
                metric_totals[metric] += 1
                if not metrics_swap[metric].get("consistent", True):
                    metric_flips[metric] += 1

    flip_labels: list[str] = []
    flip_values: list[float] = []
    for m in METRICS:
        if metric_totals.get(m, 0) > 0:
            flip_labels.append(METRIC_SHORT.get(m, m))
            flip_values.append(metric_flips[m] / metric_totals[m] * 100)

    if flip_labels:
        fig2, ax2 = plt.subplots(figsize=FIG_SINGLE)
        bar_colors = [METRIC_COLORS.get(m, TOL_BLUE) for m in METRICS if metric_totals.get(m, 0) > 0]
        bars = ax2.bar(
            flip_labels, flip_values, color=bar_colors,
            alpha=0.85, edgecolor="white", linewidth=0.5,
        )

        # Value labels
        for bar, val in zip(bars, flip_values):
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{val:.1f}%", ha="center", va="bottom", fontsize=8,
            )

        ax2.set_ylabel("Flip Rate (%)", fontsize=9)
        ax2.tick_params(labelsize=8)
        ax2.set_ylim(0, max(flip_values) * 1.3 if flip_values else 50)
        fig2.tight_layout()
        all_paths.extend(save_figure(fig2, figures_dir, f"fig_{exp_id}_2_flip_rate"))
        plt.close(fig2)

    # ── Tables ──
    _generate_exp303_tables(
        source_list, matrix, agree_rate, total,
        metric_flips, metric_totals, figures_dir, exp_id,
    )

    return all_paths


def _generate_exp303_tables(
    source_list: list[str],
    matrix: list[list[int]],
    agree_rate: float,
    total: int,
    metric_flips: dict[str, int],
    metric_totals: dict[str, int],
    output_dir: Path,
    exp_id: str,
) -> None:
    """Generate Markdown and LaTeX tables for position bias results."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Markdown ──
    md_lines = [
        f"## {exp_id}: Position Bias Summary\n",
        f"Overall agreement rate: {agree_rate:.1f}% (n={total})\n",
        "### Per-Metric Flip Rates\n",
        "| Metric | Flips | Total | Rate (%) |",
        "|--------|------:|------:|---------:|",
    ]
    for m in METRICS:
        if metric_totals.get(m, 0) > 0:
            rate = metric_flips[m] / metric_totals[m] * 100
            md_lines.append(
                f"| {METRIC_SHORT.get(m, m)} | {metric_flips[m]} "
                f"| {metric_totals[m]} | {rate:.1f} |"
            )
    md_lines.append("")
    (output_dir / f"table_{exp_id}.md").write_text(
        "\n".join(md_lines), encoding="utf-8",
    )

    # ── LaTeX (booktabs) ──
    # Find best (lowest) flip rate for bold
    rates = {
        m: metric_flips[m] / metric_totals[m] * 100
        for m in METRICS if metric_totals.get(m, 0) > 0
    }
    best_rate = min(rates.values()) if rates else 0.0

    tex_rows: list[str] = []
    for m in METRICS:
        if metric_totals.get(m, 0) > 0:
            rate = rates[m]
            rate_str = f"{rate:.1f}"
            if rate == best_rate:
                rate_str = f"\\textbf{{{rate_str}}}"
            tex_rows.append(
                f"  {METRIC_SHORT.get(m, m)} & {metric_flips[m]} "
                f"& {metric_totals[m]} & {rate_str} \\\\"
            )

    tex = (
        "\\begin{table}[htbp]\n"
        "  \\centering\n"
        f"  \\caption{{{exp_id}: Position Bias — Per-Metric Flip Rates"
        f" (Agreement {agree_rate:.1f}\\%)}}\n"
        "  \\begin{tabular}{lrrr}\n"
        "    \\toprule\n"
        "    Metric & Flips & Total & Rate (\\%) \\\\\n"
        "    \\midrule\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        "    \\bottomrule\n"
        "  \\end{tabular}\n"
        "\\end{table}\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex, encoding="utf-8")


# =====================================================================
# EXP-304: Cross-Model Evaluation Consistency
# =====================================================================


@register("EXP-304")
def vis_exp_304(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Correlation heatmap + violin plot across evaluator models."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    model_scores = load_multi_model_scores(run_dir)
    models = sorted(model_scores.keys())

    if len(models) < 2:
        logger.warning(
            "%s: Need >= 2 models for cross-model analysis (found %d)",
            exp_id, len(models),
        )
        return all_paths

    # Gather per-model overall score lists
    model_overalls: dict[str, list[float]] = {}
    for model in models:
        all_overalls: list[float] = []
        for cond_scores in model_scores[model].values():
            all_overalls.extend(cond_scores.get("overall", []))
        model_overalls[model] = all_overalls

    # Short model labels for display
    short_models = [m.split("/")[-1][:20] for m in models]

    # ── Fig 1: Correlation heatmap ──
    n = len(models)
    corr_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            a = model_overalls[models[i]]
            b = model_overalls[models[j]]
            min_len = min(len(a), len(b))
            if min_len >= 2:
                corr_matrix[i, j] = spearman(a[:min_len], b[:min_len])
            else:
                corr_matrix[i, j] = 1.0 if i == j else 0.0

    fig, ax = plt.subplots(figsize=FIG_SINGLE)
    im = ax.imshow(
        corr_matrix, cmap="RdYlGn", aspect="auto",
        vmin=-1.0, vmax=1.0,
    )

    ax.set_xticks(range(n))
    ax.set_xticklabels(short_models, fontsize=8, rotation=30, ha="right")
    ax.set_yticks(range(n))
    ax.set_yticklabels(short_models, fontsize=8)

    # Cell annotations
    for i in range(n):
        for j in range(n):
            val = corr_matrix[i, j]
            text_color = "white" if abs(val) > 0.7 else "black"
            ax.text(
                j, i, f"{val:.2f}", ha="center", va="center",
                fontsize=8, fontweight="bold", color=text_color,
            )

    fig.colorbar(im, ax=ax, shrink=0.8, label="Spearman $\\rho$")
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_corr_heatmap"))
    plt.close(fig)

    # ── Fig 2: Violin plot ──
    fig2, ax2 = plt.subplots(figsize=FIG_SINGLE)

    violin_data = [model_overalls[m] for m in models]
    # Filter out empty lists
    valid_indices = [i for i, d in enumerate(violin_data) if len(d) >= 2]
    if valid_indices:
        valid_data = [violin_data[i] for i in valid_indices]
        valid_labels = [short_models[i] for i in valid_indices]

        parts = ax2.violinplot(
            valid_data, positions=range(1, len(valid_data) + 1),
            showmeans=True, showmedians=True,
        )

        for i, pc in enumerate(parts.get("bodies", [])):
            pc.set_facecolor(PALETTE[i % len(PALETTE)])
            pc.set_alpha(0.6)
            pc.set_edgecolor(PALETTE[i % len(PALETTE)])

        # Style the statistic lines
        for key in ("cmeans", "cmedians", "cmins", "cmaxes", "cbars"):
            if key in parts:
                parts[key].set_color("#333333")
                parts[key].set_linewidth(0.8)

        ax2.set_xticks(range(1, len(valid_labels) + 1))
        ax2.set_xticklabels(valid_labels, fontsize=8, rotation=15, ha="right")

    ax2.set_ylabel("Overall Score", fontsize=9)
    ax2.tick_params(labelsize=8)
    fig2.tight_layout()
    all_paths.extend(save_figure(fig2, figures_dir, f"fig_{exp_id}_2_violin"))
    plt.close(fig2)

    return all_paths


# =====================================================================
# EXP-305: Human-LLM Correlation
# =====================================================================


@register("EXP-305")
def vis_exp_305(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Scatter (human vs LLM) with regression. Graceful if no human data."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []

    # Search for human_eval.csv in several locations
    human_csv = run_dir / "human_eval.csv"
    if not human_csv.exists():
        human_csv = run_dir / "evaluations" / "human_eval.csv"
    if not human_csv.exists():
        logger.info("%s: No human evaluation CSV found; skipping", exp_id)
        return all_paths

    # Parse CSV manually to avoid pandas dependency
    human_records: list[dict[str, str]] = []
    try:
        text = human_csv.read_text(encoding="utf-8")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) < 2:
            return all_paths
        headers = [h.strip() for h in lines[0].split(",")]
        for line in lines[1:]:
            values = [v.strip() for v in line.split(",")]
            if len(values) == len(headers):
                human_records.append(dict(zip(headers, values)))
    except Exception:
        logger.warning("%s: Failed to parse human_eval.csv", exp_id)
        return all_paths

    if not human_records:
        return all_paths

    # Match human scores with LLM single scores
    per_paper = load_single_scores_per_paper(run_dir)
    human_scores: list[float] = []
    llm_scores: list[float] = []

    for rec in human_records:
        proposal_id = rec.get("proposal_id", rec.get("paper_id", ""))
        # Compute human mean from available metric columns
        human_vals: list[float] = []
        for m in METRICS:
            val = rec.get(m)
            if val is not None:
                try:
                    human_vals.append(float(val))
                except (ValueError, TypeError):
                    pass
        # Also try "overall" directly
        overall_raw = rec.get("overall")
        if overall_raw is not None:
            try:
                human_mean = float(overall_raw)
            except (ValueError, TypeError):
                human_mean = safe_mean(human_vals) if human_vals else None
        else:
            human_mean = safe_mean(human_vals) if human_vals else None

        if human_mean is None:
            continue

        # Find matching LLM score
        matched = False
        for cond, papers in per_paper.items():
            for paper_id, scores in papers.items():
                if proposal_id in paper_id or paper_id in proposal_id:
                    llm_overall = scores.get("overall")
                    if llm_overall is not None:
                        human_scores.append(human_mean)
                        llm_scores.append(llm_overall)
                        matched = True
                        break
            if matched:
                break

    if len(human_scores) < 3:
        logger.info(
            "%s: Insufficient matched human-LLM pairs (n=%d)",
            exp_id, len(human_scores),
        )
        return all_paths

    # ── Fig 1: Scatter with regression ──
    fig, ax = plt.subplots(figsize=FIG_SINGLE)
    x_arr = np.array(human_scores)
    y_arr = np.array(llm_scores)

    ax.scatter(
        x_arr, y_arr, s=30, alpha=0.7, color=TOL_BLUE,
        edgecolors="white", linewidth=0.4, zorder=3,
    )

    # Regression line
    if len(x_arr) >= 2 and len(set(x_arr)) >= 2:
        coeffs = np.polyfit(x_arr, y_arr, 1)
        x_line = np.linspace(x_arr.min(), x_arr.max(), 100)
        y_line = np.polyval(coeffs, x_line)
        ax.plot(x_line, y_line, "--", color="grey", linewidth=1.2, alpha=0.7)

    # Identity line (y = x)
    lo = min(x_arr.min(), y_arr.min()) - 0.5
    hi = max(x_arr.max(), y_arr.max()) + 0.5
    ax.plot([lo, hi], [lo, hi], ":", color="black", alpha=0.25, linewidth=0.8)

    # Pearson r + Spearman rho annotation
    r = pearson(human_scores, llm_scores)
    rho = spearman(human_scores, llm_scores)
    ax.text(
        0.05, 0.95,
        f"Pearson r = {r:.3f}\nSpearman $\\rho$ = {rho:.3f}\nn = {len(human_scores)}",
        transform=ax.transAxes, fontsize=8, va="top",
        bbox=dict(
            boxstyle="round,pad=0.4", facecolor="white",
            edgecolor="#CCCCCC", alpha=0.9,
        ),
    )

    ax.set_xlabel("Human Score", fontsize=9)
    ax.set_ylabel("LLM Score", fontsize=9)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_scatter"))
    plt.close(fig)

    return all_paths


# =====================================================================
# EXP-306: Traceability Assessment
# =====================================================================


@register("EXP-306")
def vis_exp_306(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Grouped bar (ideagraph vs direct_llm) + optional stacked grounding bar."""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    if len(conditions) < 2:
        logger.warning(
            "%s: Need >= 2 conditions for comparison (found %d)",
            exp_id, len(conditions),
        )
        return all_paths

    # ── Fig 1: Grouped bar with significance stars ──
    stats = StatsHelper(run_dir)
    sig_results = stats.per_metric_significance(conditions[0], conditions[1])

    n_metrics = len(METRICS)
    n_conds = len(conditions)
    bar_width = 0.8 / n_conds
    x_base = np.arange(n_metrics)

    fig, ax = plt.subplots(figsize=FIG_DOUBLE)
    for c_idx, cond in enumerate(conditions):
        means = [safe_mean(scores[cond].get(m, [])) for m in METRICS]
        sems = [safe_sem(scores[cond].get(m, [])) for m in METRICS]
        offset = (c_idx - (n_conds - 1) / 2) * bar_width
        c = color_for(cond)
        ax.bar(
            x_base + offset, means, bar_width * 0.88,
            yerr=sems, capsize=3, color=c, alpha=0.85,
            label=display_name(cond),
            error_kw={"linewidth": 0.8},
        )

    # Significance annotations
    y_max = ax.get_ylim()[1]
    for sr in sig_results:
        metric_name = sr.get("metric", "")
        if metric_name not in METRICS:
            continue
        m_idx = METRICS.index(metric_name)
        stars = sr.get("stars", "n.s.")

        cond_a = sr.get("cond_a", "")
        cond_b = sr.get("cond_b", "")
        if cond_a not in conditions or cond_b not in conditions:
            continue
        a_idx = conditions.index(cond_a)
        b_idx = conditions.index(cond_b)
        x1 = m_idx + (a_idx - (n_conds - 1) / 2) * bar_width
        x2 = m_idx + (b_idx - (n_conds - 1) / 2) * bar_width

        y_bar = y_max * 0.92
        ax.plot(
            [x1, x1, x2, x2],
            [y_bar - 0.08, y_bar, y_bar, y_bar - 0.08],
            color="black", linewidth=0.7,
        )
        ax.text(
            (x1 + x2) / 2, y_bar + 0.03, stars,
            ha="center", va="bottom", fontsize=8,
        )

    ax.set_xticks(x_base)
    ax.set_xticklabels(
        [METRIC_SHORT.get(m, m) for m in METRICS], fontsize=8,
    )
    ax.set_ylabel("Score (1-10)", fontsize=9)
    ax.legend(fontsize=8)
    ax.tick_params(labelsize=8)
    ax.set_ylim(0, None)
    fig.tight_layout()
    all_paths.extend(save_figure(fig, figures_dir, f"fig_{exp_id}_1_grouped_bar"))
    plt.close(fig)

    # ── Fig 2: Stacked bar (grounding categories) ──
    grounding_file = run_dir / "summary" / "grounding_analysis.json"
    if not grounding_file.exists():
        grounding_file = run_dir / "grounding_analysis.json"

    if grounding_file.exists():
        try:
            grounding = json.loads(grounding_file.read_text(encoding="utf-8"))
            categories = list(grounding.keys())
            full_vals = [grounding[c].get("full", 0) for c in categories]
            partial_vals = [grounding[c].get("partial", 0) for c in categories]
            none_vals = [grounding[c].get("none", 0) for c in categories]

            # Convert to percentages
            for i in range(len(categories)):
                total = full_vals[i] + partial_vals[i] + none_vals[i]
                if total > 0:
                    full_vals[i] = full_vals[i] / total * 100
                    partial_vals[i] = partial_vals[i] / total * 100
                    none_vals[i] = none_vals[i] / total * 100

            fig2, ax2 = plt.subplots(figsize=FIG_SINGLE)
            x = np.arange(len(categories))
            w = 0.55
            bottom_partial = np.array(full_vals)
            bottom_none = bottom_partial + np.array(partial_vals)

            ax2.bar(
                x, full_vals, w, label="Full",
                color=TOL_GREEN, alpha=0.85, edgecolor="white", linewidth=0.5,
            )
            ax2.bar(
                x, partial_vals, w, bottom=full_vals, label="Partial",
                color=TOL_YELLOW, alpha=0.85, edgecolor="white", linewidth=0.5,
            )
            ax2.bar(
                x, none_vals, w, bottom=bottom_none.tolist(), label="None",
                color=TOL_RED, alpha=0.85, edgecolor="white", linewidth=0.5,
            )

            # Percentage labels inside bars
            for i in range(len(categories)):
                for val, base in [
                    (full_vals[i], 0),
                    (partial_vals[i], full_vals[i]),
                    (none_vals[i], float(bottom_none[i])),
                ]:
                    if val > 5:
                        ax2.text(
                            x[i], base + val / 2,
                            f"{val:.0f}%", ha="center", va="center",
                            fontsize=8, color="white", fontweight="bold",
                        )

            ax2.set_xticks(x)
            ax2.set_xticklabels(
                [display_name(c) for c in categories], fontsize=8,
            )
            ax2.set_ylabel("Grounding Rate (%)", fontsize=9)
            ax2.legend(fontsize=8)
            ax2.tick_params(labelsize=8)
            fig2.tight_layout()
            all_paths.extend(
                save_figure(fig2, figures_dir, f"fig_{exp_id}_2_stacked"),
            )
            plt.close(fig2)
        except Exception:
            logger.warning(
                "%s: Failed to parse grounding_analysis.json", exp_id,
            )

    return all_paths
