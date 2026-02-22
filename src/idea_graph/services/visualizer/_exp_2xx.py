"""200系: アブレーション実験の可視化 (EXP-201〜209)

EXP-201: Multi-hop depth ablation
EXP-202: Graph format ablation
EXP-203: Prompt scope ablation
EXP-204: Path count ablation
EXP-205: Graph size effect
EXP-206: Proposal count ablation
EXP-207: Quality-cost efficiency
EXP-208: 接続性安定性 → degree連続値散布図 + 回帰分析
EXP-209: 接続性効果 → 交互作用プロット
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._registry import register
from ._style import METRICS, METRIC_SHORT, STYLE, _safe_mean, _safe_std, _save_figure, HAS_MPL, logger
from ._loaders import (
    load_single_scores,
    load_single_scores_per_paper,
    load_experiment_meta,
    load_paper_degrees,
)

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# ══════════════════════════════════════════════════════
# 共通ユーティリティ
# ══════════════════════════════════════════════════════


def _extract_sweep(
    conditions: list[str],
) -> tuple[list[float], list[str]] | None:
    """条件名から数値パラメータを抽出してソートする。"""
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
    run_dir: Path, figures_dir: Path, exp_id: str,
    xlabel: str,
) -> list[Path]:
    """パラメータスイープ実験の共通可視化: MultiLine + Heatmap。"""
    if not HAS_MPL:
        return []
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    sweep = _extract_sweep(conditions)
    if not sweep:
        logger.warning("%s: Could not detect parameter sweep in condition names", exp_id)
        return all_paths
    x_values, sorted_conds = sweep

    # ── Fig 1: MultiLine (各指標 + SD帯 + 最適点) ──
    metric_colors = {
        "novelty": "#2563EB", "significance": "#DC2626",
        "feasibility": "#16A34A", "clarity": "#F59E0B",
        "effectiveness": "#8B5CF6", "overall": "#0F172A",
    }
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    for metric in METRICS + ["overall"]:
        means = [_safe_mean(scores[c].get(metric, [])) for c in sorted_conds]
        stds = [_safe_std(scores[c].get(metric, [])) for c in sorted_conds]
        x_arr = np.array(x_values[:len(means)])
        m_arr = np.array(means)
        s_arr = np.array(stds)
        color = metric_colors.get(metric, "#6B7280")
        label = METRIC_SHORT.get(metric, metric.capitalize())
        lw = 2.5 if metric == "overall" else 1.5
        ls = "-" if metric == "overall" else "--"
        ax1.plot(x_arr, m_arr, f"o{ls}", color=color, linewidth=lw, label=label, markersize=5)
        if len(x_arr) > 1:
            ax1.fill_between(x_arr, m_arr - s_arr, m_arr + s_arr, alpha=0.1, color=color)
        # 最適点 (overall のみ)
        if metric == "overall" and len(m_arr) > 0:
            best_idx = int(np.argmax(m_arr))
            ax1.plot(x_arr[best_idx], m_arr[best_idx], "*", color=color, markersize=14, zorder=5)

    ax1.set_xlabel(xlabel, fontsize=11)
    ax1.set_ylabel("Score (1-10)", fontsize=11)
    ax1.set_title(f"{exp_id}: {xlabel} vs Quality", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9, ncol=2)
    ax1.grid(True, alpha=0.3)
    fig1.tight_layout()
    all_paths.extend(_save_figure(fig1, figures_dir, f"fig_{exp_id}_1_sweep"))
    plt.close(fig1)

    # ── Fig 2: Heatmap (パラメータ × 指標) ──
    fig2, ax2 = plt.subplots(figsize=(9, max(4, len(sorted_conds) * 0.8)))
    data = []
    for cond in sorted_conds:
        row = [_safe_mean(scores[cond].get(m, [])) for m in METRICS]
        data.append(row)
    arr = np.array(data)
    col_labels = [METRIC_SHORT.get(m, m) for m in METRICS]
    row_labels = [str(int(x)) if x == int(x) else str(x) for x in x_values]

    im = ax2.imshow(arr, cmap="YlOrRd", aspect="auto")
    ax2.set_xticks(range(len(col_labels)))
    ax2.set_xticklabels(col_labels, fontsize=10)
    ax2.set_yticks(range(len(row_labels)))
    ax2.set_yticklabels(row_labels, fontsize=10)

    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            ax2.text(j, i, f"{arr[i, j]:.1f}", ha="center", va="center", fontsize=9, fontweight="bold")

    # 列最高値ハイライト
    for j in range(arr.shape[1]):
        best_i = int(np.argmax(arr[:, j]))
        ax2.add_patch(plt.Rectangle(
            (j - 0.5, best_i - 0.5), 1, 1,
            fill=False, edgecolor="#16A34A", linewidth=2.5,
        ))

    fig2.colorbar(im, ax=ax2, label="Score", shrink=0.8)
    ax2.set_xlabel("Metric", fontsize=11)
    ax2.set_ylabel(xlabel, fontsize=11)
    ax2.set_title(f"{exp_id}: {xlabel} × Metric Heatmap", fontsize=12, fontweight="bold")
    fig2.tight_layout()
    all_paths.extend(_save_figure(fig2, figures_dir, f"fig_{exp_id}_2_heatmap"))
    plt.close(fig2)

    # ── Table (Markdown + LaTeX) ──
    _generate_sweep_tables(sorted_conds, x_values, scores, figures_dir, exp_id, xlabel)

    return all_paths


def _grouped_bar_figures(
    run_dir: Path, figures_dir: Path, exp_id: str,
) -> list[Path]:
    """カテゴリ条件 (非数値) の比較: Grouped Bar + Radar。"""
    if not HAS_MPL:
        return []
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if len(conditions) < 2:
        return all_paths

    # ── Fig 1: Grouped Bar ──
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    n_metrics = len(METRICS)
    n_conds = len(conditions)
    bar_width = 0.8 / n_conds
    x_base = np.arange(n_metrics)

    for c_idx, cond in enumerate(conditions):
        means = [_safe_mean(scores[cond].get(m, [])) for m in METRICS]
        sems = [_safe_std(scores[cond].get(m, [])) / max(1, len(scores[cond].get(m, []))) ** 0.5 for m in METRICS]
        offset = (c_idx - (n_conds - 1) / 2) * bar_width
        color = STYLE.color_for(cond)
        ax1.bar(
            x_base + offset, means, bar_width * 0.88,
            yerr=sems, capsize=3, color=color, alpha=0.85,
            label=cond, error_kw={"linewidth": 1},
        )

    ax1.set_xticks(x_base)
    ax1.set_xticklabels([METRIC_SHORT.get(m, m) for m in METRICS], fontsize=10)
    ax1.set_ylabel("Score (1-10)", fontsize=11)
    ax1.set_title(f"{exp_id}: Condition Comparison", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9)
    ax1.grid(axis="y", alpha=0.3)
    fig1.tight_layout()
    all_paths.extend(_save_figure(fig1, figures_dir, f"fig_{exp_id}_1_grouped_bar"))
    plt.close(fig1)

    return all_paths


# ══════════════════════════════════════════════════════
# 各実験の登録
# ══════════════════════════════════════════════════════


@register("EXP-201")
def vis_exp_201(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    return _sweep_figures(run_dir, figures_dir, exp_id, xlabel="Max Hops")


@register("EXP-202")
def vis_exp_202(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    return _grouped_bar_figures(run_dir, figures_dir, exp_id)


@register("EXP-203")
def vis_exp_203(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    return _grouped_bar_figures(run_dir, figures_dir, exp_id)


@register("EXP-204")
def vis_exp_204(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    return _sweep_figures(run_dir, figures_dir, exp_id, xlabel="Path Count")


@register("EXP-205")
def vis_exp_205(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    return _sweep_figures(run_dir, figures_dir, exp_id, xlabel="Graph Size")


@register("EXP-206")
def vis_exp_206(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Num proposals: mean overall + best-of-N dual line。"""
    if not HAS_MPL:
        return []
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    sweep = _extract_sweep(conditions)
    if not sweep:
        return _grouped_bar_figures(run_dir, figures_dir, exp_id)
    x_values, sorted_conds = sweep

    mean_overall = [_safe_mean(scores[c].get("overall", [])) for c in sorted_conds]
    per_paper = load_single_scores_per_paper(run_dir)
    best_of_n: list[float] = []
    for cond in sorted_conds:
        papers = per_paper.get(cond, {})
        if papers:
            bests = [p.get("overall", 0) for p in papers.values()]
            best_of_n.append(max(bests) if bests else 0)
        else:
            best_of_n.append(0)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x_values, mean_overall, "o-", color="#2563EB", linewidth=2.5, label="Mean Overall", markersize=7)
    ax.plot(x_values, best_of_n, "s--", color="#DC2626", linewidth=2.5, label="Best-of-N", markersize=7)
    ax.fill_between(x_values, mean_overall, best_of_n, alpha=0.08, color="#8B5CF6")

    ax.set_xlabel("Num Proposals", fontsize=11)
    ax.set_ylabel("Overall Score (1-10)", fontsize=11)
    ax.set_title(f"{exp_id}: Mean vs Best-of-N by Proposal Count", fontsize=12, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    all_paths.extend(_save_figure(fig, figures_dir, f"fig_{exp_id}_1_dual_line"))
    plt.close(fig)

    return all_paths


@register("EXP-207")
def vis_exp_207(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """Quality-Cost Pareto frontier。"""
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
        overall_scores.append(_safe_mean(scores[cond].get("overall", [])))
        labels.append(cond)
        cost = 0.0
        log_file = log_dir / f"{cond}.json" if log_dir.exists() else None
        if log_file and log_file.exists():
            try:
                cost = float(json.loads(log_file.read_text(encoding="utf-8")).get("total_cost_usd", 0))
            except Exception:
                pass
        if cost == 0:
            nums = re.findall(r"(\d+)", cond)
            cost = sum(float(n) for n in nums) * 0.001 if nums else 0.01
        costs.append(cost)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(costs, overall_scores, s=80, color="#2563EB", zorder=5, edgecolors="white", linewidth=0.8)
    for i, label in enumerate(labels):
        ax.annotate(label, (costs[i], overall_scores[i]), fontsize=8, xytext=(6, 6), textcoords="offset points")

    # Pareto front
    paired = sorted(zip(costs, overall_scores), key=lambda p: p[0])
    front_x, front_y = [], []
    best = -float("inf")
    for c, s in paired:
        if s >= best:
            front_x.append(c)
            front_y.append(s)
            best = s
    ax.plot(front_x, front_y, "r--", linewidth=2, label="Pareto Front", alpha=0.7)

    ax.set_xlabel("Estimated Cost (USD)", fontsize=11)
    ax.set_ylabel("Overall Score", fontsize=11)
    ax.set_title(f"{exp_id}: Quality-Cost Pareto Frontier", fontsize=12, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    all_paths.extend(_save_figure(fig, figures_dir, f"fig_{exp_id}_1_pareto"))
    plt.close(fig)

    return all_paths


# ══════════════════════════════════════════════════════
# EXP-208: 接続性安定性 (degree連続値)
# ══════════════════════════════════════════════════════


@register("EXP-208")
def vis_exp_208(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-208: degree (連続値) × スコア散布図 + 回帰分析 + 相関サマリ。"""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    if not scores:
        return all_paths

    degrees = load_paper_degrees(run_dir)
    per_paper = load_single_scores_per_paper(run_dir)

    # degree × score ペアを構築 (全条件統合)
    degree_vals: list[float] = []
    overall_vals: list[float] = []
    metric_pairs: dict[str, tuple[list[float], list[float]]] = {m: ([], []) for m in METRICS}

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

    # データが少ない場合も対応: 少なくとも1点あればプロット
    if not degree_vals:
        logger.warning("EXP-208: No degree-score data available")
        return all_paths

    # spearman を安全にインポート
    try:
        from idea_graph.services.aggregator import spearman, pearson
    except ImportError:
        def spearman(x: list[float], y: list[float]) -> float:
            return 0.0
        def pearson(x: list[float], y: list[float]) -> float:
            return 0.0

    # ── Fig 1: Degree × Overall 散布図 + 回帰線 ──
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    x_arr = np.array(degree_vals)
    y_arr = np.array(overall_vals)

    ax1.scatter(
        x_arr, y_arr, s=60, alpha=0.7, color="#2563EB",
        edgecolors="white", linewidth=0.8, zorder=3,
    )

    # 回帰線 + 95%CI帯 (2点以上必要)
    if len(x_arr) >= 2 and len(set(x_arr)) >= 2:
        coeffs = np.polyfit(x_arr, y_arr, 1)
        x_line = np.linspace(x_arr.min() - 1, x_arr.max() + 1, 100)
        y_line = np.polyval(coeffs, x_line)
        ax1.plot(x_line, y_line, "--", color="#DC2626", linewidth=2, label="Linear Fit")

        y_pred = np.polyval(coeffs, x_arr)
        se = np.std(y_arr - y_pred)
        ax1.fill_between(
            x_line, y_line - 1.96 * se, y_line + 1.96 * se,
            alpha=0.12, color="#DC2626", label="95% CI",
        )

    # 統計アノテーション
    n = len(degree_vals)
    rho = spearman(degree_vals, overall_vals) if n >= 3 else 0.0
    r = pearson(degree_vals, overall_vals) if n >= 3 else 0.0
    annotation = f"n = {n}"
    if n >= 3:
        annotation += f"\nSpearman ρ = {rho:.3f}\nPearson r = {r:.3f}"
    ax1.text(
        0.05, 0.95, annotation, transform=ax1.transAxes,
        fontsize=11, va="top", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="#D1D5DB", alpha=0.9),
    )

    ax1.set_xlabel("Degree (number of connections)", fontsize=12)
    ax1.set_ylabel("Overall Score", fontsize=12)
    ax1.set_title(
        f"{exp_id}: Connectivity Stability — Degree vs Overall Score",
        fontsize=13, fontweight="bold",
    )
    # 凡例はアーティストがある場合のみ
    handles, labels = ax1.get_legend_handles_labels()
    if handles:
        ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)
    fig1.tight_layout()
    all_paths.extend(_save_figure(fig1, figures_dir, f"fig_{exp_id}_1_degree_scatter"))
    plt.close(fig1)

    # ── Fig 2: 指標別パネル (2×3 サブプロット) ──
    plot_metrics = METRICS + ["overall"]
    all_metric_pairs = {**metric_pairs, "overall": (degree_vals, overall_vals)}

    fig2, axes = plt.subplots(2, 3, figsize=(15, 9))
    metric_colors = {
        "novelty": "#2563EB", "significance": "#DC2626",
        "feasibility": "#16A34A", "clarity": "#F59E0B",
        "effectiveness": "#8B5CF6", "overall": "#0F172A",
    }

    for idx, m in enumerate(plot_metrics):
        row, col = idx // 3, idx % 3
        ax = axes[row][col]
        dx, dy = all_metric_pairs[m]
        color = metric_colors.get(m, "#6B7280")

        if len(dx) < 1:
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes, ha="center", va="center", fontsize=11)
            ax.set_title(METRIC_SHORT.get(m, m.capitalize()), fontsize=11, fontweight="bold")
            continue

        ax.scatter(dx, dy, alpha=0.6, color=color, s=40, edgecolors="white", linewidth=0.5)

        if len(dx) >= 2 and len(set(dx)) >= 2:
            x_a = np.array(dx)
            y_a = np.array(dy)
            c = np.polyfit(x_a, y_a, 1)
            xl = np.linspace(x_a.min(), x_a.max(), 50)
            ax.plot(xl, np.polyval(c, xl), "--", color="#DC2626", linewidth=1.5)

        if len(dx) >= 3:
            rho_m = spearman(dx, dy)
            ax.text(
                0.05, 0.95, f"ρ = {rho_m:.3f}", transform=ax.transAxes,
                fontsize=10, va="top", fontweight="bold",
                bbox=dict(boxstyle="round", facecolor="white", edgecolor="#D1D5DB", alpha=0.9),
            )

        ax.set_title(METRIC_SHORT.get(m, m.capitalize()), fontsize=11, fontweight="bold")
        ax.set_xlabel("Degree", fontsize=9)
        ax.set_ylabel("Score", fontsize=9)
        ax.grid(True, alpha=0.3)

    fig2.suptitle(f"{exp_id}: Per-Metric Degree Correlation", fontsize=13, fontweight="bold")
    fig2.tight_layout(rect=[0, 0, 1, 0.96])
    all_paths.extend(_save_figure(fig2, figures_dir, f"fig_{exp_id}_2_metric_panels"))
    plt.close(fig2)

    # ── Fig 3: 相関係数サマリバー ──
    if any(len(all_metric_pairs[m][0]) >= 3 for m in plot_metrics):
        fig3, ax3 = plt.subplots(figsize=(8, 5))
        metric_labels: list[str] = []
        rho_values: list[float] = []
        for m in plot_metrics:
            dx, dy = all_metric_pairs[m]
            if len(dx) >= 3:
                rho_m = spearman(dx, dy)
                metric_labels.append(METRIC_SHORT.get(m, m.capitalize()))
                rho_values.append(rho_m)

        if metric_labels:
            colors = ["#16A34A" if abs(v) < 0.3 else "#DC2626" for v in rho_values]
            bars = ax3.bar(metric_labels, [abs(v) for v in rho_values], color=colors, alpha=0.85, edgecolor="white")
            ax3.axhline(0.3, color="#6B7280", linestyle="--", linewidth=1, alpha=0.7, label="|ρ| = 0.3 (weak/moderate)")
            ax3.set_ylabel("|Spearman ρ|", fontsize=11)
            ax3.set_title(f"{exp_id}: Correlation Strength Summary", fontsize=12, fontweight="bold")
            ax3.legend(fontsize=9)
            ax3.grid(axis="y", alpha=0.3)
            ax3.set_ylim(0, max(abs(v) for v in rho_values) * 1.3 if rho_values else 1.0)

            # 値ラベル
            for bar, val in zip(bars, rho_values):
                sign = "+" if val >= 0 else "−"
                ax3.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                    f"{sign}{abs(val):.3f}", ha="center", va="bottom", fontsize=9, fontweight="bold",
                )

            fig3.tight_layout()
            all_paths.extend(_save_figure(fig3, figures_dir, f"fig_{exp_id}_3_correlation_bar"))
            plt.close(fig3)

    # ── Table ──
    _generate_exp208_tables(all_metric_pairs, plot_metrics, figures_dir, exp_id)

    return all_paths


@register("EXP-209")
def vis_exp_209(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-209: 接続性効果 — 交互作用プロット + Δバー。"""
    if not HAS_MPL:
        return []
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    meta = load_experiment_meta(run_dir)
    paper_tiers: dict[str, str] = {}
    for rec in meta.get("records", []):
        paper_id = rec.get("paper_id", "")
        tier = rec.get("tier", rec.get("connectivity_tier", ""))
        if paper_id and tier:
            paper_tiers[paper_id] = tier

    tiers = sorted(set(paper_tiers.values())) or ["low", "medium", "high"]
    per_paper = load_single_scores_per_paper(run_dir)

    method_scores: dict[str, list[float]] = {}
    for cond in conditions:
        tier_means: list[float] = []
        papers = per_paper.get(cond, {})
        for tier in tiers:
            tier_papers = [p for p, t in paper_tiers.items() if t == tier]
            vals = [papers[p].get("overall", 0) for p in tier_papers if p in papers]
            tier_means.append(_safe_mean(vals))
        method_scores[cond] = tier_means

    if not method_scores:
        return all_paths

    # Interaction plot
    fig, ax = plt.subplots(figsize=(10, 6))
    x = list(range(len(tiers)))
    for method, tier_scores in method_scores.items():
        color = STYLE.color_for(method)
        ls = "-" if "ideagraph" in method.lower() else "--"
        ax.plot(x, tier_scores, f"o{ls}", color=color, label=method, linewidth=2, markersize=7)
    ax.set_xticks(x)
    ax.set_xticklabels(tiers, fontsize=10)
    ax.set_xlabel("Connectivity Tier", fontsize=11)
    ax.set_ylabel("Overall Score", fontsize=11)
    ax.set_title(f"{exp_id}: Method × Connectivity Interaction", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    all_paths.extend(_save_figure(fig, figures_dir, f"fig_{exp_id}_1_interaction"))
    plt.close(fig)

    return all_paths


# ══════════════════════════════════════════════════════
# テーブル生成
# ══════════════════════════════════════════════════════


def _generate_sweep_tables(
    sorted_conds: list[str], x_values: list[float],
    scores: dict, output_dir: Path, exp_id: str, xlabel: str,
) -> None:
    """パラメータスイープの Markdown + LaTeX テーブル。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    display_metrics = METRICS + ["overall"]

    # Markdown
    header = f"| {xlabel} | " + " | ".join(METRIC_SHORT.get(m, m) for m in display_metrics) + " |"
    sep = "|-------:|" + "|".join("--------:" for _ in display_metrics) + "|"
    rows = []
    for x, cond in zip(x_values, sorted_conds):
        x_label = str(int(x)) if x == int(x) else f"{x:.1f}"
        vals = [f"{_safe_mean(scores[cond].get(m, [])):.2f}" for m in display_metrics]
        rows.append(f"| {x_label} | " + " | ".join(vals) + " |")

    md = f"## {exp_id}: {xlabel} Ablation\n\n{header}\n{sep}\n" + "\n".join(rows) + "\n"
    (output_dir / f"table_{exp_id}.md").write_text(md, encoding="utf-8")

    # LaTeX
    col_spec = "r" + "r" * len(display_metrics)
    header_tex = " & ".join([xlabel] + [METRIC_SHORT.get(m, m) for m in display_metrics]) + r" \\"
    tex_rows = []
    for x, cond in zip(x_values, sorted_conds):
        x_label = str(int(x)) if x == int(x) else f"{x:.1f}"
        vals = [f"{_safe_mean(scores[cond].get(m, [])):.2f}" for m in display_metrics]
        tex_rows.append(f"  {x_label} & " + " & ".join(vals) + r" \\")

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


def _generate_exp208_tables(
    all_metric_pairs: dict, plot_metrics: list[str],
    output_dir: Path, exp_id: str,
) -> None:
    """EXP-208 相関係数テーブル。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from idea_graph.services.aggregator import spearman, pearson
    except ImportError:
        return

    # Markdown
    header = "| Metric | Spearman ρ | Pearson r | n |"
    sep = "|--------|----------:|----------:|--:|"
    rows = []
    for m in plot_metrics:
        dx, dy = all_metric_pairs[m]
        if len(dx) >= 3:
            rho = spearman(dx, dy)
            r = pearson(dx, dy)
            rows.append(f"| {METRIC_SHORT.get(m, m)} | {rho:.3f} | {r:.3f} | {len(dx)} |")

    if rows:
        md = f"## {exp_id}: Degree-Score Correlations\n\n{header}\n{sep}\n" + "\n".join(rows) + "\n"
        (output_dir / f"table_{exp_id}.md").write_text(md, encoding="utf-8")

    # LaTeX
    if rows:
        tex_rows = []
        for m in plot_metrics:
            dx, dy = all_metric_pairs[m]
            if len(dx) >= 3:
                rho = spearman(dx, dy)
                r = pearson(dx, dy)
                tex_rows.append(f"  {METRIC_SHORT.get(m, m)} & {rho:.3f} & {r:.3f} & {len(dx)}" + r" \\")

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
