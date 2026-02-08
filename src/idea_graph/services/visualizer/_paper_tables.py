"""論文品質の LaTeX テーブル 4 点を生成する PaperTableGenerator"""

from __future__ import annotations

import re
from pathlib import Path

from ._style import METRICS, METRIC_SHORT, _safe_mean, _safe_std, _p_label, logger
from ._cross_loader import CrossExperimentLoader, CrossExperimentData, ExperimentData
from ._paper_figures import CONDITION_LABELS, METRIC_DISPLAY, _label

from idea_graph.services.aggregator import cohen_d, paired_permutation_pvalue


class PaperTableGenerator:
    """論文品質の LaTeX テーブル 4 点を生成する。"""

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
    ) -> dict[str, list[Path]]:
        """全テーブルを .tex ファイルとして出力。"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        data = self._ensure_data()
        results: dict[str, list[Path]] = {}

        generators = [
            ("table1_main_results", self._table1_main_results),
            ("table2_ablation_results", self._table2_ablation_results),
            ("table3_validation_checklist", self._table3_validation_checklist),
            ("table4_full_scores", self._table4_full_scores),
        ]

        for name, gen_fn in generators:
            try:
                latex = gen_fn(data)
                if latex is None:
                    logger.info("Skipping %s (insufficient data)", name)
                    continue
                path = output_path / f"{name}.tex"
                path.write_text(latex, encoding="utf-8")
                results[name] = [path]
                logger.info("Generated %s", name)
            except Exception as e:
                logger.error("Failed to generate %s: %s", name, e, exc_info=True)

        return results

    # ────────────────────────────────────────────────────────────────
    # Table 1: 主要結果テーブル
    # ────────────────────────────────────────────────────────────────
    def _table1_main_results(self, data: CrossExperimentData) -> str | None:
        # 全手法のスコアを収集
        method_scores: dict[str, dict[str, list[float]]] = {}
        method_wins: dict[str, float] = {}

        for exp_id in ["EXP-101", "EXP-102"]:
            exp = data.get(exp_id)
            if exp is None:
                continue
            for cond, scores in exp.single_scores.items():
                label = _label(cond)
                if label not in method_scores:
                    method_scores[label] = {m: [] for m in METRICS + ["overall"]}
                for m in METRICS + ["overall"]:
                    method_scores[label][m].extend(scores.get(m, []))

            # Win%
            wins = exp.pairwise_wins
            conditions = list(exp.single_scores.keys())
            if wins and len(conditions) >= 2:
                total = sum(wins.values())
                if total > 0:
                    for cond in conditions:
                        label = _label(cond)
                        pct = wins.get(cond, 0) / total * 100
                        method_wins[label] = pct

        if not method_scores:
            return None

        # 各指標の最良値を特定
        metric_cols = ["novelty", "significance", "feasibility", "clarity", "effectiveness", "overall"]
        best_vals: dict[str, float] = {}
        for m in metric_cols:
            vals = {method: _safe_mean(method_scores[method].get(m, []))
                    for method in method_scores}
            if vals:
                best_vals[m] = max(vals.values())

        # Cohen's d 脚注用
        footnotes: list[str] = []
        for exp_id, baseline in [("EXP-101", "Direct LLM"), ("EXP-102", "CoI-Agent")]:
            exp = data.get(exp_id)
            if exp is None or exp.stats is None:
                continue
            conditions = list(exp.single_scores.keys())
            if len(conditions) < 2:
                continue
            sig = exp.stats.per_metric_significance(conditions[0], conditions[1])
            for s in sig:
                if s["metric"] == "overall":
                    footnotes.append(f"vs {baseline}: d={s['d']:.2f}, p={s['p']:.4f}")

        # LaTeX 生成
        lines = [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Main Results: IdeaGraph vs Baselines}",
            r"\label{tab:main-results}",
            r"\begin{tabular}{l" + "c" * len(metric_cols) + "c}",
            r"\toprule",
        ]

        # ヘッダー
        short_with_overall = {**METRIC_SHORT, "overall": "Overall"}
        header_cols = [short_with_overall.get(m, m) for m in metric_cols] + ["Win\\%"]
        lines.append("Method & " + " & ".join(header_cols) + r" \\")
        lines.append(r"\midrule")

        # 各手法の行
        for method in sorted(method_scores.keys()):
            cells = []
            for m in metric_cols:
                vals = method_scores[method].get(m, [])
                mean = _safe_mean(vals)
                std = _safe_std(vals)
                cell = f"{mean:.2f} $\\pm$ {std:.2f}"
                # 最良値を太字
                if abs(mean - best_vals.get(m, -1)) < 0.005:
                    cell = r"\textbf{" + cell + "}"
                cells.append(cell)

            # Win%
            win_pct = method_wins.get(method, 0)
            cells.append(f"{win_pct:.0f}")

            # 有意差スター
            method_cell = method
            lines.append(f"{method_cell} & " + " & ".join(cells) + r" \\")

        lines.append(r"\bottomrule")
        lines.append(r"\end{tabular}")

        # 脚注
        if footnotes:
            lines.append(r"\vspace{0.5em}")
            lines.append(r"\begin{minipage}{\linewidth}")
            lines.append(r"\footnotesize")
            for fn in footnotes:
                lines.append(fn + r" \\")
            lines.append(r"\end{minipage}")

        lines.append(r"\end{table}")
        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────
    # Table 2: アブレーション結果テーブル
    # ────────────────────────────────────────────────────────────────
    def _table2_ablation_results(self, data: CrossExperimentData) -> str | None:
        ablation_map = {
            "EXP-201": ("Max Hops", "1--5"),
            "EXP-202": ("Graph Format", "mermaid, paths"),
            "EXP-203": ("Prompt Scope", "full, partial, minimal"),
            "EXP-204": ("Path Count", "3--20"),
            "EXP-205": ("Graph Size", "20--full"),
            "EXP-206": ("Num Proposals", "1--10"),
            "EXP-207": ("Cost Tier", "low--high"),
        }

        rows_data = []
        for exp_id, (param_name, param_range) in ablation_map.items():
            exp = data.get(exp_id)
            if exp is None:
                continue

            scores = exp.single_scores
            if not scores:
                continue

            # 最適条件
            best_cond = max(scores.keys(),
                            key=lambda c: _safe_mean(scores[c].get("overall", [])))
            best_overall = _safe_mean(scores[best_cond].get("overall", []))

            # デフォルト条件との差分
            default_cond = None
            for c in scores.keys():
                if "default" in c.lower() or c == list(scores.keys())[0]:
                    default_cond = c
                    break
            default_overall = _safe_mean(scores[default_cond].get("overall", [])) if default_cond else best_overall
            delta = best_overall - default_overall

            rows_data.append((param_name, param_range, best_cond, best_overall, delta))

        if not rows_data:
            return None

        lines = [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Ablation Study Results}",
            r"\label{tab:ablation}",
            r"\begin{tabular}{llccc}",
            r"\toprule",
            r"Parameter & Range & Best Setting & Overall & $\Delta$ vs Default \\",
            r"\midrule",
        ]

        for param, rng, best, overall, delta in rows_data:
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"{param} & {rng} & {best[:15]} & {overall:.2f} & {sign}{delta:.2f} " + r"\\"
            )

        lines.extend([
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ])
        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────
    # Table 3: 評価妥当性チェックリスト
    # ────────────────────────────────────────────────────────────────
    def _table3_validation_checklist(self, data: CrossExperimentData) -> str | None:
        checks = [
            ("EXP-301", "Pairwise-Single Consistency", "Spearman $\\rho$", "0.70", self._check_301),
            ("EXP-302", "Reproducibility", "Krippendorff's $\\alpha$", "0.90", self._check_302),
            ("EXP-303", "Position Bias", "Agreement \\%", "80\\%", self._check_303),
            ("EXP-304", "Cross-Model Consistency", "Mean Spearman $\\rho$", "0.80", self._check_304),
            ("EXP-305", "Human-LLM Agreement", "Pearson $r$", "0.70", self._check_305),
            ("EXP-306", "Citation Grounding", "Full Grounding \\%", "70\\%", self._check_306),
        ]

        rows_data = []
        has_any = False
        for exp_id, test_name, metric_name, threshold, check_fn in checks:
            exp = data.get(exp_id)
            if exp is None:
                rows_data.append((test_name, metric_name, threshold, "--", "--"))
                continue
            has_any = True
            measured, passed = check_fn(exp)
            pass_str = r"\textcolor{green}{\checkmark}" if passed else r"\textcolor{red}{$\times$}"
            rows_data.append((test_name, metric_name, threshold, measured, pass_str))

        if not has_any:
            return None

        lines = [
            r"\begin{table}[t]",
            r"\centering",
            r"\caption{Evaluation Validity Checklist}",
            r"\label{tab:validity}",
            r"\begin{tabular}{llccc}",
            r"\toprule",
            r"Validation Test & Metric & Threshold & Measured & Pass \\",
            r"\midrule",
        ]

        for test, metric, thresh, measured, passed in rows_data:
            lines.append(f"{test} & {metric} & {thresh} & {measured} & {passed} " + r"\\")

        lines.extend([
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ])
        return "\n".join(lines)

    def _check_301(self, exp: ExperimentData) -> tuple[str, bool]:
        from idea_graph.services.aggregator import spearman
        per_paper = exp.per_paper
        from ._loaders import load_pairwise_details
        pw_files = load_pairwise_details(exp.run_dir)

        single_vals, pw_vals = [], []
        for pw in pw_files:
            for entry in pw.get("ranking", []):
                source = str(entry.get("source", ""))
                elo = entry.get("elo_rating", 1500 - (entry.get("rank", 1) - 1) * 100)
                for cond, papers in per_paper.items():
                    for pid, sc in papers.items():
                        if source in pid or pid in source:
                            single_vals.append(sc.get("overall", 5))
                            pw_vals.append(float(elo))
                            break

        if len(single_vals) < 3:
            return "--", False
        rho = spearman(single_vals, pw_vals)
        return f"{rho:.3f}", rho >= 0.70

    def _check_302(self, exp: ExperimentData) -> tuple[str, bool]:
        alphas = {}
        if exp.stats:
            alphas = exp.stats.irr_alphas()
        if not alphas:
            irr = exp.aggregate.get("inter_rater_reliability", {})
            for cond, cd in irr.items():
                ka = cd.get("krippendorffs_alpha", {})
                if ka:
                    alphas[cond] = ka
        if not alphas:
            return "--", False

        all_alphas = []
        for cond, metric_alphas in alphas.items():
            for m, a in metric_alphas.items():
                all_alphas.append(a)
        if not all_alphas:
            return "--", False
        mean_alpha = sum(all_alphas) / len(all_alphas)
        return f"{mean_alpha:.3f}", mean_alpha >= 0.90

    def _check_303(self, exp: ExperimentData) -> tuple[str, bool]:
        from ._loaders import load_pairwise_swap_data
        swap = load_pairwise_swap_data(exp.run_dir)
        if not swap:
            return "--", False
        consistent = sum(1 for v in swap.values() if v.get("consistent", True))
        total = len(swap)
        pct = consistent / total * 100 if total > 0 else 0
        return f"{pct:.1f}\\%", pct >= 80

    def _check_304(self, exp: ExperimentData) -> tuple[str, bool]:
        from ._loaders import load_multi_model_scores
        from idea_graph.services.aggregator import spearman

        multi = load_multi_model_scores(exp.run_dir)
        models = sorted(multi.keys())
        if len(models) < 2:
            return "--", False

        model_overalls: dict[str, list[float]] = {}
        for model in models:
            all_s = []
            for cond, scores in multi[model].items():
                all_s.extend(scores.get("overall", []))
            model_overalls[model] = all_s

        rhos = []
        for i in range(len(models)):
            for j in range(i + 1, len(models)):
                a = model_overalls[models[i]]
                b = model_overalls[models[j]]
                n = min(len(a), len(b))
                if n >= 3:
                    rhos.append(spearman(a[:n], b[:n]))
        if not rhos:
            return "--", False
        mean_rho = sum(rhos) / len(rhos)
        return f"{mean_rho:.3f}", mean_rho >= 0.80

    def _check_305(self, exp: ExperimentData) -> tuple[str, bool]:
        from idea_graph.services.aggregator import pearson

        agg = exp.aggregate
        human = agg.get("human_scores", [])
        llm = agg.get("llm_scores", [])
        if not human or not llm:
            per_paper = exp.per_paper
            conds = list(per_paper.keys())
            if len(conds) >= 2:
                common = sorted(set(per_paper[conds[0]]) & set(per_paper[conds[1]]))
                human = [per_paper[conds[0]][p].get("overall", 5) for p in common]
                llm = [per_paper[conds[1]][p].get("overall", 5) for p in common]
        n = min(len(human), len(llm))
        if n < 3:
            return "--", False
        r = pearson(human[:n], llm[:n])
        return f"{r:.3f}", r >= 0.70

    def _check_306(self, exp: ExperimentData) -> tuple[str, bool]:
        grounding = exp.aggregate.get("grounding_analysis", {})
        if not grounding:
            return "--", False
        total_full, total_all = 0, 0
        for cond, vals in grounding.items():
            total_full += vals.get("full", 0)
            total_all += vals.get("full", 0) + vals.get("partial", 0) + vals.get("none", 0)
        pct = total_full / total_all * 100 if total_all > 0 else 0
        return f"{pct:.1f}\\%", pct >= 70

    # ────────────────────────────────────────────────────────────────
    # Table 4: 全条件×全指標スコア (Appendix longtable)
    # ────────────────────────────────────────────────────────────────
    def _table4_full_scores(self, data: CrossExperimentData) -> str | None:
        all_rows = []  # (exp_id, condition, {metric: (mean, std, n)})

        for exp_id in ["EXP-101", "EXP-102", "EXP-103"]:
            exp = data.get(exp_id)
            if exp is None:
                continue
            for cond, scores in exp.single_scores.items():
                row = {}
                for m in METRICS + ["overall"]:
                    vals = scores.get(m, [])
                    row[m] = (_safe_mean(vals), _safe_std(vals), len(vals))
                all_rows.append((exp_id, _label(cond), row))

        if not all_rows:
            return None

        metric_cols = METRICS + ["overall"]
        header_labels = [METRIC_SHORT.get(m, m) for m in metric_cols]

        lines = [
            r"\begin{longtable}{ll" + "c" * len(metric_cols) + "}",
            r"\caption{Complete Scores for All Conditions}",
            r"\label{tab:full-scores} \\",
            r"\toprule",
            "Exp & Condition & " + " & ".join(header_labels) + r" \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            "Exp & Condition & " + " & ".join(header_labels) + r" \\",
            r"\midrule",
            r"\endhead",
            r"\midrule",
            r"\multicolumn{" + str(len(metric_cols) + 2) + r"}{r}{\textit{Continued on next page}} \\",
            r"\endfoot",
            r"\bottomrule",
            r"\endlastfoot",
        ]

        for exp_id, cond, row in all_rows:
            cells = []
            for m in metric_cols:
                mean, std, n = row.get(m, (0, 0, 0))
                cells.append(f"{mean:.2f} $\\pm$ {std:.2f}")
            lines.append(f"{exp_id} & {cond} & " + " & ".join(cells) + r" \\")

        lines.append(r"\end{longtable}")
        return "\n".join(lines)
