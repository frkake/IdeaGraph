"""100系: システム有効性実験の可視化 (EXP-101, EXP-102)

EXP-101: 3手法 pairwise（ideagraph, direct_llm, coi）→ ELO比較 + 勝率
EXP-102: IdeaGraph vs 元論文 pairwise → レーダーチャート + ランキング
"""

from __future__ import annotations

import json
from pathlib import Path

from ._registry import register
from ._style import METRICS, METRIC_SHORT, STYLE, _safe_mean, _safe_std, _save_figure, HAS_MPL, logger
from ._loaders import load_pairwise_elo_by_source

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# ── ELO データの統合ロード ──


def _load_source_elo_summary(
    run_dir: Path,
) -> dict[str, dict[str, tuple[float, float]]]:
    """ソース別 → 指標別 (mean, std) の ELO サマリを返す。"""
    elo_by_source = load_pairwise_elo_by_source(run_dir)
    summary: dict[str, dict[str, tuple[float, float]]] = {}
    for source, metrics in elo_by_source.items():
        summary[source] = {}
        for m, vals in metrics.items():
            summary[source][m] = (_safe_mean(vals), _safe_std(vals))
    return summary


# ═══════════════════════════════════════════════════════════
# EXP-101: 3手法 pairwise 比較
# ═══════════════════════════════════════════════════════════


