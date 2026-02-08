"""100系: システム有効性実験の専用可視化 (EXP-101, 102, 103)"""

from __future__ import annotations

import json
from pathlib import Path

from ._registry import register
from ._style import METRICS, METRIC_SHORT, _safe_mean, _safe_std, HAS_MPL, logger
from ._loaders import (
    load_single_scores,
    load_single_scores_per_paper,
    load_pairwise_wins,
)
from ._renderers import GroupedBarRenderer, StackedBarRenderer, ScatterRenderer, RadarRenderer
from ._stats import StatsHelper


def _two_condition_vis(
    run_dir: Path, figures_dir: Path, exp_id: str,
    color_hint: str = "ideagraph",
) -> list[Path]:
    """EXP-101/102 共通の2条件比較可視化。"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())
    if len(conditions) < 2:
        logger.warning("%s: need 2+ conditions, got %d", exp_id, len(conditions))
        return all_paths

    cond_a, cond_b = conditions[0], conditions[1]

    # --- Fig 1: GroupedBar（指標別 mean±SEM + 有意差スター + Cohen's d）
    stats = StatsHelper(run_dir)
    sig_results = stats.per_metric_significance(cond_a, cond_b)
    sig_pairs = [
        {"cond_a": s["cond_a"], "cond_b": s["cond_b"],
         "p": s["p"], "d": s["d"], "metric": s["metric"]}
        for s in sig_results if s["metric"] in METRICS
    ]
    all_paths.extend(GroupedBarRenderer.render(
        scores, figures_dir, exp_id, fig_num=1, sig_pairs=sig_pairs,
    ))

    # --- Fig 2: StackedBar（Pairwise 勝率 win/loss/tie）
    wins = load_pairwise_wins(run_dir)
    if wins:
        total = sum(wins.values())
        if total > 0:
            categories = [cond_a]
            win_pct = wins.get(cond_a, 0) / total * 100
            loss_pct = wins.get(cond_b, 0) / total * 100
            tie_pct = 100 - win_pct - loss_pct
            stacks = {
                "Win": [win_pct],
                "Loss": [loss_pct],
                "Tie": [max(0, tie_pct)],
            }
            all_paths.extend(StackedBarRenderer.render(
                categories, stacks, figures_dir, exp_id,
                fig_num=2, ylabel="Rate (%)", horizontal=True,
            ))

    # --- Fig 3: Scatter（論文別 overall score 対角線プロット）
    per_paper = load_single_scores_per_paper(run_dir)
    a_papers = per_paper.get(cond_a, {})
    b_papers = per_paper.get(cond_b, {})
    common = sorted(set(a_papers) & set(b_papers))
    if common:
        x = [a_papers[p].get("overall", 0) for p in common]
        y = [b_papers[p].get("overall", 0) for p in common]
        corr = stats.correlation(x, y)
        annotation = f"r={corr['pearson_r']:.2f}, n={int(corr['n'])}"
        all_paths.extend(ScatterRenderer.render(
            x, y, figures_dir, exp_id,
            xlabel=f"{cond_a} Overall", ylabel=f"{cond_b} Overall",
            fig_num=3, diag_line=True, annotation=annotation,
        ))

    return all_paths


@register("EXP-101")
def vis_exp_101(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-101: IdeaGraph vs Direct LLM"""
    return _two_condition_vis(run_dir, figures_dir, exp_id, color_hint="ideagraph")


@register("EXP-102")
def vis_exp_102(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-102: IdeaGraph vs CoI-Agent"""
    return _two_condition_vis(run_dir, figures_dir, exp_id, color_hint="coi")


@register("EXP-103")
def vis_exp_103(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-103: 生成アイデア vs 元論文（ペアワイズランキング分析）"""
    all_paths: list[Path] = []

    # ペアワイズ結果から順位分布を集計
    pairwise_dir = run_dir / "evaluations" / "pairwise"
    if not pairwise_dir.exists():
        return all_paths

    # 各ファイルのランキングからソース別順位分布を集計
    rank_counts: dict[str, dict[int, int]] = {}  # source -> {rank: count}
    for f in sorted(pairwise_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for entry in data.get("ranking", []):
                source = str(entry.get("source", "unknown"))
                rank = entry.get("rank", 0)
                is_target = entry.get("is_target_paper", False)
                label = "Target Paper" if is_target else source
                rank_counts.setdefault(label, {})
                rank_counts[label][rank] = rank_counts[label].get(rank, 0) + 1
        except Exception:
            continue

    if not rank_counts:
        return all_paths

    # --- Fig 1: StackedBar（元論文の順位分布）
    target_ranks = rank_counts.get("Target Paper", {})
    if target_ranks:
        max_rank = max(target_ranks.keys(), default=4)
        categories = [f"#{r}" for r in range(1, max_rank + 1)]
        total = sum(target_ranks.values())
        if total > 0:
            values = [target_ranks.get(r, 0) / total * 100 for r in range(1, max_rank + 1)]
            stacks = {"Target Paper": values}
            all_paths.extend(StackedBarRenderer.render(
                categories, stacks, figures_dir, exp_id,
                fig_num=1, ylabel="Frequency (%)",
            ))

    # --- Fig 2: Radar（生成提案 vs 元論文のメトリックプロファイル）
    scores = load_single_scores(run_dir)
    if scores:
        all_paths.extend(RadarRenderer.render(scores, figures_dir, exp_id, fig_num=2))

    return all_paths
