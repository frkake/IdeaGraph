"""論文品質の合成図を生成する PaperFigureGenerator

利用可能な実験データのみから図を生成し、欠損実験は graceful にスキップする。
出力: PNG (300 DPI) + SVG
"""

from __future__ import annotations

from pathlib import Path

from ._style import (
    HAS_MPL,
    METRICS,
    METRIC_SHORT,
    STYLE,
    _safe_mean,
    _safe_std,
    _save_figure,
    logger,
)
from ._cross_loader import CrossExperimentLoader, CrossExperimentData
from ._loaders import load_pairwise_elo_by_source, load_paper_degrees, load_single_scores_per_paper

if HAS_MPL:
    import matplotlib
    import matplotlib.pyplot as plt
    import numpy as np

# ── 共通定義 ──

METHOD_COLORS: dict[str, str] = {
    "ideagraph": "#2563EB",
    "direct_llm": "#DC2626",
    "coi_agent": "#16A34A",
    "coi": "#16A34A",
    "target_paper": "#F59E0B",
}

CONDITION_LABELS: dict[str, str] = {
    "ideagraph": "IdeaGraph",
    "ideagraph_default": "IdeaGraph",
    "direct_llm": "Direct LLM",
    "direct_llm_baseline": "Direct LLM",
    "coi": "CoI-Agent",
    "coi_agent": "CoI-Agent",
    "target_paper": "Target Paper",
}

METRIC_DISPLAY: dict[str, str] = {
    "novelty": "Novelty",
    "significance": "Significance",
    "feasibility": "Feasibility",
    "clarity": "Clarity",
    "effectiveness": "Effectiveness",
    "overall": "Overall",
}


def _label(name: str) -> str:
    return CONDITION_LABELS.get(name.lower(), name)


def _color(name: str) -> str:
    lower = name.lower()
    for key, color in METHOD_COLORS.items():
        if key in lower:
            return color
    return STYLE.color_for(name)


