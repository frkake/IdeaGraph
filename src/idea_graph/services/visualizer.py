"""実験結果の可視化サービス (PLAN 9.1)"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    import numpy as np

    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import seaborn as sns

    HAS_SNS = True
except ImportError:
    HAS_SNS = False


# ────────────────────────── 共通スタイル ──────────────────────────

@dataclass(frozen=True)
class ChartStyle:
    COLORS: dict[str, str] = field(default_factory=lambda: {
        "ideagraph": "#2563EB",
        "ideagraph_default": "#2563EB",
        "direct_llm": "#DC2626",
        "direct_llm_baseline": "#DC2626",
        "coi": "#16A34A",
        "coi_agent": "#16A34A",
        "target_paper": "#F59E0B",
    })
    DPI: int = 300
    SINGLE_SIZE: tuple[float, float] = (8.0, 5.0)
    DOUBLE_SIZE: tuple[float, float] = (12.0, 5.0)
    MATRIX_SIZE: tuple[float, float] = (10.0, 8.0)

    def color_for(self, name: str) -> str:
        lower = name.lower()
        for key, color in self.COLORS.items():
            if key in lower:
                return color
        palette = ["#2563EB", "#DC2626", "#16A34A", "#F59E0B", "#8B5CF6"]
        return palette[hash(name) % len(palette)]


STYLE = ChartStyle()
METRICS = ["novelty", "significance", "feasibility", "clarity", "effectiveness"]
METRIC_SHORT = {"novelty": "Nov", "significance": "Sig", "feasibility": "Fea",
                "clarity": "Cla", "effectiveness": "Eff"}

_P_ANNOTATIONS = {0.001: "***", 0.01: "**", 0.05: "*"}


def _p_label(p: float) -> str:
    for threshold, label in _P_ANNOTATIONS.items():
        if p < threshold:
            return label
    return "ns"


# ────────────────────────── データ読み込み ──────────────────────────

def _load_single_scores(run_dir: Path) -> dict[str, dict[str, list[float]]]:
    """条件別 → 指標別スコアリストを返す。"""
    result: dict[str, dict[str, list[float]]] = {}
    single_root = run_dir / "evaluations" / "single"
    if not single_root.exists():
        return result
    for condition_dir in sorted(single_root.iterdir()):
        if not condition_dir.is_dir():
            continue
        scores: dict[str, list[float]] = {m: [] for m in METRICS}
        scores["overall"] = []
        for f in sorted(condition_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for entry in data.get("ranking", []):
                    for s in entry.get("scores", []):
                        metric = s.get("metric", "")
                        score = s.get("score")
                        if metric in scores and score is not None:
                            scores[metric].append(float(score))
                    overall = entry.get("overall_score")
                    if overall is not None:
                        scores["overall"].append(float(overall))
            except Exception:
                continue
        result[condition_dir.name] = scores
    return result


def _load_pairwise_wins(run_dir: Path) -> dict[str, int]:
    """ソース別勝利回数を返す。"""
    wins: dict[str, int] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return wins
    for f in sorted(root.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ranking = data.get("ranking", [])
            if ranking:
                source = str(ranking[0].get("source", "unknown"))
                wins[source] = wins.get(source, 0) + 1
        except Exception:
            continue
    return wins


def _load_experiment_meta(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {}


# ────────────────────────── レンダラー ──────────────────────────

class BoxPlotRenderer:
    """条件比較の箱ひげ図。"""

    @staticmethod
    def render(scores: dict[str, dict[str, list[float]]], output_dir: Path, exp_id: str) -> list[Path]:
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
    def render(scores: dict[str, dict[str, list[float]]], output_dir: Path, exp_id: str) -> list[Path]:
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

        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_2_radar")
        plt.close(fig)
        return paths


class LineRenderer:
    """パラメータ-性能曲線。"""

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
        ax.errorbar(x_values, y_means, yerr=y_stds, fmt="o-", capsize=5, color=STYLE.COLORS["ideagraph"])
        best_idx = int(max(range(len(y_means)), key=lambda i: y_means[i]))
        ax.annotate("peak", xy=(x_values[best_idx], y_means[best_idx]),
                     xytext=(10, 10), textcoords="offset points",
                     arrowprops=dict(arrowstyle="->"), fontsize=9)
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
                ax.text(j, i, f"{arr[i][j]:.1f}", ha="center", va="center", fontsize=7)
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
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        ax.scatter(x, y, alpha=0.7, color=STYLE.COLORS["ideagraph"])
        if len(x) >= 2:
            coeffs = np.polyfit(x, y, 1)
            x_line = np.linspace(min(x), max(x), 100)
            y_line = np.polyval(coeffs, x_line)
            ax.plot(x_line, y_line, "--", color="gray", alpha=0.5)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{exp_id}: {ylabel} vs {xlabel}")
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
    ) -> list[Path]:
        if not HAS_MPL:
            return []
        fig, ax = plt.subplots(figsize=STYLE.SINGLE_SIZE)
        bar_colors = colors or [STYLE.color_for(l) for l in labels]
        ax.bar(labels, values, color=bar_colors, alpha=0.8)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{exp_id}: {ylabel}")
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
            ax.annotate(label, (costs[i], scores[i]), fontsize=7,
                         xytext=(5, 5), textcoords="offset points")

        # Pareto front
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
        fig.tight_layout()
        paths = _save_figure(fig, output_dir, f"fig_{exp_id}_1_confusion")
        plt.close(fig)
        return paths


# ────────────────────────── ヘルパー ──────────────────────────

def _safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _safe_std(vals: list[float]) -> float:
    if len(vals) <= 1:
        return 0.0
    m = _safe_mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def _save_figure(fig, output_dir: Path, name: str) -> list[Path]:
    """PNG + SVG で保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ["png", "svg"]:
        path = output_dir / f"{name}.{ext}"
        fig.savefig(str(path), dpi=STYLE.DPI if ext == "png" else None, bbox_inches="tight")
        paths.append(path)
    return paths


