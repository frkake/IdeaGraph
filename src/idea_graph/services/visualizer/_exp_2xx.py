"""200系: アブレーション実験の専用可視化 (EXP-201〜209)"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._registry import register
from ._style import METRICS, METRIC_SHORT, _safe_mean, _safe_std, _save_figure, HAS_MPL, logger
from ._loaders import (
    load_single_scores,
    load_single_scores_per_paper,
    load_experiment_meta,
    load_metadata,
)
from ._renderers import (
    GroupedBarRenderer,
    MultiLineRenderer,
    HeatmapRenderer,
    ParetoRenderer,
    InteractionPlotRenderer,
    BarRenderer,
)
from ._stats import StatsHelper

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


def _extract_sweep(
    conditions: list[str],
    scores: dict[str, dict[str, list[float]]],
) -> tuple[list[float], list[str]] | None:
    """条件名から数値パラメータを抽出してソートする。"""
    values: list[tuple[float, str]] = []
    for cond in conditions:
        nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
        if nums:
            values.append((float(nums[-1]), cond))
    if len(values) < 3:
        return None
    values.sort(key=lambda x: x[0])
    return [v[0] for v in values], [v[1] for v in values]


def _sweep_multiline(
    run_dir: Path, figures_dir: Path, exp_id: str,
    xlabel: str,
) -> list[Path]:
    """パラメータスイープ実験の共通可視化ロジック。"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    sweep = _extract_sweep(conditions, scores)
    if not sweep:
        return all_paths
    x_values, sorted_conds = sweep

    # --- Fig 1: MultiLine（指標別ライン + SD帯）
    metric_data: dict[str, tuple[list[float], list[float]]] = {}
    for metric in METRICS:
        means = [_safe_mean(scores[c].get(metric, [])) for c in sorted_conds]
        stds = [_safe_std(scores[c].get(metric, [])) for c in sorted_conds]
        metric_data[metric] = (means, stds)
    all_paths.extend(MultiLineRenderer.render(
        x_values, metric_data, figures_dir, exp_id, xlabel=xlabel, fig_num=1,
    ))

    # --- Fig 2: Heatmap（パラメータ×指標、列最適値ハイライト）
    data = []
    for cond in sorted_conds:
        row = [_safe_mean(scores[cond].get(m, [])) for m in METRICS]
        data.append(row)
    row_labels = [str(int(x)) if x == int(x) else str(x) for x in x_values]
    col_labels = [METRIC_SHORT.get(m, m) for m in METRICS]
    all_paths.extend(HeatmapRenderer.render(
        data, row_labels, col_labels, figures_dir, exp_id,
        title=f"{exp_id}: {xlabel} x Metric Scores",
        fig_num=2, highlight_best=True,
    ))

    return all_paths


