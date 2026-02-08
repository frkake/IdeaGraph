"""論文品質の合成図 8 点を生成する PaperFigureGenerator"""

from __future__ import annotations

import re
from pathlib import Path

from ._style import (
    HAS_MPL,
    METRICS,
    METRIC_SHORT,
    _safe_mean,
    _safe_std,
    _safe_sem,
    _p_label,
    logger,
)
from ._cross_loader import CrossExperimentLoader, CrossExperimentData, ExperimentData
from ._loaders import load_pairwise_wins, load_pairwise_details

if HAS_MPL:
    import matplotlib
    import matplotlib.pyplot as plt
    import numpy as np

# ── 論文品質 matplotlib 設定 ──
PAPER_RC: dict = {
    "font.family": "serif",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
}

METHOD_COLORS: dict[str, str] = {
    "ideagraph": "#2563EB",
    "direct_llm": "#DC2626",
    "coi_agent": "#16A34A",
    "target_paper": "#F59E0B",
}

CONDITION_LABELS: dict[str, str] = {
    "ideagraph_default": "IdeaGraph",
    "ideagraph": "IdeaGraph",
    "direct_llm_baseline": "Direct LLM",
    "direct_llm": "Direct LLM",
    "coi_agent": "CoI-Agent",
    "coi": "CoI-Agent",
    "target_paper": "Target Paper",
}

METRIC_DISPLAY = {
    "novelty": "Novelty",
    "significance": "Significance",
    "feasibility": "Feasibility",
    "clarity": "Clarity",
    "effectiveness": "Effectiveness",
    "overall": "Overall",
}


def _label(cond: str) -> str:
    """条件名を論文表示名に正規化。"""
    return CONDITION_LABELS.get(cond, cond)


def _color(cond: str) -> str:
    """条件名から論文用色を取得。"""
    lower = cond.lower()
    for key, c in METHOD_COLORS.items():
        if key in lower:
            return c
    palette = list(METHOD_COLORS.values())
    return palette[hash(cond) % len(palette)]


