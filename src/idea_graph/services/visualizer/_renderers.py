"""レンダラー（既存10 + 新規4）"""

from __future__ import annotations

from pathlib import Path

from ._style import (
    HAS_MPL,
    METRICS,
    METRIC_SHORT,
    STYLE,
    _p_label,
    _safe_mean,
    _safe_sem,
    _safe_std,
    _save_figure,
)

if HAS_MPL:
    import matplotlib.pyplot as plt
    import numpy as np


# ──────────────────── 既存レンダラー ────────────────────


class BoxPlotRenderer:
    """条件比較の箱ひげ図。"""

    @staticmethod
    def render(
        scores: dict[str, dict[str, list[float]]],
        output_dir: Path,
        exp_id: str,
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        conditions = list(scores.keys())
        if len(conditions) < 2:
            return []

        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        positions = []
        tick_labels = []
        data_groups: list[list[float]] = []
        colors: list[str] = []

        for m_idx, metric in enumerate(METRICS):
            for c_idx, cond in enumerate(conditions):
                pos = m_idx * (len(conditions) + 1) + c_idx
                positions.append(pos)
                tick_labels.append(f"{METRIC_SHORT.get(metric, metric)}\n{cond[:10]}")
                data_groups.append(scores[cond].get(metric, []))
                colors.append(STYLE.color_for(cond))

        bp = ax.boxplot(data_groups, positions=positions, widths=0.6, patch_artist=True)
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.set_xticks(positions)
        ax.set_xticklabels(tick_labels, fontsize=7, rotation=45, ha="right")
        ax.set_ylabel("Score (1-10)")
        ax.set_title(f"{exp_id}: Metric Comparison by Condition")
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_1_boxplot")
        plt.close(fig)
        return paths


class RadarRenderer:
    """レーダーチャート。"""

    @staticmethod
    def render(
        scores: dict[str, dict[str, list[float]]],
        output_dir: Path,
        exp_id: str,
        fig_num: int = 2,
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        conditions = list(scores.keys())
        if not conditions:
            return []

        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE, subplot_kw={"polar": True})
        angles = [n / len(METRICS) * 2 * 3.14159 for n in range(len(METRICS))]
        angles += angles[:1]

        for cond in conditions:
            values = [_safe_mean(scores[cond].get(m, [])) for m in METRICS]
            values += values[:1]
            color = STYLE.color_for(cond)
            ax.plot(angles, values, "o-", linewidth=2, label=cond, color=color)
            ax.fill(angles, values, alpha=0.15, color=color)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([METRIC_SHORT.get(m, m) for m in METRICS])
        ax.set_ylim(0, 10)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
        ax.set_title(f"{exp_id}: Metric Profile")
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_radar")
        plt.close(fig)
        return paths


class LineRenderer:
    """パラメータ-性能曲線（単一ライン）。"""

    @staticmethod
    def render(
        x_values: list[float],
        y_means: list[float],
        y_stds: list[float],
        output_dir: Path,
        exp_id: str,
        xlabel: str = "Parameter",
        ylabel: str = "Overall Score",
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        ax.errorbar(
            x_values, y_means, yerr=y_stds,
            fmt="o-", capsize=5, color=STYLE.COLORS["ideagraph"],
        )
        best_idx = int(max(range(len(y_means)), key=lambda i: y_means[i]))
        ax.annotate(
            "peak", xy=(x_values[best_idx], y_means[best_idx]),
            xytext=(10, 10), textcoords="offset points",
            arrowprops=dict(arrowstyle="->"), fontsize=9,
        )
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{exp_id}: {ylabel} vs {xlabel}")
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_1_line")
        plt.close(fig)
        return paths


class HeatmapRenderer:
    """ヒートマップ。"""

    @staticmethod
    def render(
        data: list[list[float]],
        row_labels: list[str],
        col_labels: list[str],
        output_dir: Path,
        exp_id: str,
        title: str = "",
        fig_num: int = 2,
        highlight_best: bool = False,
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        arr = [[v for v in row] for row in data]
        im = ax.imshow(arr, cmap="YlOrRd", aspect="auto")
        ax.set_xticks(range(len(col_labels)))
        ax.set_xticklabels(col_labels, fontsize=8)
        ax.set_yticks(range(len(row_labels)))
        ax.set_yticklabels(row_labels, fontsize=8)

        for i in range(len(row_labels)):
            for j in range(len(col_labels)):
                val = arr[i][j]
                ax.text(j, i, f"{val:.2f}", ha="center", va="center", fontsize=7)

        if highlight_best and arr:
            for j in range(len(col_labels)):
                col_vals = [arr[i][j] for i in range(len(row_labels))]
                best_i = max(range(len(col_vals)), key=lambda i: col_vals[i])
                ax.add_patch(plt.Rectangle(
                    (j - 0.5, best_i - 0.5), 1, 1,
                    fill=False, edgecolor="lime", linewidth=2,
                ))

        fig.colorbar(im, ax=ax)
        ax.set_title(title or f"{exp_id}: Heatmap")
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_heatmap")
        plt.close(fig)
        return paths


class ScatterRenderer:
    """散布図。"""

    @staticmethod
    def render(
        x: list[float],
        y: list[float],
        output_dir: Path,
        exp_id: str,
        xlabel: str = "X",
        ylabel: str = "Y",
        fig_num: int = 1,
        annotation: str = "",
        diag_line: bool = False,
        threshold_line: float | None = None,
        threshold_label: str = "",
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        ax.scatter(x, y, alpha=0.7, color=STYLE.COLORS["ideagraph"])

        if len(x) >= 2:
            coeffs = np.polyfit(x, y, 1)
            x_line = np.linspace(min(x), max(x), 100)
            y_line = np.polyval(coeffs, x_line)
            ax.plot(x_line, y_line, "--", color="gray", alpha=0.5, label="Regression")

        if diag_line:
            lo = min(min(x, default=0), min(y, default=0))
            hi = max(max(x, default=10), max(y, default=10))
            ax.plot([lo, hi], [lo, hi], ":", color="black", alpha=0.3, label="y=x")

        if threshold_line is not None:
            ax.axhline(threshold_line, color="red", linestyle="--", alpha=0.5,
                       label=threshold_label or f"threshold={threshold_line}")

        if annotation:
            ax.text(
                0.05, 0.95, annotation, transform=ax.transAxes,
                fontsize=10, verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            )

        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{exp_id}: {ylabel} vs {xlabel}")
        if diag_line or threshold_line is not None:
            ax.legend()
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_scatter")
        plt.close(fig)
        return paths


class BarRenderer:
    """棒グラフ。"""

    @staticmethod
    def render(
        labels: list[str],
        values: list[float],
        output_dir: Path,
        exp_id: str,
        ylabel: str = "Value",
        fig_num: int = 1,
        colors: list[str] | None = None,
        threshold_line: float | None = None,
        threshold_label: str = "",
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        bar_colors = colors or [STYLE.color_for(l) for l in labels]
        ax.bar(labels, values, color=bar_colors, alpha=0.8)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{exp_id}: {ylabel}")

        if threshold_line is not None:
            ax.axhline(threshold_line, color="red", linestyle="--", alpha=0.7,
                       label=threshold_label or f"threshold={threshold_line}")
            ax.legend()

        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_bar")
        plt.close(fig)
        return paths


class ParetoRenderer:
    """Pareto frontier プロット。"""

    @staticmethod
    def render(
        costs: list[float],
        scores: list[float],
        labels: list[str],
        output_dir: Path,
        exp_id: str,
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        ax.scatter(costs, scores, color=STYLE.COLORS["ideagraph"], zorder=5)
        for i, label in enumerate(labels):
            ax.annotate(
                label, (costs[i], scores[i]), fontsize=7,
                xytext=(5, 5), textcoords="offset points",
            )

        paired = sorted(zip(costs, scores), key=lambda p: p[0])
        front_x, front_y = [], []
        best = -float("inf")
        for c, s in paired:
            if s >= best:
                front_x.append(c)
                front_y.append(s)
                best = s
        ax.plot(front_x, front_y, "r--", linewidth=2, label="Pareto front")

        ax.set_xlabel("Cost (USD)")
        ax.set_ylabel("Overall Score")
        ax.set_title(f"{exp_id}: Quality-Cost Pareto Frontier")
        ax.legend()
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_1_pareto")
        plt.close(fig)
        return paths


class InteractionPlotRenderer:
    """交互作用プロット。"""

    @staticmethod
    def render(
        tiers: list[str],
        method_scores: dict[str, list[float]],
        output_dir: Path,
        exp_id: str,
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        x = list(range(len(tiers)))
        for method, scores in method_scores.items():
            color = STYLE.color_for(method)
            linestyle = "-" if "ideagraph" in method.lower() else "--"
            ax.plot(x, scores, f"o{linestyle[0]}", color=color, label=method, linewidth=2)
        ax.set_xticks(x)
        ax.set_xticklabels(tiers)
        ax.set_xlabel("Connectivity Tier")
        ax.set_ylabel("Overall Score")
        ax.set_title(f"{exp_id}: Method x Connectivity Interaction")
        ax.legend()
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_1_interaction")
        plt.close(fig)
        return paths


class BlandAltmanRenderer:
    """Bland-Altman プロット。"""

    @staticmethod
    def render(
        human: list[float],
        llm: list[float],
        output_dir: Path,
        exp_id: str,
    ) -> list[Path]:
        if not HAS_MPL or len(human) != len(llm):
            return []
        means = [(h + l) / 2 for h, l in zip(human, llm)]
        diffs = [h - l for h, l in zip(human, llm)]
        mean_diff = _safe_mean(diffs)
        std_diff = _safe_std(diffs)

        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        ax.scatter(means, diffs, alpha=0.7, color=STYLE.COLORS["ideagraph"])
        ax.axhline(mean_diff, color="red", linestyle="-", label=f"Mean diff: {mean_diff:.2f}")
        ax.axhline(mean_diff + 1.96 * std_diff, color="gray", linestyle="--", label="+1.96 SD")
        ax.axhline(mean_diff - 1.96 * std_diff, color="gray", linestyle="--", label="-1.96 SD")
        ax.set_xlabel("Mean of Human & LLM")
        ax.set_ylabel("Human - LLM")
        ax.set_title(f"{exp_id}: Bland-Altman Plot")
        ax.legend()
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_2_bland_altman")
        plt.close(fig)
        return paths


class ConfusionMatrixRenderer:
    """混同行列。"""

    @staticmethod
    def render(
        matrix: list[list[int]],
        labels: list[str],
        output_dir: Path,
        exp_id: str,
        annotation: str = "",
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(matrix, cmap="Blues", aspect="auto")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=9)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, str(matrix[i][j]), ha="center", va="center", fontsize=12)
        fig.colorbar(im, ax=ax)
        ax.set_xlabel("BA Order Winner")
        ax.set_ylabel("AB Order Winner")
        ax.set_title(f"{exp_id}: Position Bias Confusion Matrix")

        if annotation:
            ax.text(
                0.5, -0.15, annotation, transform=ax.transAxes,
                fontsize=10, ha="center",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
            )

        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_1_confusion")
        plt.close(fig)
        return paths


# ──────────────────── 新規レンダラー ────────────────────


class GroupedBarRenderer:
    """N条件を横並びのグループ棒グラフ（エラーバー + 有意差スター + Cohen's d 注釈）。"""

    @staticmethod
    def render(
        scores: dict[str, dict[str, list[float]]],
        output_dir: Path,
        exp_id: str,
        fig_num: int = 1,
        sig_pairs: list[dict] | None = None,
        metrics: list[str] | None = None,
    ) -> list[Path]:
        """
        Args:
            scores: {condition: {metric: [scores]}}
            sig_pairs: [{cond_a, cond_b, p, d, metric}] 有意差ペア情報
            metrics: 表示する指標リスト（デフォルト: METRICS）
        """
        if not HAS_MPL:
            return []
        conditions = list(scores.keys())
        if not conditions:
            return []

        target_metrics = metrics or METRICS
        n_metrics = len(target_metrics)
        n_conds = len(conditions)

        fig, ax = plt.subplots(figsize=(max(8, n_metrics * 2), 5.5))
        bar_width = 0.8 / n_conds
        x_base = np.arange(n_metrics)

        for c_idx, cond in enumerate(conditions):
            means = [_safe_mean(scores[cond].get(m, [])) for m in target_metrics]
            sems = [_safe_sem(scores[cond].get(m, [])) for m in target_metrics]
            offset = (c_idx - (n_conds - 1) / 2) * bar_width
            color = STYLE.color_for(cond)
            ax.bar(
                x_base + offset, means, bar_width * 0.9,
                yerr=sems, capsize=3,
                color=color, alpha=0.85, label=cond,
                error_kw={"linewidth": 1},
            )

        # 有意差アノテーション
        if sig_pairs:
            y_max = ax.get_ylim()[1]
            for sp in sig_pairs:
                metric_name = sp.get("metric", "overall")
                if metric_name not in target_metrics:
                    continue
                m_idx = target_metrics.index(metric_name)
                cond_a = sp.get("cond_a", "")
                cond_b = sp.get("cond_b", "")
                if cond_a not in conditions or cond_b not in conditions:
                    continue
                a_idx = conditions.index(cond_a)
                b_idx = conditions.index(cond_b)
                x1 = m_idx + (a_idx - (n_conds - 1) / 2) * bar_width
                x2 = m_idx + (b_idx - (n_conds - 1) / 2) * bar_width

                p_val = sp.get("p", 1.0)
                d_val = sp.get("d", 0.0)
                label = _p_label(p_val)

                y_bar = y_max * 0.92
                ax.plot([x1, x1, x2, x2], [y_bar - 0.1, y_bar, y_bar, y_bar - 0.1],
                        color="black", linewidth=0.8)
                text = label
                if abs(d_val) > 0.01:
                    text += f"\nd={d_val:.2f}"
                ax.text((x1 + x2) / 2, y_bar + 0.05, text,
                        ha="center", va="bottom", fontsize=7)

        ax.set_xticks(x_base)
        ax.set_xticklabels(
            [METRIC_SHORT.get(m, m) for m in target_metrics],
            fontsize=9,
        )
        ax.set_ylabel("Score (1-10)")
        ax.set_title(f"{exp_id}: Grouped Comparison")
        ax.legend(fontsize=8)
        ax.set_ylim(0, None)
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_grouped_bar")
        plt.close(fig)
        return paths


class StackedBarRenderer:
    """積み上げ棒グラフ。"""

    @staticmethod
    def render(
        categories: list[str],
        stacks: dict[str, list[float]],
        output_dir: Path,
        exp_id: str,
        fig_num: int = 2,
        ylabel: str = "Proportion (%)",
        horizontal: bool = False,
    ) -> list[Path]:
        """
        Args:
            categories: X 軸ラベル
            stacks: {stack_name: [values_per_category]}
        """
        if not HAS_MPL:
            return []
        if not categories or not stacks:
            return []

        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        x = np.arange(len(categories))
        bottom = np.zeros(len(categories))

        stack_colors = ["#2563EB", "#DC2626", "#9CA3AF", "#16A34A", "#F59E0B"]
        for i, (stack_name, values) in enumerate(stacks.items()):
            color = stack_colors[i % len(stack_colors)]
            if horizontal:
                ax.barh(x, values, left=bottom, height=0.6,
                        label=stack_name, color=color, alpha=0.85)
            else:
                ax.bar(x, values, bottom=bottom, width=0.6,
                       label=stack_name, color=color, alpha=0.85)
            # ラベル
            for j, v in enumerate(values):
                if v > 3:  # 小さすぎる値はスキップ
                    pos = bottom[j] + v / 2
                    if horizontal:
                        ax.text(pos, x[j], f"{v:.0f}%", ha="center", va="center", fontsize=7)
                    else:
                        ax.text(x[j], pos, f"{v:.0f}%", ha="center", va="center", fontsize=7)
            bottom += np.array(values)

        if horizontal:
            ax.set_yticks(x)
            ax.set_yticklabels(categories, fontsize=9)
            ax.set_xlabel(ylabel)
        else:
            ax.set_xticks(x)
            ax.set_xticklabels(categories, fontsize=9)
            ax.set_ylabel(ylabel)

        ax.set_title(f"{exp_id}: Distribution")
        ax.legend(fontsize=8, loc="upper right")
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_stacked")
        plt.close(fig)
        return paths


class MultiLineRenderer:
    """指標別の複数ライン + shaded ±1SD バンド、最適点ハイライト。"""

    @staticmethod
    def render(
        x_values: list[float],
        metric_data: dict[str, tuple[list[float], list[float]]],
        output_dir: Path,
        exp_id: str,
        xlabel: str = "Parameter",
        fig_num: int = 1,
    ) -> list[Path]:
        """
        Args:
            x_values: X 軸値
            metric_data: {metric_name: (means, stds)}
        """
        if not HAS_MPL:
            return []
        if not x_values or not metric_data:
            return []

        colors = ["#2563EB", "#DC2626", "#16A34A", "#F59E0B", "#8B5CF6", "#EC4899"]
        fig, ax = plt.subplots(figsize=(10, 6))

        for i, (metric_name, (means, stds)) in enumerate(metric_data.items()):
            color = colors[i % len(colors)]
            label = METRIC_SHORT.get(metric_name, metric_name)
            x_arr = np.array(x_values[:len(means)])
            m_arr = np.array(means)
            s_arr = np.array(stds)

            ax.plot(x_arr, m_arr, "o-", color=color, linewidth=2, label=label)
            ax.fill_between(x_arr, m_arr - s_arr, m_arr + s_arr,
                            alpha=0.15, color=color)

            # 最適点
            best_idx = int(np.argmax(m_arr))
            ax.plot(x_arr[best_idx], m_arr[best_idx], "*",
                    color=color, markersize=12, zorder=5)

        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel("Score (1-10)", fontsize=11)
        ax.set_title(f"{exp_id}: Metrics vs {xlabel}")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_multiline")
        plt.close(fig)
        return paths


class ViolinRenderer:
    """バイオリンプロット。"""

    @staticmethod
    def render(
        group_data: dict[str, list[float]],
        output_dir: Path,
        exp_id: str,
        fig_num: int = 2,
        ylabel: str = "Score (1-10)",
    ) -> list[Path]:
        """
        Args:
            group_data: {group_name: [values]}
        """
        if not HAS_MPL:
            return []
        if not group_data:
            return []

        labels = list(group_data.keys())
        data = [group_data[l] for l in labels]

        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        parts = ax.violinplot(data, showmeans=True, showmedians=True)

        colors = ["#2563EB", "#DC2626", "#16A34A", "#F59E0B", "#8B5CF6"]
        for i, pc in enumerate(parts.get("bodies", [])):
            pc.set_facecolor(colors[i % len(colors)])
            pc.set_alpha(0.7)

        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{exp_id}: Score Distribution")
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_{fig_num}_violin")
        plt.close(fig)
        return paths