class PaperFigureGenerator:
    """全実験横断の論文品質合成図を生成する。"""

    def __init__(self, runs_base: str | Path) -> None:
        self.runs_base = Path(runs_base)
        self._data: CrossExperimentData | None = None

    def _ensure_data(self) -> CrossExperimentData:
        if self._data is None:
            loader = CrossExperimentLoader(self.runs_base)
            self._data = loader.load()
        return self._data

    def generate_all(
        self,
        output_dir: str | Path,
        formats: list[str] | None = None,
    ) -> dict[str, list[Path]]:
        """全合成図を出力ディレクトリに生成する。"""
        if not HAS_MPL:
            return {}

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        data = self._ensure_data()
        results: dict[str, list[Path]] = {}

        generators = [
            ("fig1_main_results", self._fig1_main_results),
            ("fig2_radar_profile", self._fig2_radar_profile),
            ("fig3_winrate_summary", self._fig3_winrate_summary),
            ("fig4_connectivity", self._fig4_connectivity),
        ]

        for name, gen_fn in generators:
            try:
                paths = gen_fn(data, output_path)
                if paths:
                    results[name] = paths
                    logger.info("Generated paper figure: %s (%d files)", name, len(paths))
                else:
                    logger.info("Skipped %s (insufficient data)", name)
            except Exception as e:
                logger.warning("Failed to generate %s: %s", name, e)

        return results

    def _fig1_main_results(self, data: CrossExperimentData, output_dir: Path) -> list[Path]:
        """Fig 1: 手法別メトリクス比較 (Grouped Bar)"""
        exp101 = data.get("EXP-101")
        if not exp101:
            return []

        elo_by_source = load_pairwise_elo_by_source(exp101.run_dir)
        if not elo_by_source:
            return []

        sources = sorted(elo_by_source.keys())
        display_metrics = METRICS + ["overall"]

        fig, ax = plt.subplots(figsize=(12, 6))
        n_metrics = len(display_metrics)
        n_sources = len(sources)
        bar_width = 0.8 / max(n_sources, 1)
        x_base = np.arange(n_metrics)

        for s_idx, source in enumerate(sources):
            means = [_safe_mean(elo_by_source[source].get(m, [])) for m in display_metrics]
            stds = [_safe_std(elo_by_source[source].get(m, [])) for m in display_metrics]
            offset = (s_idx - (n_sources - 1) / 2) * bar_width
            ax.bar(
                x_base + offset, means, bar_width * 0.88,
                yerr=stds, capsize=3, color=_color(source), alpha=0.85,
                label=_label(source), error_kw={"linewidth": 1},
            )

        ax.axhline(1000, color="gray", linestyle=":", linewidth=0.8, alpha=0.5)
        ax.set_xticks(x_base)
        ax.set_xticklabels([METRIC_DISPLAY.get(m, m) for m in display_metrics], fontsize=11)
        ax.set_ylabel("ELO Rating", fontsize=12)
        ax.set_title("Method Comparison — ELO Scores by Metric", fontsize=14, fontweight="bold")
        ax.legend(fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, "fig1_main_results")
        plt.close(fig)
        return paths

    def _fig2_radar_profile(self, data: CrossExperimentData, output_dir: Path) -> list[Path]:
        """Fig 2: レーダープロファイル"""
        exp101 = data.get("EXP-101")
        if not exp101:
            return []

        elo_by_source = load_pairwise_elo_by_source(exp101.run_dir)
        if not elo_by_source:
            return []

        sources = sorted(elo_by_source.keys())

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"polar": True})
        angles = [n / len(METRICS) * 2 * np.pi for n in range(len(METRICS))]
        angles += angles[:1]

        for source in sources:
            values = [_safe_mean(elo_by_source[source].get(m, [])) for m in METRICS]
            values += values[:1]
            ax.plot(angles, values, "o-", linewidth=2.5, label=_label(source),
                    color=_color(source), markersize=6)
            ax.fill(angles, values, alpha=0.12, color=_color(source))

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(
            [METRIC_DISPLAY.get(m, m) for m in METRICS],
            fontsize=12, fontweight="bold",
        )

        all_vals = [_safe_mean(elo_by_source[s].get(m, [])) for s in sources for m in METRICS]
        if all_vals:
            ax.set_ylim(min(all_vals) - 50, max(all_vals) + 50)

        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1), fontsize=10)
        ax.set_title("Metric Profile Comparison", fontsize=14, fontweight="bold", pad=20)
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, "fig2_radar_profile")
        plt.close(fig)
        return paths

    def _fig3_winrate_summary(self, data: CrossExperimentData, output_dir: Path) -> list[Path]:
        """Fig 3: 勝率サマリ"""
        exp101 = data.get("EXP-101")
        if not exp101 or not exp101.pairwise_wins:
            return []

        wins = exp101.pairwise_wins
        total = sum(wins.values())
        if total == 0:
            return []

        fig, ax = plt.subplots(figsize=(8, 5))
        sources = sorted(wins.keys())
        labels = [_label(s) for s in sources]
        pcts = [wins[s] / total * 100 for s in sources]
        colors = [_color(s) for s in sources]

        bars = ax.bar(labels, pcts, color=colors, alpha=0.85, edgecolor="white")
        for bar, pct in zip(bars, pcts):
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{pct:.0f}%", ha="center", va="bottom", fontsize=12, fontweight="bold",
            )

        ax.set_ylabel("Win Rate (%)", fontsize=12)
        ax.set_title("Top-1 Rank Win Rate", fontsize=14, fontweight="bold")
        ax.set_ylim(0, max(pcts) * 1.3)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, "fig3_winrate_summary")
        plt.close(fig)
        return paths

    def _fig4_connectivity(self, data: CrossExperimentData, output_dir: Path) -> list[Path]:
        """Fig 4: 接続性安定性 (EXP-208)"""
        exp208 = data.get("EXP-208")
        if not exp208:
            return []

        degrees = load_paper_degrees(exp208.run_dir)
        per_paper = load_single_scores_per_paper(exp208.run_dir)
        if not degrees or not per_paper:
            return []

        degree_vals: list[float] = []
        overall_vals: list[float] = []
        for cond, papers in per_paper.items():
            for paper_id, scores in papers.items():
                deg = degrees.get(paper_id)
                overall = scores.get("overall")
                if deg is not None and overall is not None:
                    degree_vals.append(float(deg))
                    overall_vals.append(float(overall))

        if not degree_vals:
            return []

        try:
            from idea_graph.services.aggregator import spearman, pearson
        except ImportError:
            return []

        fig, ax = plt.subplots(figsize=(10, 6))
        x_arr = np.array(degree_vals)
        y_arr = np.array(overall_vals)

        ax.scatter(x_arr, y_arr, s=70, alpha=0.7, color="#2563EB",
                   edgecolors="white", linewidth=0.8, zorder=3)

        if len(x_arr) >= 2 and len(set(x_arr)) >= 2:
            coeffs = np.polyfit(x_arr, y_arr, 1)
            x_line = np.linspace(x_arr.min() - 1, x_arr.max() + 1, 100)
            y_line = np.polyval(coeffs, x_line)
            ax.plot(x_line, y_line, "--", color="#DC2626", linewidth=2, label="Linear Fit")

            se = np.std(y_arr - np.polyval(coeffs, x_arr))
            ax.fill_between(x_line, y_line - 1.96 * se, y_line + 1.96 * se,
                            alpha=0.12, color="#DC2626", label="95% CI")

        n = len(degree_vals)
        rho = spearman(degree_vals, overall_vals) if n >= 3 else 0.0
        r = pearson(degree_vals, overall_vals) if n >= 3 else 0.0
        annotation = f"n = {n}"
        if n >= 3:
            annotation += f"\nSpearman ρ = {rho:.3f}\nPearson r = {r:.3f}"
        ax.text(
            0.05, 0.95, annotation, transform=ax.transAxes,
            fontsize=11, va="top", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white",
                      edgecolor="#D1D5DB", alpha=0.9),
        )

        ax.set_xlabel("Degree (number of connections)", fontsize=12)
        ax.set_ylabel("Overall Score", fontsize=12)
        ax.set_title("Connectivity Stability — Degree vs Quality", fontsize=14, fontweight="bold")
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        paths = _save_figure(fig, output_dir, "fig4_connectivity")
        plt.close(fig)
        return paths