@register("EXP-201")
def vis_exp_201(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-201: Multi-hop depth (hops=1..5)"""
    return _sweep_multiline(run_dir, figures_dir, exp_id, xlabel="Max Hops")


@register("EXP-202")
def vis_exp_202(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-202: Graph format (mermaid vs paths)"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if len(conditions) < 2:
        return all_paths

    # GroupedBar + 差分注釈
    stats = StatsHelper(run_dir)
    sig_results = stats.per_metric_significance(conditions[0], conditions[1])
    sig_pairs = [
        {"cond_a": s["cond_a"], "cond_b": s["cond_b"],
         "p": s["p"], "d": s["d"], "metric": s["metric"]}
        for s in sig_results if s["metric"] in METRICS
    ]
    all_paths.extend(GroupedBarRenderer.render(
        scores, figures_dir, exp_id, fig_num=1, sig_pairs=sig_pairs,
    ))
    return all_paths


@register("EXP-203")
def vis_exp_203(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-203: Prompt scope (3条件)"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if len(conditions) < 2:
        return all_paths

    # 全ペアの有意差を計算
    all_sig: list[dict] = []
    stats = StatsHelper(run_dir)
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            sig = stats.per_metric_significance(conditions[i], conditions[j])
            for s in sig:
                if s["metric"] in METRICS:
                    all_sig.append({
                        "cond_a": s["cond_a"], "cond_b": s["cond_b"],
                        "p": s["p"], "d": s["d"], "metric": s["metric"],
                    })

    all_paths.extend(GroupedBarRenderer.render(
        scores, figures_dir, exp_id, fig_num=1, sig_pairs=all_sig,
    ))
    return all_paths


@register("EXP-204")
def vis_exp_204(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-204: Path count (3..20)"""
    return _sweep_multiline(run_dir, figures_dir, exp_id, xlabel="Path Count")


@register("EXP-205")
def vis_exp_205(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-205: Graph size (20..full)"""
    return _sweep_multiline(run_dir, figures_dir, exp_id, xlabel="Graph Size (nodes)")


@register("EXP-206")
def vis_exp_206(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-206: Num proposals (1..10) — mean overall + best-of-N"""
    if not HAS_MPL:
        return []
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    sweep = _extract_sweep(conditions, scores)
    if not sweep:
        return all_paths
    x_values, sorted_conds = sweep

    # mean overall と best-of-N を計算
    mean_overall = [_safe_mean(scores[c].get("overall", [])) for c in sorted_conds]

    # best-of-N: 各論文について上位Nの最高値を取る
    per_paper = load_single_scores_per_paper(run_dir)
    best_of_n: list[float] = []
    for cond in sorted_conds:
        papers = per_paper.get(cond, {})
        if papers:
            bests = [p.get("overall", 0) for p in papers.values()]
            best_of_n.append(max(bests) if bests else 0)
        else:
            best_of_n.append(0)

    # Dual-line plot
    from ._style import STYLE, _save_figure

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(x_values, mean_overall, "o-", color="#2563EB", linewidth=2, label="Mean Overall")
    ax.plot(x_values, best_of_n, "s--", color="#DC2626", linewidth=2, label="Best-of-N")
    ax.fill_between(x_values, mean_overall, best_of_n, alpha=0.1, color="#8B5CF6")

    ax.set_xlabel("Num Proposals", fontsize=11)
    ax.set_ylabel("Overall Score", fontsize=11)
    ax.set_title(f"{exp_id}: Mean vs Best-of-N")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    all_paths.extend(_save_figure(fig, figures_dir, f"fig_{exp_id}_1_dual_line"))
    plt.close(fig)
    return all_paths


@register("EXP-207")
def vis_exp_207(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-207: 品質-コスト効率 — Pareto frontier"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if not conditions:
        return all_paths

    # コスト推定: execution_logs があれば使う、なければ条件名から推定
    costs: list[float] = []
    overall_scores: list[float] = []
    labels: list[str] = []

    log_dir = run_dir / "execution_logs"
    for cond in conditions:
        overall_scores.append(_safe_mean(scores[cond].get("overall", [])))
        labels.append(cond)

        # execution_logs/{cond}.json からコスト取得を試みる
        cost = 0.0
        log_file = log_dir / f"{cond}.json" if log_dir.exists() else None
        if log_file and log_file.exists():
            try:
                log_data = json.loads(log_file.read_text(encoding="utf-8"))
                cost = float(log_data.get("total_cost_usd", 0))
            except Exception:
                pass
        if cost == 0:
            # 条件名からパラメータ数を抽出してコスト近似
            nums = re.findall(r"(\d+)", cond)
            cost = sum(float(n) for n in nums) * 0.001 if nums else 0.01
        costs.append(cost)

    all_paths.extend(ParetoRenderer.render(
        costs, overall_scores, labels, figures_dir, exp_id,
    ))
    return all_paths


@register("EXP-208")
def vis_exp_208(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-208: ドメイン汎化 — 接続性tier×指標のGroupedBar"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    if not scores:
        return all_paths

    all_paths.extend(GroupedBarRenderer.render(
        scores, figures_dir, exp_id, fig_num=1,
    ))
    return all_paths


@register("EXP-209")
def vis_exp_209(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-209: 接続性効果 — 交互作用プロット + Δバー"""
    if not HAS_MPL:
        return []
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    # summary.json から target_papers のメタデータ(tier)を取得
    meta = load_experiment_meta(run_dir)
    paper_tiers: dict[str, str] = {}
    for rec in meta.get("records", []):
        paper_id = rec.get("paper_id", "")
        tier = rec.get("tier", rec.get("connectivity_tier", ""))
        if paper_id and tier:
            paper_tiers[paper_id] = tier

    tiers = sorted(set(paper_tiers.values())) or ["low", "medium", "high"]

    # tier別に条件のoverallスコア平均を計算
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

    # --- Fig 1: InteractionPlot
    if method_scores:
        all_paths.extend(InteractionPlotRenderer.render(
            tiers, method_scores, figures_dir, exp_id,
        ))

    # --- Fig 2: Δ bar (差分)
    if len(conditions) >= 2:
        cond_a, cond_b = conditions[0], conditions[1]
        a_means = method_scores.get(cond_a, [])
        b_means = method_scores.get(cond_b, [])
        if a_means and b_means:
            deltas = [a - b for a, b in zip(a_means, b_means)]
            colors = ["#16A34A" if d > 0 else "#DC2626" for d in deltas]
            all_paths.extend(BarRenderer.render(
                tiers, deltas, figures_dir, exp_id,
                ylabel=f"Δ({cond_a} - {cond_b})",
                fig_num=2, colors=colors,
            ))

    return all_paths
