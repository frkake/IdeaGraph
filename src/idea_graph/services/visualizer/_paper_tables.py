"""論文品質の LaTeX + Markdown テーブルを生成する PaperTableGenerator"""

from __future__ import annotations

from pathlib import Path

from ._style import METRICS, METRIC_SHORT, _safe_mean, _safe_std, logger
from ._cross_loader import CrossExperimentLoader, CrossExperimentData
from ._paper_figures import CONDITION_LABELS, METRIC_DISPLAY, _label
from ._loaders import load_pairwise_elo_by_source

from idea_graph.services.aggregator import cohen_d, paired_permutation_pvalue


class PaperTableGenerator:
    """論文品質の LaTeX + Markdown テーブルを生成する。"""

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
        """全テーブルを出力ディレクトリに生成する。"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        data = self._ensure_data()
        results: dict[str, list[Path]] = {}

        generators = [
            ("table1_main_results", self._table1_main_results),
            ("table2_full_scores", self._table2_full_scores),
        ]

        for name, gen_fn in generators:
            try:
                content = gen_fn(data)
                if content is None:
                    logger.info("Skipping %s (insufficient data)", name)
                    continue

                paths: list[Path] = []

                # LaTeX
                tex_path = output_path / f"{name}.tex"
                tex_path.write_text(content["latex"], encoding="utf-8")
                paths.append(tex_path)

                # Markdown
                md_path = output_path / f"{name}.md"
                md_path.write_text(content["markdown"], encoding="utf-8")
                paths.append(md_path)

                results[name] = paths
                logger.info("Generated table: %s (%d files)", name, len(paths))

            except Exception as e:
                logger.warning("Failed to generate %s: %s", name, e)

        return results

    def _table1_main_results(self, data: CrossExperimentData) -> dict[str, str] | None:
        """Table 1: 手法別メトリクス比較テーブル (EXP-101 ELO)"""
        exp101 = data.get("EXP-101")
        if not exp101:
            return None

        elo_by_source = load_pairwise_elo_by_source(exp101.run_dir)
        if not elo_by_source:
            return None

        sources = sorted(elo_by_source.keys())
        display_metrics = METRICS + ["overall"]

        # ── LaTeX ──
        col_spec = "l" + "r" * len(display_metrics)
        header = " & ".join(
            ["Method"] + [METRIC_DISPLAY.get(m, m) for m in display_metrics]
        ) + r" \\"

        rows = []
        for source in sources:
            name = _label(source)
            vals = []
            for m in display_metrics:
                mean = _safe_mean(elo_by_source[source].get(m, []))
                std = _safe_std(elo_by_source[source].get(m, []))
                if std > 0:
                    vals.append(f"{mean:.0f} $\\pm$ {std:.0f}")
                else:
                    vals.append(f"{mean:.0f}")
            rows.append(f"  {name} & " + " & ".join(vals) + r" \\")

        latex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            r"  \caption{Main Results: ELO Scores by Method}" + "\n"
            f"  \\begin{{tabular}}{{{col_spec}}}\n"
            r"    \toprule" + "\n"
            f"    {header}\n"
            r"    \midrule" + "\n"
            + "\n".join(f"    {r}" for r in rows) + "\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )

        # ── Markdown ──
        md_header = "| Method | " + " | ".join(METRIC_DISPLAY.get(m, m) for m in display_metrics) + " |"
        md_sep = "|--------|" + "|".join("--------:" for _ in display_metrics) + "|"
        md_rows = []
        for source in sources:
            name = _label(source)
            vals = []
            for m in display_metrics:
                mean = _safe_mean(elo_by_source[source].get(m, []))
                vals.append(f"{mean:.0f}")
            md_rows.append(f"| {name} | " + " | ".join(vals) + " |")

        markdown = f"## Main Results: ELO Scores\n\n{md_header}\n{md_sep}\n" + "\n".join(md_rows) + "\n"

        return {"latex": latex, "markdown": markdown}

    def _table2_full_scores(self, data: CrossExperimentData) -> dict[str, str] | None:
        """Table 2: 全条件 × 全指標の詳細スコアテーブル"""
        # 利用可能な Single 評価データを集約
        all_scores: dict[str, dict[str, list[float]]] = {}

        for exp_id in ["EXP-103", "EXP-104", "EXP-105", "EXP-106"]:
            exp = data.get(exp_id)
            if exp and exp.single_scores:
                for cond, scores in exp.single_scores.items():
                    all_scores[cond] = scores

        if not all_scores:
            return None

        conditions = sorted(all_scores.keys())
        display_metrics = METRICS + ["overall"]

        # ── LaTeX ──
        col_spec = "l" + "r" * len(display_metrics)
        header = " & ".join(
            ["Condition"] + [METRIC_DISPLAY.get(m, m) for m in display_metrics]
        ) + r" \\"

        rows = []
        for cond in conditions:
            name = _label(cond)
            vals = []
            for m in display_metrics:
                mean = _safe_mean(all_scores[cond].get(m, []))
                std = _safe_std(all_scores[cond].get(m, []))
                if std > 0:
                    vals.append(f"{mean:.2f} $\\pm$ {std:.2f}")
                else:
                    vals.append(f"{mean:.2f}")
            rows.append(f"  {name} & " + " & ".join(vals) + r" \\")

        latex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            r"  \caption{Full Scores by Condition}" + "\n"
            f"  \\begin{{tabular}}{{{col_spec}}}\n"
            r"    \toprule" + "\n"
            f"    {header}\n"
            r"    \midrule" + "\n"
            + "\n".join(f"    {r}" for r in rows) + "\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )

        # ── Markdown ──
        md_header = "| Condition | " + " | ".join(METRIC_DISPLAY.get(m, m) for m in display_metrics) + " |"
        md_sep = "|-----------|" + "|".join("--------:" for _ in display_metrics) + "|"
        md_rows = []
        for cond in conditions:
            name = _label(cond)
            vals = [f"{_safe_mean(all_scores[cond].get(m, [])):.2f}" for m in display_metrics]
            md_rows.append(f"| {name} | " + " | ".join(vals) + " |")

        markdown = f"## Full Scores by Condition\n\n{md_header}\n{md_sep}\n" + "\n".join(md_rows) + "\n"

        return {"latex": latex, "markdown": markdown}
