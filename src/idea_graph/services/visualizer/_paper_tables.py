"""Publication-quality LaTeX + Markdown tables for the research paper.

Each table method corresponds to one numbered table in the paper.
Missing experiment data is handled gracefully — the table is skipped
and an empty path list is returned.

Output: .tex (booktabs) + .md per table.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._style import (
    METRICS,
    METRIC_SHORT,
    METRIC_DISPLAY,
    safe_mean,
    safe_std,
    safe_sem,
    clean_condition,
    logger,
)
from ._cross_loader import CrossExperimentLoader, CrossExperimentData
from ._loaders import (
    load_pairwise_elo_by_source,
    load_pairwise_elo_per_paper,
    load_single_scores,
    load_repeat_scores,
    load_pairwise_swap_data,
    load_single_scores_per_paper,
)

from ._style import display_name, color_for  # used for method labels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_table(
    output_dir: Path,
    name: str,
    content: dict[str, str],
) -> list[Path]:
    """Write latex and markdown strings to files, return saved paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ext, key in [("tex", "latex"), ("md", "markdown")]:
        text = content.get(key, "")
        if not text:
            continue
        p = output_dir / f"{name}.{ext}"
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    return paths


def _bold_best_latex(values: list[str], raw: list[float]) -> list[str]:
    """Return a copy of *values* with the maximum entry wrapped in \\textbf."""
    if not raw:
        return values
    best_idx = int(max(range(len(raw)), key=lambda i: raw[i]))
    out = list(values)
    out[best_idx] = r"\textbf{" + out[best_idx] + "}"
    return out


def _bold_best_md(values: list[str], raw: list[float]) -> list[str]:
    """Return a copy of *values* with the maximum entry wrapped in **bold**."""
    if not raw:
        return values
    best_idx = int(max(range(len(raw)), key=lambda i: raw[i]))
    out = list(values)
    out[best_idx] = f"**{out[best_idx]}**"
    return out


def _extract_sweep(conditions: list[str]) -> tuple[list[float], list[str]] | None:
    """Extract numeric parameter from condition names."""
    vals: list[tuple[float, str]] = []
    for c in conditions:
        nums = re.findall(r"(\d+(?:\.\d+)?)", c)
        if nums:
            vals.append((float(nums[-1]), c))
    if len(vals) < 2:
        return None
    vals.sort(key=lambda x: x[0])
    return [v[0] for v in vals], [v[1] for v in vals]


# ═══════════════════════════════════════════════════════════════════════════
# PaperTableGenerator
# ═══════════════════════════════════════════════════════════════════════════