# ────────────────────────── メインビジュアライザ ──────────────────────────

class ExperimentVisualizer:
    """メインエントリポイント: run_dir から適切なチャートを自動生成する。"""

    def visualize(self, run_dir: str | Path) -> list[Path]:
        if not HAS_MPL:
            logger.warning("matplotlib not installed. Skipping visualization.")
            return []

        run_path = Path(run_dir)
        figures_dir = run_path / "figures"
        meta = _load_experiment_meta(run_path)
        exp_id = meta.get("experiment_id", run_path.name.split("_")[0])

        scores = _load_single_scores(run_path)
        all_paths: list[Path] = []

        if not scores:
            logger.info("No single evaluation scores found for visualization.")
            return all_paths

        conditions = list(scores.keys())

        # 箱ひげ図（2条件以上）
        if len(conditions) >= 2:
            all_paths.extend(BoxPlotRenderer.render(scores, figures_dir, exp_id))

        # レーダーチャート
        all_paths.extend(RadarRenderer.render(scores, figures_dir, exp_id))

        # パラメータスイープ検出（条件名に数字を含む場合）
        param_values = self._detect_parameter_sweep(conditions, scores)
        if param_values:
            x_vals, y_means, y_stds = param_values
            all_paths.extend(LineRenderer.render(x_vals, y_means, y_stds, figures_dir, exp_id))

        # ヒートマップ（条件×指標）
        if len(conditions) >= 2:
            data = []
            for cond in conditions:
                row = [_safe_mean(scores[cond].get(m, [])) for m in METRICS]
                data.append(row)
            short_labels = [METRIC_SHORT.get(m, m) for m in METRICS]
            all_paths.extend(HeatmapRenderer.render(
                data, conditions, short_labels, figures_dir, exp_id,
                title=f"{exp_id}: Condition x Metric Scores",
            ))

        # Pairwise 勝率バーチャート
        wins = _load_pairwise_wins(run_path)
        if wins:
            total = sum(wins.values())
            labels = list(wins.keys())
            values = [wins[l] / total * 100 for l in labels]
            all_paths.extend(BarRenderer.render(
                labels, values, figures_dir, exp_id,
                ylabel="Win Rate (%)", fig_num=3,
            ))

        logger.info("Generated %d figure files in %s", len(all_paths), figures_dir)
        return all_paths

    @staticmethod
    def _detect_parameter_sweep(
        conditions: list[str],
        scores: dict[str, dict[str, list[float]]],
    ) -> tuple[list[float], list[float], list[float]] | None:
        """条件名から数値パラメータを抽出してスイープを検出する。"""
        import re

        values: list[tuple[float, str]] = []
        for cond in conditions:
            nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
            if nums:
                values.append((float(nums[-1]), cond))

        if len(values) < 3:
            return None

        values.sort(key=lambda x: x[0])
        x_vals = [v[0] for v in values]
        y_means = [_safe_mean(scores[v[1]].get("overall", [])) for v in values]
        y_stds = [_safe_std(scores[v[1]].get("overall", [])) for v in values]
        return x_vals, y_means, y_stds
