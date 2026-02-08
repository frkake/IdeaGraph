"""300系: 評価妥当性実験の専用可視化 (EXP-301〜306)"""

from __future__ import annotations

import json
from pathlib import Path

from ._registry import register
from ._style import METRICS, METRIC_SHORT, _safe_mean, _safe_std, HAS_MPL, logger
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
from ._renderers import (
    ScatterRenderer,
    BarRenderer,
    ConfusionMatrixRenderer,
    HeatmapRenderer,
    ViolinRenderer,
    BlandAltmanRenderer,
    GroupedBarRenderer,
    StackedBarRenderer,
)
from ._stats import StatsHelper

from idea_graph.services.aggregator import spearman, pearson


@register("EXP-301")
def vis_exp_301(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-301: Pairwise vs Single 整合性 — Scatter + 回帰線 + Spearman ρ 注釈"""
    all_paths: list[Path] = []

    # Single overall スコア（論文別）
    per_paper = load_single_scores_per_paper(run_dir)
    # Pairwise ELO（論文別）
    pairwise_files = load_pairwise_details(run_dir)

    # 各論文・条件について Single overall と Pairwise ELO を対応付ける
    single_vals: list[float] = []
    pairwise_vals: list[float] = []

    for pw_data in pairwise_files:
        ranking = pw_data.get("ranking", [])
        for entry in ranking:
            source = str(entry.get("source", ""))
            elo = entry.get("elo_rating")
            if elo is None:
                # ELO がない場合は rank の逆数をプロキシとして使用
                rank = entry.get("rank", 1)
                elo = 1500 - (rank - 1) * 100

            # 対応する Single スコアを探す
            for cond, papers in per_paper.items():
                if source and source in cond:
                    for paper_id, paper_scores in papers.items():
                        overall = paper_scores.get("overall")
                        if overall is not None:
                            single_vals.append(overall)
                            pairwise_vals.append(float(elo))
                    break

    if len(single_vals) >= 3:
        rho = spearman(single_vals, pairwise_vals)
        annotation = f"Spearman ρ = {rho:.3f}"
        all_paths.extend(ScatterRenderer.render(
            single_vals, pairwise_vals, figures_dir, exp_id,
            xlabel="Single Overall Score",
            ylabel="Pairwise ELO Rating",
            fig_num=1,
            annotation=annotation,
            threshold_line=None,
        ))

    return all_paths


@register("EXP-302")
def vis_exp_302(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-302: 再現性 — Krippendorff's α per metric + 閾値線"""
    all_paths: list[Path] = []

    # aggregate.json から alpha 取得
    agg = load_aggregate(run_dir)
    irr = agg.get("inter_rater_reliability", {})

    if not irr:
        # まだ集計されていない場合は StatsHelper 経由
        stats = StatsHelper(run_dir)
        irr_data = stats.irr_alphas()
        if irr_data:
            # 最初の条件を使う
            for cond_name, alphas in irr_data.items():
                irr = {cond_name: {"krippendorffs_alpha": alphas}}
                break

    # 条件ごとにバーチャートを生成
    for cond_name, cond_data in irr.items():
        alphas = cond_data.get("krippendorffs_alpha", {})
        if not alphas:
            continue

        labels = [METRIC_SHORT.get(m, m) for m in METRICS if m in alphas]
        values = [alphas[m] for m in METRICS if m in alphas]
        if "overall" in alphas:
            labels.append("Overall")
            values.append(alphas["overall"])

        # pass/fail 色分け（α ≥ 0.9 = green、< 0.9 = red）
        colors = ["#16A34A" if v >= 0.9 else "#DC2626" for v in values]

        all_paths.extend(BarRenderer.render(
            labels, values, figures_dir, exp_id,
            ylabel="Krippendorff's α",
            fig_num=1, colors=colors,
            threshold_line=0.9, threshold_label="α = 0.9 threshold",
        ))

    return all_paths


@register("EXP-303")
def vis_exp_303(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-303: ポジションバイアス — ConfusionMatrix + フリップ率バー"""
    all_paths: list[Path] = []

    swap_data = load_pairwise_swap_data(run_dir)
    if not swap_data:
        # swap_test フィールドがない場合は pairwise ファイルから推定
        logger.info("%s: No swap_test data found", exp_id)
        return all_paths

    # 全条件のユニークなソースを収集
    sources = set()
    for paper_id, info in swap_data.items():
        sources.add(info.get("ab_winner", ""))
        sources.add(info.get("ba_winner", ""))
    sources.discard("")
    source_list = sorted(sources)

    if len(source_list) < 2:
        return all_paths

    # --- Fig 1: ConfusionMatrix
    n = len(source_list)
    matrix = [[0] * n for _ in range(n)]
    total = 0
    consistent = 0

    for paper_id, info in swap_data.items():
        ab = info.get("ab_winner", "")
        ba = info.get("ba_winner", "")
        if ab in source_list and ba in source_list:
            i = source_list.index(ab)
            j = source_list.index(ba)
            matrix[i][j] += 1
            total += 1
            if ab == ba:
                consistent += 1

    agree_rate = consistent / total * 100 if total > 0 else 0
    annotation = f"Agreement: {agree_rate:.1f}% ({consistent}/{total})"

    all_paths.extend(ConfusionMatrixRenderer.render(
        matrix, source_list, figures_dir, exp_id, annotation=annotation,
    ))

    # --- Fig 2: 指標別フリップ率
    # pairwise 詳細からフリップ率を計算
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

    labels = [METRIC_SHORT.get(m, m) for m in METRICS if metric_totals.get(m, 0) > 0]
    values = [
        metric_flips[m] / metric_totals[m] * 100
        for m in METRICS if metric_totals.get(m, 0) > 0
    ]
    if labels:
        all_paths.extend(BarRenderer.render(
            labels, values, figures_dir, exp_id,
            ylabel="Flip Rate (%)", fig_num=2,
        ))

    return all_paths


@register("EXP-304")
def vis_exp_304(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-304: クロスモデル整合性 — モデル間相関 Heatmap + Violin"""
    all_paths: list[Path] = []

    model_scores = load_multi_model_scores(run_dir)
    models = sorted(model_scores.keys())

    if len(models) < 2:
        return all_paths

    # 各モデルの overall スコアリストを取得
    model_overalls: dict[str, list[float]] = {}
    for model in models:
        all_overalls: list[float] = []
        for cond_scores in model_scores[model].values():
            all_overalls.extend(cond_scores.get("overall", []))
        model_overalls[model] = all_overalls

    # --- Fig 1: Heatmap（モデル間 Spearman ρ 相関行列）
    n = len(models)
    corr_matrix: list[list[float]] = []
    for i in range(n):
        row: list[float] = []
        for j in range(n):
            a = model_overalls[models[i]]
            b = model_overalls[models[j]]
            min_len = min(len(a), len(b))
            if min_len >= 2:
                rho = spearman(a[:min_len], b[:min_len])
            else:
                rho = 1.0 if i == j else 0.0
            row.append(rho)
        corr_matrix.append(row)

    # モデル名を短くする
    short_models = [m.split("/")[-1][:20] for m in models]
    all_paths.extend(HeatmapRenderer.render(
        corr_matrix, short_models, short_models, figures_dir, exp_id,
        title=f"{exp_id}: Inter-Model Spearman ρ",
        fig_num=1,
    ))

    # --- Fig 2: Violin（モデル別スコア分布）
    violin_data = {m.split("/")[-1][:20]: model_overalls[m] for m in models}
    all_paths.extend(ViolinRenderer.render(
        violin_data, figures_dir, exp_id, fig_num=2,
    ))

    return all_paths


@register("EXP-305")
def vis_exp_305(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-305: 人間-LLM相関 — BlandAltman + Scatter"""
    all_paths: list[Path] = []

    # human_eval.csv を探す
    human_csv = run_dir / "human_eval.csv"
    if not human_csv.exists():
        human_csv = run_dir / "evaluations" / "human_eval.csv"
    if not human_csv.exists():
        logger.info("%s: No human evaluation CSV found", exp_id)
        return all_paths

    # human CSV をロード
    from idea_graph.services.aggregator import ExperimentAggregator
    agg = ExperimentAggregator()
    human_records = agg.load_human_eval(human_csv)

    if not human_records:
        return all_paths

    # LLM single スコアをロード
    per_paper = load_single_scores_per_paper(run_dir)

    human_scores: list[float] = []
    llm_scores: list[float] = []

    for rec in human_records:
        proposal_id = str(rec.get("proposal_id", ""))
        human_metrics = [rec.get(m) for m in METRICS]
        valid = [float(v) for v in human_metrics if isinstance(v, (int, float))]
        if not valid:
            continue
        human_mean = sum(valid) / len(valid)

        # LLM スコアとのマッチング
        for cond, papers in per_paper.items():
            for paper_id, scores in papers.items():
                if proposal_id in paper_id or paper_id in proposal_id:
                    llm_overall = scores.get("overall")
                    if llm_overall is not None:
                        human_scores.append(human_mean)
                        llm_scores.append(llm_overall)
                    break

    if len(human_scores) < 3:
        return all_paths

    # --- Fig 1: BlandAltman
    all_paths.extend(BlandAltmanRenderer.render(
        human_scores, llm_scores, figures_dir, exp_id,
    ))

    # --- Fig 2: Scatter + Pearson r
    r = pearson(human_scores, llm_scores)
    annotation = f"Pearson r = {r:.3f}"
    all_paths.extend(ScatterRenderer.render(
        human_scores, llm_scores, figures_dir, exp_id,
        xlabel="Human Score",
        ylabel="LLM Score",
        fig_num=2,
        annotation=annotation,
        diag_line=True,
    ))

    return all_paths


@register("EXP-306")
def vis_exp_306(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-306: 根拠トレーサビリティ — GroupedBar + StackedBar"""
    all_paths: list[Path] = []
    scores = load_single_scores(run_dir)
    conditions = list(scores.keys())

    if len(conditions) < 2:
        return all_paths

    # --- Fig 1: GroupedBar（grounding rate比較 + 有意差）
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

    # --- Fig 2: StackedBar（full/partial/none カテゴリ比率）
    # grounding 分析ファイルを探す
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

            # パーセンテージに変換
            for i in range(len(categories)):
                total = full_vals[i] + partial_vals[i] + none_vals[i]
                if total > 0:
                    full_vals[i] = full_vals[i] / total * 100
                    partial_vals[i] = partial_vals[i] / total * 100
                    none_vals[i] = none_vals[i] / total * 100

            stacks = {
                "Full": full_vals,
                "Partial": partial_vals,
                "None": none_vals,
            }
            all_paths.extend(StackedBarRenderer.render(
                categories, stacks, figures_dir, exp_id,
                fig_num=2, ylabel="Grounding Rate (%)",
            ))
        except Exception:
            pass

    return all_paths