@register("EXP-101")
def vis_exp_101(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-101: IdeaGraph vs Direct LLM vs CoI-Agent (Pairwise ELO)"""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    elo_summary = _load_source_elo_summary(run_dir)
    if not elo_summary:
        logger.warning("EXP-101: No pairwise ELO data found")
        return all_paths

    sources = sorted(elo_summary.keys())

    # ── Fig 1: 手法別 ELO スコア (Grouped Bar — 指標×手法) ──
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    display_metrics = METRICS + ["overall"]
    n_metrics = len(display_metrics)
    n_sources = len(sources)
    bar_width = 0.8 / max(n_sources, 1)
    x_base = np.arange(n_metrics)

    for s_idx, source in enumerate(sources):
        means = []
        errs = []
        for m in display_metrics:
            m_mean, m_std = elo_summary[source].get(m, (1000.0, 0.0))
            means.append(m_mean)
            errs.append(m_std)
        offset = (s_idx - (n_sources - 1) / 2) * bar_width
        color = STYLE.color_for(source)
        label = _source_display_name(source)
        ax1.bar(
            x_base + offset, means, bar_width * 0.88,
            yerr=errs, capsize=3, color=color, alpha=0.85,
            label=label, error_kw={"linewidth": 1},
        )

    # Y軸をELO値の範囲にズーム（0始まりだと差が見えない）
    all_means = [elo_summary[s].get(m, (1000, 0))[0] for s in sources for m in display_metrics]
    all_stds = [elo_summary[s].get(m, (1000, 0))[1] for s in sources for m in display_metrics]
    y_min = min(m - s for m, s in zip(all_means, all_stds)) - 30
    y_max = max(m + s for m, s in zip(all_means, all_stds)) + 30
    ax1.set_ylim(y_min, y_max)

    # 基準線 (ELO = 1000)
    ax1.axhline(1000, color="gray", linestyle=":", linewidth=0.8, alpha=0.5)
    ax1.set_xticks(x_base)
    ax1.set_xticklabels([METRIC_SHORT.get(m, m.capitalize()) for m in display_metrics], fontsize=10)
    ax1.set_ylabel("ELO Rating", fontsize=11)
    ax1.set_title(f"{exp_id}: Method Comparison — ELO Scores by Metric", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=9, loc="upper right")
    ax1.grid(axis="y", alpha=0.3)
    fig1.tight_layout()
    all_paths.extend(_save_figure(fig1, figures_dir, f"fig_{exp_id}_1_elo_comparison"))
    plt.close(fig1)

    # ── Fig 2: 勝率サマリ (Win Rate Bar) ──
    # pairwise ranking の rank=1 ソースをカウント
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
            fig2, ax2 = plt.subplots(figsize=(8, 5))
            win_sources = sorted(source_wins.keys())
            win_pcts = [source_wins.get(s, 0) / total_papers * 100 for s in win_sources]
            colors = [STYLE.color_for(s) for s in win_sources]
            labels = [_source_display_name(s) for s in win_sources]
            bars = ax2.bar(labels, win_pcts, color=colors, alpha=0.85, edgecolor="white", linewidth=0.5)

            # 値ラベル
            for bar, pct in zip(bars, win_pcts):
                ax2.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{pct:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold",
                )

            ax2.set_ylabel("Win Rate (%)", fontsize=11)
            ax2.set_title(f"{exp_id}: Top-1 Rank Win Rate", fontsize=12, fontweight="bold")
            ax2.set_ylim(0, max(win_pcts) * 1.2)
            ax2.grid(axis="y", alpha=0.3)
            fig2.tight_layout()
            all_paths.extend(_save_figure(fig2, figures_dir, f"fig_{exp_id}_2_win_rate"))
            plt.close(fig2)

    # ── Fig 3: ELO ヒートマップ (Method × Metric) ──
    fig3, ax3 = plt.subplots(figsize=(9, 4))
    display_labels = [METRIC_SHORT.get(m, m.capitalize()) for m in display_metrics]
    source_labels = [_source_display_name(s) for s in sources]

    matrix = []
    for source in sources:
        row = [elo_summary[source].get(m, (1000, 0))[0] for m in display_metrics]
        matrix.append(row)

    arr = np.array(matrix)
    im = ax3.imshow(arr, cmap="RdYlGn", aspect="auto", vmin=arr.min() - 10, vmax=arr.max() + 10)

    ax3.set_xticks(range(len(display_labels)))
    ax3.set_xticklabels(display_labels, fontsize=10)
    ax3.set_yticks(range(len(source_labels)))
    ax3.set_yticklabels(source_labels, fontsize=10)

    # セル値表示
    for i in range(len(sources)):
        for j in range(len(display_metrics)):
            val = arr[i, j]
            ax3.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=9, fontweight="bold")

    # 列ごと最高値をハイライト
    for j in range(len(display_metrics)):
        best_i = int(np.argmax(arr[:, j]))
        ax3.add_patch(plt.Rectangle(
            (j - 0.5, best_i - 0.5), 1, 1,
            fill=False, edgecolor="#16A34A", linewidth=2.5,
        ))

    fig3.colorbar(im, ax=ax3, label="ELO Rating", shrink=0.8)
    ax3.set_title(f"{exp_id}: ELO Heatmap — Method × Metric", fontsize=12, fontweight="bold")
    fig3.tight_layout()
    all_paths.extend(_save_figure(fig3, figures_dir, f"fig_{exp_id}_3_elo_heatmap"))
    plt.close(fig3)

    # ── Table (Markdown + LaTeX) ──
    _generate_exp101_tables(elo_summary, sources, figures_dir, exp_id)

    return all_paths


# ═══════════════════════════════════════════════════════════
# EXP-102: IdeaGraph vs 元論文
# ═══════════════════════════════════════════════════════════


@register("EXP-102")
def vis_exp_102(run_dir: Path, figures_dir: Path, exp_id: str) -> list[Path]:
    """EXP-102: IdeaGraph vs Target Paper — レーダーチャート + ランキング"""
    if not HAS_MPL:
        return []

    all_paths: list[Path] = []
    elo_summary = _load_source_elo_summary(run_dir)
    if not elo_summary:
        logger.warning("EXP-102: No pairwise ELO data found")
        return all_paths

    sources = sorted(elo_summary.keys())

    # ── Fig 1: レーダーチャート (5メトリクス比較) ──
    fig1, ax1 = plt.subplots(figsize=(8, 8), subplot_kw={"polar": True})

    angles = [n / len(METRICS) * 2 * np.pi for n in range(len(METRICS))]
    angles += angles[:1]  # 閉じる

    for source in sources:
        values = [elo_summary[source].get(m, (1000, 0))[0] for m in METRICS]
        values += values[:1]
        color = STYLE.color_for(source)
        label = _source_display_name(source)
        ax1.plot(angles, values, "o-", linewidth=2.5, label=label, color=color, markersize=6)
        ax1.fill(angles, values, alpha=0.15, color=color)

    ax1.set_xticks(angles[:-1])
    ax1.set_xticklabels(
        [METRIC_SHORT.get(m, m.capitalize()) for m in METRICS],
        fontsize=12, fontweight="bold",
    )

    # Y軸の範囲を調整
    all_vals = [elo_summary[s].get(m, (1000, 0))[0] for s in sources for m in METRICS]
    if all_vals:
        ymin = min(all_vals) - 30
        ymax = max(all_vals) + 30
        ax1.set_ylim(ymin, ymax)

    ax1.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=10)
    ax1.set_title(
        f"{exp_id}: Metric Profile — IdeaGraph vs Target Paper",
        fontsize=13, fontweight="bold", pad=20,
    )
    fig1.tight_layout()
    all_paths.extend(_save_figure(fig1, figures_dir, f"fig_{exp_id}_1_radar"))
    plt.close(fig1)

    # ── Fig 2: ランキング ELO バー (Target Paper ハイライト) ──
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    overall_elos = [(s, elo_summary[s].get("overall", (1000, 0))) for s in sources]
    overall_elos.sort(key=lambda x: x[1][0], reverse=True)

    bar_labels = [_source_display_name(s) for s, _ in overall_elos]
    bar_vals = [v[0] for _, v in overall_elos]
    bar_errs = [v[1] for _, v in overall_elos]
    bar_colors = []
    for s, _ in overall_elos:
        if "target" in s.lower():
            bar_colors.append(STYLE.COLORS.get("target_paper", "#F59E0B"))
        else:
            bar_colors.append(STYLE.color_for(s))

    bars = ax2.barh(
        range(len(bar_labels)), bar_vals, xerr=bar_errs,
        color=bar_colors, alpha=0.85, edgecolor="white", linewidth=0.5, capsize=3,
    )
    ax2.set_yticks(range(len(bar_labels)))
    ax2.set_yticklabels(bar_labels, fontsize=10)
    ax2.set_xlabel("Overall ELO Rating", fontsize=11)
    ax2.axvline(1000, color="gray", linestyle=":", linewidth=0.8, alpha=0.5)
    ax2.set_title(f"{exp_id}: Overall ELO Ranking", fontsize=12, fontweight="bold")

    # X軸をELO値の範囲にズーム
    x_min = min(v - e for v, e in zip(bar_vals, bar_errs)) - 30
    x_max = max(v + e for v, e in zip(bar_vals, bar_errs)) + 30
    ax2.set_xlim(x_min, x_max)

    # 値ラベル
    for bar, val in zip(bars, bar_vals):
        ax2.text(
            val + (x_max - x_min) * 0.02, bar.get_y() + bar.get_height() / 2,
            f"{val:.0f}", va="center", fontsize=9, fontweight="bold",
        )

    ax2.invert_yaxis()
    ax2.grid(axis="x", alpha=0.3)
    fig2.tight_layout()
    all_paths.extend(_save_figure(fig2, figures_dir, f"fig_{exp_id}_2_elo_ranking"))
    plt.close(fig2)

    # ── Table (Markdown + LaTeX) ──
    _generate_exp102_tables(elo_summary, sources, figures_dir, exp_id)

    return all_paths


# ═══════════════════════════════════════════════════════════
# テーブル生成
# ═══════════════════════════════════════════════════════════


def _generate_exp101_tables(
    elo_summary: dict, sources: list[str], output_dir: Path, exp_id: str,
) -> None:
    """EXP-101 の Markdown + LaTeX テーブルを生成する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    display_metrics = METRICS + ["overall"]

    # Markdown
    header = "| Method | " + " | ".join(METRIC_SHORT.get(m, m) for m in display_metrics) + " |"
    sep = "|--------|" + "|".join("--------:" for _ in display_metrics) + "|"
    rows = []
    for s in sources:
        name = _source_display_name(s)
        vals = [f"{elo_summary[s].get(m, (0, 0))[0]:.0f}" for m in display_metrics]
        rows.append(f"| {name} | " + " | ".join(vals) + " |")

    md_content = f"## {exp_id}: ELO Scores by Method\n\n{header}\n{sep}\n" + "\n".join(rows) + "\n"
    (output_dir / f"table_{exp_id}.md").write_text(md_content, encoding="utf-8")

    # LaTeX
    col_spec = "l" + "r" * len(display_metrics)
    header_tex = " & ".join(["Method"] + [METRIC_SHORT.get(m, m) for m in display_metrics]) + r" \\"
    tex_rows = []
    for s in sources:
        name = _source_display_name(s)
        vals = [f"{elo_summary[s].get(m, (0, 0))[0]:.0f}" for m in display_metrics]
        tex_rows.append(f"  {name} & " + " & ".join(vals) + r" \\")

    tex_content = (
        r"\begin{table}[htbp]" + "\n"
        r"  \centering" + "\n"
        f"  \\caption{{{exp_id}: ELO Scores by Method}}\n"
        f"  \\begin{{tabular}}{{{col_spec}}}\n"
        r"    \toprule" + "\n"
        f"    {header_tex}\n"
        r"    \midrule" + "\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        r"    \bottomrule" + "\n"
        r"  \end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex_content, encoding="utf-8")


def _generate_exp102_tables(
    elo_summary: dict, sources: list[str], output_dir: Path, exp_id: str,
) -> None:
    """EXP-102 の Markdown + LaTeX テーブルを生成する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    display_metrics = METRICS + ["overall"]

    # Markdown
    header = "| Source | " + " | ".join(METRIC_SHORT.get(m, m) for m in display_metrics) + " |"
    sep = "|--------|" + "|".join("--------:" for _ in display_metrics) + "|"
    rows = []
    for s in sources:
        name = _source_display_name(s)
        vals = [f"{elo_summary[s].get(m, (0, 0))[0]:.0f}" for m in display_metrics]
        rows.append(f"| {name} | " + " | ".join(vals) + " |")

    md_content = f"## {exp_id}: IdeaGraph vs Target Paper\n\n{header}\n{sep}\n" + "\n".join(rows) + "\n"
    (output_dir / f"table_{exp_id}.md").write_text(md_content, encoding="utf-8")

    # LaTeX
    col_spec = "l" + "r" * len(display_metrics)
    header_tex = " & ".join(["Source"] + [METRIC_SHORT.get(m, m) for m in display_metrics]) + r" \\"
    tex_rows = []
    for s in sources:
        name = _source_display_name(s)
        vals = [f"{elo_summary[s].get(m, (0, 0))[0]:.0f}" for m in display_metrics]
        tex_rows.append(f"  {name} & " + " & ".join(vals) + r" \\")

    tex_content = (
        r"\begin{table}[htbp]" + "\n"
        r"  \centering" + "\n"
        f"  \\caption{{{exp_id}: IdeaGraph vs Target Paper ELO Scores}}\n"
        f"  \\begin{{tabular}}{{{col_spec}}}\n"
        r"    \toprule" + "\n"
        f"    {header_tex}\n"
        r"    \midrule" + "\n"
        + "\n".join(f"    {r}" for r in tex_rows) + "\n"
        r"    \bottomrule" + "\n"
        r"  \end{tabular}" + "\n"
        r"\end{table}" + "\n"
    )
    (output_dir / f"table_{exp_id}.tex").write_text(tex_content, encoding="utf-8")


# ── ヘルパー ──


def _source_display_name(source: str) -> str:
    """ソース名を表示用に変換する。"""
    name_map = {
        "ideagraph": "IdeaGraph",
        "ideagraph_default": "IdeaGraph",
        "direct_llm": "Direct LLM",
        "direct_llm_baseline": "Direct LLM",
        "coi": "CoI-Agent",
        "coi_agent": "CoI-Agent",
        "target_paper": "Target Paper",
    }
    return name_map.get(source.lower(), source)