def _save_paper_fig(
    fig, output_dir: Path, name: str, formats: list[str],
) -> list[Path]:
    """指定フォーマットで保存。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for fmt in formats:
        p = output_dir / f"{name}.{fmt}"
        fig.savefig(str(p), dpi=300 if fmt == "png" else None, bbox_inches="tight")
        paths.append(p)
    return paths


class PaperFigureGenerator:
    """論文品質の合成図 8 点を生成する。"""

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
        """全図を生成。エラーは個別キャッチし、生成可能なものだけ出力。"""
        if not HAS_MPL:
            logger.warning("matplotlib not installed. Skipping paper figures.")
            return {}

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        fmts = formats or ["png", "svg"]

        data = self._ensure_data()
        results: dict[str, list[Path]] = {}

        generators = [
            ("fig1_main_results", self._fig1_main_results),
            ("fig2_forest_plot", self._fig2_forest_plot),
            ("fig3_radar_profile", self._fig3_radar_profile),
            ("fig4_ablation_panel", self._fig4_ablation_panel),
            ("fig5_generalization", self._fig5_generalization),
            ("fig6_validation_dashboard", self._fig6_validation_dashboard),
            ("fig7_optimal_heatmap", self._fig7_optimal_heatmap),
            ("fig8_winrate_summary", self._fig8_winrate_summary),
        ]

        with matplotlib.rc_context(PAPER_RC):
            for name, gen_fn in generators:
                try:
                    fig = gen_fn(data)
                    if fig is None:
                        logger.info("Skipping %s (insufficient data)", name)
                        continue
                    paths = _save_paper_fig(fig, output_path, name, fmts)
                    plt.close(fig)
                    results[name] = paths
                    logger.info("Generated %s (%d files)", name, len(paths))
                except Exception as e:
                    logger.error("Failed to generate %s: %s", name, e, exc_info=True)

        return results

    # ────────────────────────────────────────────────────────────────
    # Figure 1: 主要結果 — ベースライン比較 (1×N パネル)
    # ────────────────────────────────────────────────────────────────
    def _fig1_main_results(self, data: CrossExperimentData):
        panels = []
        for exp_id, compare_label in [
            ("EXP-101", "vs Direct LLM"),
            ("EXP-102", "vs CoI-Agent"),
        ]:
            exp = data.get(exp_id)
            if exp is None or not exp.single_scores:
                continue
            panels.append((exp, compare_label))

        if not panels:
            return None

        n = len(panels)
        fig, axes = plt.subplots(1, n, figsize=(7 * n, 5.5))
        if n == 1:
            axes = [axes]

        for idx, (exp, title_suffix) in enumerate(panels):
            ax = axes[idx]
            self._draw_grouped_bar_panel(ax, exp, title_suffix, panel_label=chr(97 + idx))

        fig.tight_layout()
        return fig

    def _draw_grouped_bar_panel(
        self, ax, exp: ExperimentData, title_suffix: str, panel_label: str,
    ):
        """共通2条件 GroupedBar パネル描画。"""
        scores = exp.single_scores
        conditions = list(scores.keys())
        if len(conditions) < 2:
            return

        display_metrics = METRICS + ["overall"]
        n_metrics = len(display_metrics)
        n_conds = len(conditions)
        bar_w = 0.8 / n_conds
        x = np.arange(n_metrics)

        for c_idx, cond in enumerate(conditions):
            means = [_safe_mean(scores[cond].get(m, [])) for m in display_metrics]
            sems = [_safe_sem(scores[cond].get(m, [])) for m in display_metrics]
            offset = (c_idx - (n_conds - 1) / 2) * bar_w
            color = _color(cond)
            ax.bar(
                x + offset, means, bar_w * 0.9, yerr=sems, capsize=3,
                color=color, alpha=0.85, label=_label(cond),
                error_kw={"linewidth": 0.8},
            )

        # 有意差スター
        if exp.stats and len(conditions) >= 2:
            sig = exp.stats.per_metric_significance(conditions[0], conditions[1])
            y_top = ax.get_ylim()[1]
            for s in sig:
                m = s["metric"]
                if m not in display_metrics:
                    continue
                m_idx = display_metrics.index(m)
                star = _p_label(s["p"])
                if star == "ns":
                    continue
                a_off = (0 - (n_conds - 1) / 2) * bar_w
                b_off = (1 - (n_conds - 1) / 2) * bar_w
                x1, x2 = m_idx + a_off, m_idx + b_off
                yb = y_top * 0.92
                ax.plot([x1, x1, x2, x2], [yb - 0.08, yb, yb, yb - 0.08],
                        color="black", linewidth=0.7)
                txt = f"{star}\nd={s['d']:.2f}"
                ax.text((x1 + x2) / 2, yb + 0.03, txt,
                        ha="center", va="bottom", fontsize=7)

        ax.set_xticks(x)
        ax.set_xticklabels(
            [METRIC_DISPLAY.get(m, m) for m in display_metrics], fontsize=8,
        )
        ax.set_ylabel("Score (1-10)")
        ax.set_title(f"({panel_label}) {title_suffix}", fontsize=11)
        ax.legend(fontsize=8)
        ax.set_ylim(0, None)

    # ────────────────────────────────────────────────────────────────
    # Figure 2: 効果量フォレストプロット
    # ────────────────────────────────────────────────────────────────
    def _fig2_forest_plot(self, data: CrossExperimentData):
        rows = []  # (label, d, ci_lo, ci_hi)
        for exp_id, baseline_label in [
            ("EXP-101", "Direct LLM"),
            ("EXP-102", "CoI-Agent"),
        ]:
            exp = data.get(exp_id)
            if exp is None or exp.stats is None:
                continue
            conditions = list(exp.single_scores.keys())
            if len(conditions) < 2:
                continue
            cond_a, cond_b = conditions[0], conditions[1]
            for m in METRICS + ["overall"]:
                a = exp.single_scores[cond_a].get(m, [])
                b = exp.single_scores[cond_b].get(m, [])
                if not a or not b:
                    continue
                from idea_graph.services.aggregator import cohen_d
                d = cohen_d(a, b)
                # ブートストラップ CI
                ci_lo, ci_hi = self._bootstrap_ci_d(a, b)
                label = f"{METRIC_DISPLAY.get(m, m)}: IdeaGraph vs {baseline_label}"
                rows.append((label, d, ci_lo, ci_hi))

        if not rows:
            return None

        fig, ax = plt.subplots(figsize=(8, max(4, len(rows) * 0.45 + 1)))
        y_pos = list(range(len(rows)))

        # 背景帯: 効果量ゾーン
        for threshold, alpha_val in [(0.2, 0.05), (0.5, 0.08), (0.8, 0.10)]:
            ax.axvspan(threshold, threshold + 0.3, alpha=alpha_val, color="green")
            ax.axvspan(-threshold - 0.3, -threshold, alpha=alpha_val, color="green")

        ax.axvline(0, color="black", linestyle=":", linewidth=0.8)

        for i, (label, d, ci_lo, ci_hi) in enumerate(rows):
            ax.plot(d, i, "o", color=METHOD_COLORS["ideagraph"], markersize=6)
            ax.plot([ci_lo, ci_hi], [i, i], "-", color=METHOD_COLORS["ideagraph"],
                    linewidth=1.5)

        ax.set_yticks(y_pos)
        ax.set_yticklabels([r[0] for r in rows], fontsize=8)
        ax.set_xlabel("Cohen's d (effect size)")
        ax.set_title("Effect Size Forest Plot")
        ax.invert_yaxis()
        fig.tight_layout()
        return fig

    @staticmethod
    def _bootstrap_ci_d(
        a: list[float], b: list[float], n_boot: int = 2000, ci: float = 0.95,
    ) -> tuple[float, float]:
        """Cohen's d のブートストラップ信頼区間を計算。"""
        from idea_graph.services.aggregator import cohen_d
        import random
        rng = random.Random(42)
        n = min(len(a), len(b))
        a_t, b_t = a[:n], b[:n]
        ds = []
        for _ in range(n_boot):
            idx = [rng.randint(0, n - 1) for _ in range(n)]
            a_s = [a_t[i] for i in idx]
            b_s = [b_t[i] for i in idx]
            ds.append(cohen_d(a_s, b_s))
        ds.sort()
        lo_idx = int((1 - ci) / 2 * n_boot)
        hi_idx = int((1 + ci) / 2 * n_boot) - 1
        return ds[lo_idx], ds[hi_idx]

    # ────────────────────────────────────────────────────────────────
    # Figure 3: レーダープロファイル
    # ────────────────────────────────────────────────────────────────
    def _fig3_radar_profile(self, data: CrossExperimentData):
        # 各手法の平均スコアを全実験から集約
        method_scores: dict[str, dict[str, list[float]]] = {}

        for exp_id in ["EXP-101", "EXP-102", "EXP-103"]:
            exp = data.get(exp_id)
            if exp is None:
                continue
            for cond, scores in exp.single_scores.items():
                key = _label(cond)
                if key not in method_scores:
                    method_scores[key] = {m: [] for m in METRICS}
                for m in METRICS:
                    method_scores[key][m].extend(scores.get(m, []))

        if not method_scores:
            return None

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"polar": True})
        angles = [n / len(METRICS) * 2 * np.pi for n in range(len(METRICS))]
        angles += angles[:1]

        style_map = {
            "IdeaGraph": ("-", 2.0, 0.15, METHOD_COLORS["ideagraph"]),
            "Direct LLM": ("--", 1.5, 0.08, METHOD_COLORS["direct_llm"]),
            "CoI-Agent": (":", 1.5, 0.08, METHOD_COLORS["coi_agent"]),
            "Target Paper": ("-", 1.0, 0.05, METHOD_COLORS["target_paper"]),
        }

        for method, m_scores in method_scores.items():
            values = [_safe_mean(m_scores.get(m, [])) for m in METRICS]
            values += values[:1]
            ls, lw, alpha, color = style_map.get(
                method, ("-", 1.5, 0.10, "#8B5CF6"),
            )
            ax.plot(angles, values, linestyle=ls, linewidth=lw,
                    label=method, color=color)
            ax.fill(angles, values, alpha=alpha, color=color)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([METRIC_DISPLAY.get(m, m) for m in METRICS], fontsize=9)
        ax.set_ylim(0, 10)
        ax.set_title("Quality Profile Comparison", y=1.08, fontsize=12)
        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1), fontsize=9)
        fig.tight_layout()
        return fig

    # ────────────────────────────────────────────────────────────────
    # Figure 4: アブレーション総合パネル (2×4)
    # ────────────────────────────────────────────────────────────────
    def _fig4_ablation_panel(self, data: CrossExperimentData):
        # 200系のいずれか1つでもあれば生成
        ablation_ids = [
            "EXP-201", "EXP-204", "EXP-205", "EXP-206",
            "EXP-202", "EXP-203", "EXP-207",
        ]
        if not any(data.has(eid) for eid in ablation_ids):
            return None

        fig, axes = plt.subplots(2, 4, figsize=(20, 9))
        panel_specs = [
            ("EXP-201", "(a) Max Hops", self._panel_sweep_line, "Max Hops"),
            ("EXP-204", "(b) Path Count", self._panel_sweep_line, "Path Count"),
            ("EXP-205", "(c) Graph Size", self._panel_sweep_line, "Graph Size"),
            ("EXP-206", "(d) Num Proposals", self._panel_proposals, None),
            ("EXP-202", "(e) Graph Format", self._panel_grouped_bar, None),
            ("EXP-203", "(f) Prompt Scope", self._panel_grouped_bar, None),
            ("EXP-207", "(g) Quality-Cost", self._panel_pareto, None),
            (None, None, None, None),  # 最後のパネルは凡例 or 非表示
        ]

        for idx, (exp_id, title, draw_fn, xlabel) in enumerate(panel_specs):
            ax = axes[idx // 4][idx % 4]
            if exp_id is None:
                ax.set_visible(False)
                continue

            exp = data.get(exp_id)
            if exp is None:
                ax.set_facecolor("#f5f5f5")
                ax.text(0.5, 0.5, "Not yet run", transform=ax.transAxes,
                        ha="center", va="center", fontsize=12, color="#999")
                ax.set_title(title, fontsize=10)
                continue

            try:
                if xlabel:
                    draw_fn(ax, exp, xlabel)
                else:
                    draw_fn(ax, exp)
                ax.set_title(title, fontsize=10)
            except Exception as e:
                logger.warning("Ablation panel %s failed: %s", exp_id, e)
                ax.text(0.5, 0.5, f"Error: {e}", transform=ax.transAxes,
                        ha="center", va="center", fontsize=9, color="red")
                ax.set_title(title, fontsize=10)

        fig.suptitle("Ablation Studies", fontsize=14, y=1.01)
        fig.tight_layout()
        return fig

    def _panel_sweep_line(self, ax, exp: ExperimentData, xlabel: str):
        """パラメータスイープをラインプロットで描画。"""
        scores = exp.single_scores
        conditions = list(scores.keys())

        # 条件名から数値を抽出してソート
        val_conds = []
        for cond in conditions:
            nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
            if nums:
                val_conds.append((float(nums[-1]), cond))
        if not val_conds:
            return
        val_conds.sort()
        x_vals = [v[0] for v in val_conds]
        sorted_conds = [v[1] for v in val_conds]

        means = [_safe_mean(scores[c].get("overall", [])) for c in sorted_conds]
        stds = [_safe_std(scores[c].get("overall", [])) for c in sorted_conds]

        ax.errorbar(x_vals, means, yerr=stds, fmt="o-",
                    color=METHOD_COLORS["ideagraph"], capsize=3, linewidth=1.5)

        # 最適点マーク
        if means:
            best_i = max(range(len(means)), key=lambda i: means[i])
            ax.plot(x_vals[best_i], means[best_i], "*",
                    color="#F59E0B", markersize=14, zorder=5)

        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel("Overall Score", fontsize=9)
        ax.grid(True, alpha=0.3)

    def _panel_proposals(self, ax, exp: ExperimentData):
        """Num proposals: mean overall + best-of-N。"""
        scores = exp.single_scores
        conditions = list(scores.keys())

        val_conds = []
        for cond in conditions:
            nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
            if nums:
                val_conds.append((float(nums[-1]), cond))
        if not val_conds:
            return
        val_conds.sort()
        x_vals = [v[0] for v in val_conds]
        sorted_conds = [v[1] for v in val_conds]

        means = [_safe_mean(scores[c].get("overall", [])) for c in sorted_conds]
        bests = [max(scores[c].get("overall", [0])) for c in sorted_conds]

        ax.plot(x_vals, means, "o-", color=METHOD_COLORS["ideagraph"],
                linewidth=1.5, label="Mean")
        ax.plot(x_vals, bests, "s--", color=METHOD_COLORS["coi_agent"],
                linewidth=1.5, label="Best-of-N")
        ax.set_xlabel("Num Proposals", fontsize=9)
        ax.set_ylabel("Overall Score", fontsize=9)
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    def _panel_grouped_bar(self, ax, exp: ExperimentData):
        """カテゴリ条件の GroupedBar 描画。"""
        scores = exp.single_scores
        conditions = list(scores.keys())
        if not conditions:
            return

        means = [_safe_mean(scores[c].get("overall", [])) for c in conditions]
        sems = [_safe_sem(scores[c].get("overall", [])) for c in conditions]
        colors = [_color(c) for c in conditions]
        labels = [_label(c) for c in conditions]

        x = np.arange(len(conditions))
        ax.bar(x, means, yerr=sems, capsize=3, color=colors, alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=7, rotation=20, ha="right")
        ax.set_ylabel("Overall Score", fontsize=9)

        # 最適点マーク
        if means:
            best_i = max(range(len(means)), key=lambda i: means[i])
            ax.plot(x[best_i], means[best_i] + sems[best_i] + 0.1, "*",
                    color="#F59E0B", markersize=12)

    def _panel_pareto(self, ax, exp: ExperimentData):
        """Quality-Cost Pareto scatter。"""
        scores = exp.single_scores
        conditions = list(scores.keys())
        if not conditions:
            return

        # コストを条件名から推定（数値抽出）
        costs = []
        overall_means = []
        labels = []
        for cond in conditions:
            nums = re.findall(r"(\d+(?:\.\d+)?)", cond)
            cost = float(nums[-1]) if nums else 0
            costs.append(cost)
            overall_means.append(_safe_mean(scores[cond].get("overall", [])))
            labels.append(_label(cond))

        ax.scatter(costs, overall_means, color=METHOD_COLORS["ideagraph"], zorder=5)
        for i, lb in enumerate(labels):
            ax.annotate(lb, (costs[i], overall_means[i]), fontsize=6,
                        xytext=(3, 3), textcoords="offset points")

        # Pareto front
        paired = sorted(zip(costs, overall_means))
        front_x, front_y = [], []
        best = -float("inf")
        for c, s in paired:
            if s >= best:
                front_x.append(c)
                front_y.append(s)
                best = s
        if len(front_x) > 1:
            ax.plot(front_x, front_y, "r--", linewidth=1.5)

        ax.set_xlabel("Cost", fontsize=9)
        ax.set_ylabel("Overall Score", fontsize=9)

    # ────────────────────────────────────────────────────────────────
    # Figure 5: 汎化性能 (1×2 パネル)
    # ────────────────────────────────────────────────────────────────
    def _fig5_generalization(self, data: CrossExperimentData):
        panels = []
        for exp_id in ["EXP-208", "EXP-209"]:
            if data.has(exp_id):
                panels.append(data.get(exp_id))
        if not panels:
            return None

        n = len(panels)
        fig, axes = plt.subplots(1, n, figsize=(7 * n, 5.5))
        if n == 1:
            axes = [axes]

        for idx, exp in enumerate(panels):
            ax = axes[idx]
            if exp.exp_id == "EXP-208":
                self._panel_grouped_bar(ax, exp)
                ax.set_title(f"(a) Connectivity Tier Performance", fontsize=10)
            else:
                self._draw_interaction_panel(ax, exp)
                ax.set_title(f"(b) Method × Connectivity Interaction", fontsize=10)

        fig.tight_layout()
        return fig

    def _draw_interaction_panel(self, ax, exp: ExperimentData):
        """EXP-209: interaction plot。"""
        scores = exp.single_scores
        conditions = list(scores.keys())
        if not conditions:
            return

        # 条件名からメソッドとティアを分離
        # 形式: method_tier (例: ideagraph_high, direct_llm_low)
        methods: dict[str, list[tuple[str, float]]] = {}
        for cond in conditions:
            parts = cond.rsplit("_", 1)
            method = parts[0] if len(parts) > 1 else cond
            tier = parts[-1] if len(parts) > 1 else "default"
            overall = _safe_mean(scores[cond].get("overall", []))
            methods.setdefault(method, []).append((tier, overall))

        tiers_all = set()
        for m, vals in methods.items():
            for t, _ in vals:
                tiers_all.add(t)
        tier_order = sorted(tiers_all)

        for method, vals in methods.items():
            tier_map = {t: v for t, v in vals}
            y_vals = [tier_map.get(t, 0) for t in tier_order]
            linestyle = "-" if "ideagraph" in method.lower() else "--"
            ax.plot(range(len(tier_order)), y_vals, f"o{linestyle}",
                    color=_color(method), label=_label(method), linewidth=1.5)

        ax.set_xticks(range(len(tier_order)))
        ax.set_xticklabels(tier_order, fontsize=8)
        ax.set_xlabel("Connectivity Tier", fontsize=9)
        ax.set_ylabel("Overall Score", fontsize=9)
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # ────────────────────────────────────────────────────────────────
    # Figure 6: 評価妥当性ダッシュボード (2×3)
    # ────────────────────────────────────────────────────────────────
    def _fig6_validation_dashboard(self, data: CrossExperimentData):
        val_ids = ["EXP-301", "EXP-302", "EXP-303", "EXP-304", "EXP-305", "EXP-306"]
        if not any(data.has(eid) for eid in val_ids):
            return None

        fig, axes = plt.subplots(2, 3, figsize=(18, 11))
        panel_specs = [
            ("EXP-301", "(a) Pairwise-Single Consistency", self._panel_301),
            ("EXP-302", "(b) Reproducibility (α)", self._panel_302),
            ("EXP-303", "(c) Position Bias", self._panel_303),
            ("EXP-304", "(d) Cross-Model Agreement", self._panel_304),
            ("EXP-305", "(e) Human-LLM Agreement", self._panel_305),
            ("EXP-306", "(f) Citation Grounding", self._panel_306),
        ]

        for idx, (exp_id, title, draw_fn) in enumerate(panel_specs):
            ax = axes[idx // 3][idx % 3]
            exp = data.get(exp_id)
            if exp is None:
                ax.set_facecolor("#f5f5f5")
                ax.text(0.5, 0.5, "Not yet run", transform=ax.transAxes,
                        ha="center", va="center", fontsize=12, color="#999")
                ax.set_title(title, fontsize=10)
                continue
            try:
                draw_fn(ax, exp)
                ax.set_title(title, fontsize=10)
            except Exception as e:
                logger.warning("Validation panel %s failed: %s", exp_id, e)
                ax.text(0.5, 0.5, f"Error", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10, color="red")
                ax.set_title(title, fontsize=10)

        fig.suptitle("Evaluation Validity Dashboard", fontsize=14, y=1.01)
        fig.tight_layout()
        return fig

    def _panel_301(self, ax, exp: ExperimentData):
        """Scatter: Single overall vs Pairwise ELO + 回帰線 + Spearman ρ"""
        from ._loaders import load_single_scores_per_paper, load_pairwise_details
        from idea_graph.services.aggregator import spearman

        per_paper = exp.per_paper
        pairwise_files = load_pairwise_details(exp.run_dir)

        single_vals, pairwise_vals = [], []
        for pw_data in pairwise_files:
            for entry in pw_data.get("ranking", []):
                source = str(entry.get("source", ""))
                elo = entry.get("elo_rating")
                if elo is None:
                    elo = 1500 - (entry.get("rank", 1) - 1) * 100
                for cond, papers in per_paper.items():
                    for pid, sc in papers.items():
                        if source in pid or pid in source:
                            single_vals.append(sc.get("overall", 5))
                            pairwise_vals.append(float(elo))
                            break

        if len(single_vals) < 3:
            ax.text(0.5, 0.5, "Insufficient data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10)
            return

        ax.scatter(single_vals, pairwise_vals, alpha=0.6, color=METHOD_COLORS["ideagraph"])
        # 回帰線
        coeffs = np.polyfit(single_vals, pairwise_vals, 1)
        x_line = np.linspace(min(single_vals), max(single_vals), 50)
        ax.plot(x_line, np.polyval(coeffs, x_line), "--", color="gray", alpha=0.6)

        rho = spearman(single_vals, pairwise_vals)
        ax.text(0.05, 0.95, f"Spearman ρ = {rho:.3f}\nn = {len(single_vals)}",
                transform=ax.transAxes, fontsize=9, va="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
        ax.set_xlabel("Single Overall Score", fontsize=9)
        ax.set_ylabel("Pairwise ELO", fontsize=9)

    def _panel_302(self, ax, exp: ExperimentData):
        """Bar: Krippendorff's α per metric + 閾値線。"""
        if exp.stats:
            alphas = exp.stats.irr_alphas()
        else:
            alphas = {}

        # aggregate から直接取得
        if not alphas:
            irr = exp.aggregate.get("inter_rater_reliability", {})
            for cond, cond_data in irr.items():
                ka = cond_data.get("krippendorffs_alpha", {})
                if ka:
                    alphas[cond] = ka

        if not alphas:
            ax.text(0.5, 0.5, "No IRR data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10)
            return

        # 最初の条件のalphaを表示
        first_cond = list(alphas.keys())[0]
        metric_alphas = alphas[first_cond]
        metrics_list = [m for m in METRICS + ["overall"] if m in metric_alphas]
        values = [metric_alphas[m] for m in metrics_list]
        labels = [METRIC_DISPLAY.get(m, m) for m in metrics_list]
        colors = ["#16A34A" if v >= 0.9 else "#DC2626" for v in values]

        ax.bar(range(len(labels)), values, color=colors, alpha=0.85)
        ax.axhline(0.9, color="red", linestyle="--", linewidth=0.8, label="α = 0.9")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=8, rotation=20, ha="right")
        ax.set_ylabel("Krippendorff's α", fontsize=9)
        ax.legend(fontsize=7)

    def _panel_303(self, ax, exp: ExperimentData):
        """ConfusionMatrix: AB/BA 一致 + agreement rate。"""
        from ._loaders import load_pairwise_swap_data
        swap_data = load_pairwise_swap_data(exp.run_dir)

        if not swap_data:
            ax.text(0.5, 0.5, "No swap test data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10)
            return

        # 2x2 confusion matrix: consistent vs flipped
        consistent = sum(1 for v in swap_data.values() if v.get("consistent", True))
        flipped = len(swap_data) - consistent
        total = len(swap_data)
        agreement = consistent / total * 100 if total > 0 else 0

        matrix = [[consistent, flipped], [flipped, consistent]]
        im = ax.imshow(matrix, cmap="Blues", aspect="auto")
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Consistent", "Flipped"], fontsize=8)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["AB", "BA"], fontsize=8)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, str(matrix[i][j]), ha="center", va="center", fontsize=11)
        ax.text(0.5, -0.2, f"Agreement: {agreement:.1f}%",
                transform=ax.transAxes, ha="center", fontsize=9,
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

    def _panel_304(self, ax, exp: ExperimentData):
        """Heatmap: モデル間 Spearman ρ."""
        from ._loaders import load_multi_model_scores
        from idea_graph.services.aggregator import spearman

        multi = load_multi_model_scores(exp.run_dir)
        models = sorted(multi.keys())

        if len(models) < 2:
            ax.text(0.5, 0.5, "Need 2+ models", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10)
            return

        # 各モデルの overall スコアを集約
        model_overalls: dict[str, list[float]] = {}
        for model in models:
            all_scores = []
            for cond, scores in multi[model].items():
                all_scores.extend(scores.get("overall", []))
            model_overalls[model] = all_scores

        n = len(models)
        corr_matrix = np.ones((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                a = model_overalls[models[i]]
                b = model_overalls[models[j]]
                min_len = min(len(a), len(b))
                if min_len >= 3:
                    rho = spearman(a[:min_len], b[:min_len])
                    corr_matrix[i][j] = rho
                    corr_matrix[j][i] = rho

        im = ax.imshow(corr_matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
        ax.set_xticks(range(n))
        ax.set_xticklabels(models, fontsize=7, rotation=30, ha="right")
        ax.set_yticks(range(n))
        ax.set_yticklabels(models, fontsize=7)
        for i in range(n):
            for j in range(n):
                ax.text(j, i, f"{corr_matrix[i][j]:.2f}", ha="center", va="center", fontsize=8)
        plt.colorbar(im, ax=ax, shrink=0.8)

    def _panel_305(self, ax, exp: ExperimentData):
        """Scatter: Human vs LLM + Pearson r + y=x 対角線。"""
        from idea_graph.services.aggregator import pearson

        # aggregate から human_vs_llm データを探す
        agg = exp.aggregate
        human_scores = agg.get("human_scores", [])
        llm_scores = agg.get("llm_scores", [])

        if not human_scores or not llm_scores:
            # 代替: single scores から推定
            per_paper = exp.per_paper
            conditions = list(per_paper.keys())
            if len(conditions) >= 2:
                cond_a = conditions[0]
                cond_b = conditions[1]
                human_scores = [per_paper[cond_a][p].get("overall", 5) for p in per_paper[cond_a]]
                llm_scores = [per_paper[cond_b][p].get("overall", 5) for p in per_paper[cond_b] if p in per_paper[cond_a]]

        if len(human_scores) < 3 or len(llm_scores) < 3:
            ax.text(0.5, 0.5, "Insufficient data", transform=ax.transAxes,
                    ha="center", va="center", fontsize=10)
            return

        n = min(len(human_scores), len(llm_scores))
        human_scores = human_scores[:n]
        llm_scores = llm_scores[:n]

        ax.scatter(human_scores, llm_scores, alpha=0.6, color=METHOD_COLORS["ideagraph"])
        # y=x 対角線
        lo = min(min(human_scores), min(llm_scores))
        hi = max(max(human_scores), max(llm_scores))
        ax.plot([lo, hi], [lo, hi], ":", color="black", alpha=0.3)

        r = pearson(human_scores, llm_scores)
        ax.text(0.05, 0.95, f"Pearson r = {r:.3f}\nn = {n}",
                transform=ax.transAxes, fontsize=9, va="top",
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
        ax.set_xlabel("Human Score", fontsize=9)
        ax.set_ylabel("LLM Score", fontsize=9)

    def _panel_306(self, ax, exp: ExperimentData):
        """StackedBar: grounding 比率。"""
        agg = exp.aggregate
        grounding = agg.get("grounding_analysis", {})

        if not grounding:
            # single_scores から推定
            scores = exp.single_scores
            if not scores:
                ax.text(0.5, 0.5, "No grounding data", transform=ax.transAxes,
                        ha="center", va="center", fontsize=10)
                return
            # 代替表示: 各条件の overall を棒グラフ化
            conds = list(scores.keys())
            means = [_safe_mean(scores[c].get("overall", [])) for c in conds]
            ax.bar(range(len(conds)), means, color=METHOD_COLORS["ideagraph"], alpha=0.85)
            ax.set_xticks(range(len(conds)))
            ax.set_xticklabels([_label(c) for c in conds], fontsize=8)
            ax.set_ylabel("Overall Score", fontsize=9)
            return

        categories = list(grounding.keys())
        full = [grounding[c].get("full", 0) for c in categories]
        partial = [grounding[c].get("partial", 0) for c in categories]
        none_vals = [grounding[c].get("none", 0) for c in categories]

        x = np.arange(len(categories))
        ax.bar(x, full, 0.6, label="Full", color="#16A34A", alpha=0.85)
        ax.bar(x, partial, 0.6, bottom=full, label="Partial", color="#F59E0B", alpha=0.85)
        bottoms = [f + p for f, p in zip(full, partial)]
        ax.bar(x, none_vals, 0.6, bottom=bottoms, label="None", color="#DC2626", alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(categories, fontsize=8)
        ax.set_ylabel("Proportion (%)", fontsize=9)
        ax.legend(fontsize=7)

    # ────────────────────────────────────────────────────────────────
    # Figure 7: 最適設定ヒートマップ
    # ────────────────────────────────────────────────────────────────
    def _fig7_optimal_heatmap(self, data: CrossExperimentData):
        ablation_map = {
            "EXP-201": "Max Hops",
            "EXP-202": "Graph Format",
            "EXP-203": "Prompt Scope",
            "EXP-204": "Path Count",
            "EXP-205": "Graph Size",
            "EXP-206": "Num Proposals",
            "EXP-207": "Cost Tier",
        }

        rows = []  # (param_name, best_setting, {metric: score})
        for exp_id, param_name in ablation_map.items():
            exp = data.get(exp_id)
            if exp is None:
                continue

            scores = exp.single_scores
            if not scores:
                continue

            # 最適条件を特定 (overall が最高の条件)
            best_cond = max(scores.keys(),
                            key=lambda c: _safe_mean(scores[c].get("overall", [])))
            best_scores = {m: _safe_mean(scores[best_cond].get(m, []))
                           for m in METRICS + ["overall"]}
            rows.append((param_name, best_cond, best_scores))

        if not rows:
            return None

        col_metrics = METRICS + ["overall"]
        col_labels = [METRIC_DISPLAY.get(m, m) for m in col_metrics]
        row_labels = [r[0] for r in rows]

        matrix = []
        annot = []
        for param, best_cond, best_scores in rows:
            row_vals = [best_scores.get(m, 0) for m in col_metrics]
            matrix.append(row_vals)
            row_annot = [f"{v:.1f}" for v in row_vals]
            annot.append(row_annot)

        fig, ax = plt.subplots(figsize=(10, max(3, len(rows) * 0.8 + 1)))
        arr = np.array(matrix)
        im = ax.imshow(arr, cmap="YlOrRd", aspect="auto")

        ax.set_xticks(range(len(col_labels)))
        ax.set_xticklabels(col_labels, fontsize=9)
        ax.set_yticks(range(len(row_labels)))
        ax.set_yticklabels(row_labels, fontsize=9)

        # セル値 + 最適設定名注釈
        for i in range(len(row_labels)):
            for j in range(len(col_labels)):
                val = annot[i][j]
                setting = rows[i][1]
                text = f"{val}\n({setting[:12]})" if j == len(col_labels) - 1 else val
                ax.text(j, i, text, ha="center", va="center", fontsize=7)

        # 列最適値を緑枠ハイライト
        for j in range(len(col_labels)):
            col_vals = [arr[i, j] for i in range(len(row_labels))]
            if col_vals:
                best_i = max(range(len(col_vals)), key=lambda i: col_vals[i])
                ax.add_patch(plt.Rectangle(
                    (j - 0.5, best_i - 0.5), 1, 1,
                    fill=False, edgecolor="lime", linewidth=2,
                ))

        plt.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title("Optimal Settings Heatmap", fontsize=12)
        fig.tight_layout()
        return fig

    # ────────────────────────────────────────────────────────────────
    # Figure 8: Pairwise 勝率サマリー
    # ────────────────────────────────────────────────────────────────
    def _fig8_winrate_summary(self, data: CrossExperimentData):
        rows = []  # (label, win%, loss%, tie%)
        for exp_id, label in [
            ("EXP-101", "vs Direct LLM"),
            ("EXP-102", "vs CoI-Agent"),
        ]:
            exp = data.get(exp_id)
            if exp is None:
                continue
            wins = exp.pairwise_wins
            if not wins:
                continue
            conditions = list(exp.single_scores.keys())
            if len(conditions) < 2:
                continue
            total = sum(wins.values())
            if total == 0:
                continue
            cond_a, cond_b = conditions[0], conditions[1]
            win_pct = wins.get(cond_a, 0) / total * 100
            loss_pct = wins.get(cond_b, 0) / total * 100
            tie_pct = max(0, 100 - win_pct - loss_pct)
            rows.append((label, win_pct, loss_pct, tie_pct))

        if not rows:
            return None

        fig, ax = plt.subplots(figsize=(8, max(2, len(rows) * 1.2 + 1)))
        y_pos = np.arange(len(rows))
        bar_h = 0.5

        win_vals = [r[1] for r in rows]
        loss_vals = [r[2] for r in rows]
        tie_vals = [r[3] for r in rows]

        ax.barh(y_pos, win_vals, bar_h, label="Win", color=METHOD_COLORS["ideagraph"], alpha=0.85)
        ax.barh(y_pos, tie_vals, bar_h, left=win_vals, label="Tie", color="#9CA3AF", alpha=0.85)
        left_for_loss = [w + t for w, t in zip(win_vals, tie_vals)]
        ax.barh(y_pos, loss_vals, bar_h, left=left_for_loss, label="Loss", color=METHOD_COLORS["direct_llm"], alpha=0.85)

        # パーセンテージラベル
        for i, (label, w, l, t) in enumerate(rows):
            if w > 5:
                ax.text(w / 2, i, f"{w:.0f}%", ha="center", va="center", fontsize=9, color="white", fontweight="bold")
            if t > 5:
                ax.text(w + t / 2, i, f"{t:.0f}%", ha="center", va="center", fontsize=9)
            if l > 5:
                ax.text(w + t + l / 2, i, f"{l:.0f}%", ha="center", va="center", fontsize=9, color="white", fontweight="bold")

        ax.set_yticks(y_pos)
        ax.set_yticklabels([r[0] for r in rows], fontsize=10)
        ax.set_xlabel("Percentage (%)")
        ax.set_title("Pairwise Win Rate Summary", fontsize=12)
        ax.legend(loc="upper right", fontsize=9)
        ax.set_xlim(0, 100)
        fig.tight_layout()
        return fig