class PaperTableGenerator:
    """Generate the main numbered tables for the research paper.

    Outputs booktabs LaTeX (.tex) and pipe-style Markdown (.md)
    for each table.
    """

    def __init__(self, runs_base: str | Path) -> None:
        self.runs_base = Path(runs_base)
        self._data: CrossExperimentData | None = None

    # -- data access --------------------------------------------------------

    def _ensure_data(self) -> CrossExperimentData:
        if self._data is None:
            self._data = CrossExperimentLoader(self.runs_base).load()
        return self._data

    # -- public entry point -------------------------------------------------

    def generate_all(
        self,
        output_dir: str | Path,
    ) -> dict[str, list[Path]]:
        """Generate all paper tables and return ``{name: [paths]}``."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        data = self._ensure_data()

        results: dict[str, list[Path]] = {}
        generators = [
            ("table1_main_results", self._table1_main_results),
            ("table2_single_scores", self._table2_single_scores),
            ("table3_ablation_summary", self._table3_ablation_summary),
            ("table4_evaluation_validity", self._table4_evaluation_validity),
        ]

        for name, gen_fn in generators:
            try:
                content = gen_fn(data)
                if content is None:
                    logger.info("Skipped %s (insufficient data)", name)
                    continue
                paths = _write_table(out, name, content)
                if paths:
                    results[name] = paths
                    logger.info("Generated table: %s (%d files)", name, len(paths))
            except Exception as e:
                logger.warning("Failed to generate %s: %s", name, e, exc_info=True)

        return results

    # ======================================================================
    # Table 1 — Main Results: ELO by Method (EXP-101)
    # ======================================================================

    def _table1_main_results(
        self, data: CrossExperimentData,
    ) -> dict[str, str] | None:
        """ELO +/- SEM per metric per method.  Bold best per column."""
        exp = data.get("EXP-101")
        if exp is None:
            return None

        elo = load_pairwise_elo_by_source(exp.run_dir)
        if not elo:
            return None

        sources = sorted(elo.keys())
        disp_metrics = METRICS + ["overall"]

        # Pre-compute means for bold detection
        means_grid: dict[str, list[float]] = {}  # metric -> [mean per source]
        for m in disp_metrics:
            means_grid[m] = [safe_mean(elo[s].get(m, [])) for s in sources]

        # -- LaTeX --
        col_spec = "l" + "r" * len(disp_metrics)
        header_cells = ["Method"] + [METRIC_SHORT.get(m, m) for m in disp_metrics]
        header = " & ".join(header_cells) + r" \\"

        tex_rows: list[str] = []
        for s_idx, src in enumerate(sources):
            name = display_name(src)
            cells: list[str] = []
            raw_vals: list[float] = []
            for m in disp_metrics:
                vals = elo[src].get(m, [])
                mn = safe_mean(vals)
                se = safe_sem(vals)
                raw_vals.append(mn)
                if se > 0:
                    cells.append(f"{mn:.0f} $\\pm$ {se:.0f}")
                else:
                    cells.append(f"{mn:.0f}")
            # bold best per column later
            tex_rows.append((name, cells, raw_vals))

        # Apply bold per column
        for col_idx, m in enumerate(disp_metrics):
            col_raw = [row[2][col_idx] for row in tex_rows]
            if not col_raw:
                continue
            best_val = max(col_raw)
            for row in tex_rows:
                if row[2][col_idx] == best_val:
                    row[1][col_idx] = r"\textbf{" + row[1][col_idx] + "}"

        latex_body = "\n".join(
            f"    {row[0]} & " + " & ".join(row[1]) + r" \\"
            for row in tex_rows
        )

        latex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            r"  \caption{Main results: ELO ratings by method (EXP-101).}" + "\n"
            r"  \label{tab:main-results}" + "\n"
            f"  \\begin{{tabular}}{{{col_spec}}}\n"
            r"    \toprule" + "\n"
            f"    {header}\n"
            r"    \midrule" + "\n"
            f"{latex_body}\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )

        # -- Markdown --
        md_header_cells = ["Method"] + [METRIC_SHORT.get(m, m) for m in disp_metrics]
        md_header = "| " + " | ".join(md_header_cells) + " |"
        md_sep = "|" + "|".join(
            " :---: " if i == 0 else " ---: " for i in range(len(md_header_cells))
        ) + "|"

        md_rows: list[str] = []
        for s_idx, src in enumerate(sources):
            name = display_name(src)
            cells: list[str] = []
            raw_for_bold: list[float] = []
            for m in disp_metrics:
                vals = elo[src].get(m, [])
                mn = safe_mean(vals)
                se = safe_sem(vals)
                raw_for_bold.append(mn)
                if se > 0:
                    cells.append(f"{mn:.0f} +/- {se:.0f}")
                else:
                    cells.append(f"{mn:.0f}")
            md_rows.append((name, cells, raw_for_bold))

        for col_idx, m in enumerate(disp_metrics):
            col_raw = [row[2][col_idx] for row in md_rows]
            if not col_raw:
                continue
            best_val = max(col_raw)
            for row in md_rows:
                if row[2][col_idx] == best_val:
                    row[1][col_idx] = f"**{row[1][col_idx]}**"

        md_body = "\n".join(
            "| " + row[0] + " | " + " | ".join(row[1]) + " |"
            for row in md_rows
        )
        markdown = f"{md_header}\n{md_sep}\n{md_body}\n"

        return {"latex": latex, "markdown": markdown}

    # ======================================================================
    # Table 2 — Single Evaluation Scores (EXP-103..106)
    # ======================================================================

    def _table2_single_scores(
        self, data: CrossExperimentData,
    ) -> dict[str, str] | None:
        """Mean +/- std per metric.  Bold best per column."""
        # Map experiment -> method label
        exp_method: list[tuple[str, str]] = [
            ("EXP-103", "IdeaGraph"),
            ("EXP-104", "Direct LLM"),
            ("EXP-105", "CoI-Agent"),
            ("EXP-106", "Target Paper"),
        ]

        all_scores: dict[str, dict[str, list[float]]] = {}
        method_order: list[str] = []

        for exp_id, label in exp_method:
            exp = data.get(exp_id)
            if exp is None or not exp.single_scores:
                continue
            # Merge all conditions under this experiment as a single method
            merged: dict[str, list[float]] = {}
            for _cond, cond_scores in exp.single_scores.items():
                for m in METRICS + ["overall"]:
                    merged.setdefault(m, []).extend(cond_scores.get(m, []))
            all_scores[label] = merged
            method_order.append(label)

        if not all_scores:
            return None

        disp_metrics = METRICS + ["overall"]

        # -- LaTeX --
        col_spec = "l" + "r" * len(disp_metrics)
        header_cells = ["Method"] + [METRIC_SHORT.get(m, m) for m in disp_metrics]
        header = " & ".join(header_cells) + r" \\"

        tex_rows: list[tuple[str, list[str], list[float]]] = []
        for method in method_order:
            cells: list[str] = []
            raw: list[float] = []
            for m in disp_metrics:
                vals = all_scores[method].get(m, [])
                mn = safe_mean(vals)
                sd = safe_std(vals)
                raw.append(mn)
                if sd > 0:
                    cells.append(f"{mn:.2f} $\\pm$ {sd:.2f}")
                else:
                    cells.append(f"{mn:.2f}")
            tex_rows.append((method, cells, raw))

        # Bold best per column
        for col_idx in range(len(disp_metrics)):
            col_raw = [row[2][col_idx] for row in tex_rows]
            if not col_raw:
                continue
            best = max(col_raw)
            for row in tex_rows:
                if row[2][col_idx] == best:
                    row[1][col_idx] = r"\textbf{" + row[1][col_idx] + "}"

        latex_body = "\n".join(
            f"    {row[0]} & " + " & ".join(row[1]) + r" \\"
            for row in tex_rows
        )

        latex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            r"  \caption{Single evaluation scores by method.}" + "\n"
            r"  \label{tab:single-scores}" + "\n"
            f"  \\begin{{tabular}}{{{col_spec}}}\n"
            r"    \toprule" + "\n"
            f"    {header}\n"
            r"    \midrule" + "\n"
            f"{latex_body}\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )

        # -- Markdown --
        md_header = "| " + " | ".join(header_cells) + " |"
        md_sep = "| :--- |" + " ---: |" * len(disp_metrics)

        md_rows: list[tuple[str, list[str], list[float]]] = []
        for method in method_order:
            cells = []
            raw = []
            for m in disp_metrics:
                vals = all_scores[method].get(m, [])
                mn = safe_mean(vals)
                sd = safe_std(vals)
                raw.append(mn)
                if sd > 0:
                    cells.append(f"{mn:.2f} +/- {sd:.2f}")
                else:
                    cells.append(f"{mn:.2f}")
            md_rows.append((method, cells, raw))

        for col_idx in range(len(disp_metrics)):
            col_raw = [row[2][col_idx] for row in md_rows]
            if not col_raw:
                continue
            best = max(col_raw)
            for row in md_rows:
                if row[2][col_idx] == best:
                    row[1][col_idx] = f"**{row[1][col_idx]}**"

        md_body = "\n".join(
            "| " + row[0] + " | " + " | ".join(row[1]) + " |"
            for row in md_rows
        )
        markdown = f"{md_header}\n{md_sep}\n{md_body}\n"

        return {"latex": latex, "markdown": markdown}

    # ======================================================================
    # Table 3 — Ablation Summary
    # ======================================================================

    def _table3_ablation_summary(
        self, data: CrossExperimentData,
    ) -> dict[str, str] | None:
        """Best vs default value per ablation parameter, with delta overall."""
        ablation_defs: list[tuple[str, str, str | None]] = [
            # (exp_id, parameter_name, default_condition_hint)
            ("EXP-201", "Max Hops", None),
            ("EXP-202", "Graph Format", None),
            ("EXP-203", "Prompt Scope", None),
            ("EXP-204", "Path Count", None),
            ("EXP-206", "Num Proposals", None),
        ]

        rows: list[dict[str, str]] = []
        raw_deltas: list[float] = []

        for exp_id, param_name, _default_hint in ablation_defs:
            exp = data.get(exp_id)
            if exp is None:
                continue

            scores = load_single_scores(exp.run_dir)
            if not scores:
                continue

            conds = list(scores.keys())
            if len(conds) < 2:
                continue

            # Compute overall mean per condition
            cond_means: dict[str, float] = {}
            for c in conds:
                cond_means[c] = safe_mean(scores[c].get("overall", []))

            # Best condition
            best_cond = max(cond_means, key=cond_means.get)  # type: ignore[arg-type]
            best_val = cond_means[best_cond]

            # Default = first condition if no hint, or "default"-containing name
            default_cond = conds[0]
            for c in conds:
                if "default" in c.lower() or "baseline" in c.lower():
                    default_cond = c
                    break
            default_val = cond_means[default_cond]

            delta = best_val - default_val

            # Extract readable condition labels
            best_label = clean_condition(best_cond)
            default_label = clean_condition(default_cond)

            rows.append({
                "param": param_name,
                "best": best_label,
                "default": default_label,
                "delta": f"{delta:+.2f}",
            })
            raw_deltas.append(delta)

        if not rows:
            return None

        # -- LaTeX --
        header = r"Parameter & Best Value & Default Value & $\Delta$ Overall \\"
        tex_rows: list[str] = []
        for row in rows:
            d_str = row["delta"]
            # Highlight positive deltas
            if d_str.startswith("+") and float(d_str) > 0:
                d_str_tex = r"\textbf{" + d_str + "}"
            else:
                d_str_tex = d_str
            tex_rows.append(
                f"    {row['param']} & {row['best']} & {row['default']} & {d_str_tex}" + r" \\"
            )

        latex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            r"  \caption{Ablation summary: best vs.\ default parameter settings.}" + "\n"
            r"  \label{tab:ablation-summary}" + "\n"
            r"  \begin{tabular}{llll}" + "\n"
            r"    \toprule" + "\n"
            f"    {header}\n"
            r"    \midrule" + "\n"
            + "\n".join(tex_rows) + "\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )

        # -- Markdown --
        md_header = "| Parameter | Best Value | Default Value | Delta Overall |"
        md_sep = "| :--- | :--- | :--- | ---: |"
        md_rows_str: list[str] = []
        for row in rows:
            d = row["delta"]
            if d.startswith("+") and float(d) > 0:
                d = f"**{d}**"
            md_rows_str.append(
                f"| {row['param']} | {row['best']} | {row['default']} | {d} |"
            )
        markdown = f"{md_header}\n{md_sep}\n" + "\n".join(md_rows_str) + "\n"

        return {"latex": latex, "markdown": markdown}

    # ======================================================================
    # Table 4 — Evaluation Validity Metrics
    # ======================================================================

    def _table4_evaluation_validity(
        self, data: CrossExperimentData,
    ) -> dict[str, str] | None:
        """Mode consistency, reproducibility, position bias in one table."""
        validity_rows: list[dict[str, str]] = []

        # --- Mode Consistency: Spearman rho (EXP-301) ---
        exp301 = data.get("EXP-301")
        if exp301 is not None:
            rho = self._compute_mode_consistency(exp301)
            if rho is not None:
                threshold = 0.7
                status = "Y" if abs(rho) >= threshold else "N"
                validity_rows.append({
                    "metric": "Mode Consistency (Spearman $\\rho$)",
                    "metric_md": "Mode Consistency (Spearman rho)",
                    "value": f"{rho:.3f}",
                    "threshold": f"{threshold:.1f}",
                    "status": status,
                })

        # --- Reproducibility: CV of repeat scores (EXP-302) ---
        exp302 = data.get("EXP-302")
        if exp302 is not None:
            cv = self._compute_reproducibility_cv(exp302)
            if cv is not None:
                threshold = 0.10  # CV < 10% is good
                status = "Y" if cv <= threshold else "N"
                validity_rows.append({
                    "metric": "Reproducibility (CV)",
                    "metric_md": "Reproducibility (CV)",
                    "value": f"{cv:.3f}",
                    "threshold": f"$\\leq$ {threshold:.2f}",
                    "threshold_md": f"<= {threshold:.2f}",
                    "status": status,
                })

        # --- Position Bias: Agreement rate (EXP-303) ---
        exp303 = data.get("EXP-303")
        if exp303 is not None:
            agree = self._compute_position_bias(exp303)
            if agree is not None:
                threshold = 80.0  # >= 80% agreement
                status = "Y" if agree >= threshold else "N"
                validity_rows.append({
                    "metric": "Position Bias (Agreement)",
                    "metric_md": "Position Bias (Agreement)",
                    "value": f"{agree:.1f}\\%",
                    "value_md": f"{agree:.1f}%",
                    "threshold": f"$\\geq$ {threshold:.0f}\\%",
                    "threshold_md": f">= {threshold:.0f}%",
                    "status": status,
                })

        if not validity_rows:
            return None

        # -- LaTeX --
        status_sym = {"Y": r"\checkmark", "N": r"$\times$"}
        header = r"Metric & Value & Threshold & Status \\"
        tex_rows: list[str] = []
        for row in validity_rows:
            s = status_sym.get(row["status"], row["status"])
            val = row.get("value", "")
            thr = row.get("threshold", "")
            tex_rows.append(
                f"    {row['metric']} & {val} & {thr} & {s}" + r" \\"
            )

        latex = (
            r"\begin{table}[htbp]" + "\n"
            r"  \centering" + "\n"
            r"  \caption{Evaluation validity metrics.}" + "\n"
            r"  \label{tab:eval-validity}" + "\n"
            r"  \begin{tabular}{llll}" + "\n"
            r"    \toprule" + "\n"
            f"    {header}\n"
            r"    \midrule" + "\n"
            + "\n".join(tex_rows) + "\n"
            r"    \bottomrule" + "\n"
            r"  \end{tabular}" + "\n"
            r"\end{table}" + "\n"
        )

        # -- Markdown --
        md_header = "| Metric | Value | Threshold | Status |"
        md_sep = "| :--- | ---: | :--- | :---: |"
        md_body_lines: list[str] = []
        for row in validity_rows:
            val = row.get("value_md", row.get("value", "").replace("\\%", "%"))
            thr = row.get("threshold_md", row.get("threshold", "").replace("$\\geq$", ">=").replace("$\\leq$", "<=").replace("\\%", "%"))
            # Remove any remaining LaTeX
            val = val.replace("$", "").replace("\\rho", "rho")
            thr = thr.replace("$", "").replace("\\rho", "rho")
            status_emoji = "Pass" if row["status"] == "Y" else "Fail"
            md_body_lines.append(
                f"| {row['metric_md']} | {val} | {thr} | {status_emoji} |"
            )
        markdown = f"{md_header}\n{md_sep}\n" + "\n".join(md_body_lines) + "\n"

        return {"latex": latex, "markdown": markdown}

    # -- Table 4 sub-computations ------------------------------------------

    @staticmethod
    def _compute_mode_consistency(exp) -> float | None:
        """Compute Spearman rho between single and pairwise scores for EXP-301.

        For each paper × condition, match the single-mode overall score
        with the per-paper pairwise ELO for the same source.
        """
        per_paper = load_single_scores_per_paper(exp.run_dir)
        pw_per_paper = load_pairwise_elo_per_paper(exp.run_dir)

        single_vals: list[float] = []
        pairwise_vals: list[float] = []

        for cond, papers in per_paper.items():
            for paper_id, scores in papers.items():
                s_overall = scores.get("overall")
                if s_overall is None:
                    continue
                pw_paper = pw_per_paper.get(paper_id, {})
                for src, pw_val in pw_paper.items():
                    if src in cond or cond in src:
                        single_vals.append(s_overall)
                        pairwise_vals.append(pw_val)
                        break

        if len(single_vals) < 3:
            return None

        try:
            from idea_graph.services.aggregator import spearman
            return spearman(single_vals, pairwise_vals)
        except ImportError:
            return None

    @staticmethod
    def _compute_reproducibility_cv(exp) -> float | None:
        """Compute coefficient of variation across repeat evaluations."""
        repeat = load_repeat_scores(exp.run_dir)
        if not repeat:
            return None

        all_means: list[float] = []
        for _cond, metrics_by_repeat in repeat.items():
            overall_repeats = metrics_by_repeat.get("overall", [])
            for scores_list in overall_repeats:
                if scores_list:
                    all_means.append(safe_mean(scores_list))

        if len(all_means) < 2:
            return None

        mn = safe_mean(all_means)
        sd = safe_std(all_means)
        if mn == 0:
            return None
        return sd / mn

    @staticmethod
    def _compute_position_bias(exp) -> float | None:
        """Compute AB/BA agreement rate from swap test data."""
        swap = load_pairwise_swap_data(exp.run_dir)
        if not swap:
            return None

        total = 0
        consistent = 0
        for _paper, info in swap.items():
            ab = info.get("ab_winner", "")
            ba = info.get("ba_winner", "")
            if ab and ba:
                total += 1
                if ab == ba:
                    consistent += 1

        if total == 0:
            return None
        return consistent / total * 100.0
