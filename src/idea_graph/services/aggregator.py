"""実験結果の集計・統計サービス"""

from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any


METRICS = ["novelty", "significance", "feasibility", "clarity", "effectiveness"]


@dataclass
class ConditionScores:
    condition: str
    metric_values: dict[str, list[float]]


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.fmean(values))


def _safe_std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    return float(statistics.stdev(values))


def _rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j - 1) / 2 + 1
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def pearson(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        return 0.0
    mx = _safe_mean(x)
    my = _safe_mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = math.sqrt(sum((a - mx) ** 2 for a in x))
    deny = math.sqrt(sum((b - my) ** 2 for b in y))
    if denx == 0 or deny == 0:
        return 0.0
    return num / (denx * deny)


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(_rank(x), _rank(y))


def cohen_d(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma = _safe_mean(a)
    mb = _safe_mean(b)
    sa = _safe_std(a)
    sb = _safe_std(b)
    pooled = math.sqrt(((len(a) - 1) * sa * sa + (len(b) - 1) * sb * sb) / (len(a) + len(b) - 2))
    if pooled == 0:
        return 0.0
    return (ma - mb) / pooled


def cliffs_delta(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    greater = 0
    lower = 0
    for x in a:
        for y in b:
            if x > y:
                greater += 1
            elif x < y:
                lower += 1
    total = len(a) * len(b)
    return (greater - lower) / total if total else 0.0


def paired_permutation_pvalue(a: list[float], b: list[float], n_iter: int = 5000, seed: int = 20260207) -> float:
    if len(a) != len(b) or not a:
        return 1.0
    diffs = [x - y for x, y in zip(a, b)]
    observed = abs(_safe_mean(diffs))
    rng = random.Random(seed)

    extreme = 0
    for _ in range(n_iter):
        signs = [1 if rng.random() > 0.5 else -1 for _ in diffs]
        perm = abs(_safe_mean([d * s for d, s in zip(diffs, signs)]))
        if perm >= observed:
            extreme += 1
    return (extreme + 1) / (n_iter + 1)


def krippendorffs_alpha(reliability_data: list[list[float | None]], level: str = "interval") -> float:
    """Krippendorff's alpha（評価者間一致度）を計算する。

    Args:
        reliability_data: 評価者×項目の行列。None は欠損値。
        level: 測定尺度。"interval" のみ対応。

    Returns:
        alpha 値（-1.0〜1.0）。1.0 が完全一致。
    """
    if not reliability_data or not reliability_data[0]:
        return 0.0

    n_raters = len(reliability_data)
    n_items = len(reliability_data[0])

    # 各項目のペアを集めて observed disagreement を計算
    observed_pairs: list[tuple[float, float]] = []
    all_values: list[float] = []

    for j in range(n_items):
        item_values: list[float] = []
        for i in range(n_raters):
            v = reliability_data[i][j] if j < len(reliability_data[i]) else None
            if v is not None:
                item_values.append(v)
                all_values.append(v)
        # 項目内の全ペア
        for a_idx in range(len(item_values)):
            for b_idx in range(a_idx + 1, len(item_values)):
                observed_pairs.append((item_values[a_idx], item_values[b_idx]))

    if not observed_pairs or len(all_values) < 2:
        return 0.0

    # interval レベルの差分関数: (v1 - v2)^2
    def _diff(v1: float, v2: float) -> float:
        return (v1 - v2) ** 2

    d_o = _safe_mean([_diff(a, b) for a, b in observed_pairs])

    # expected disagreement: 全値の全ペア
    expected_pairs: list[float] = []
    for a_idx in range(len(all_values)):
        for b_idx in range(a_idx + 1, len(all_values)):
            expected_pairs.append(_diff(all_values[a_idx], all_values[b_idx]))

    d_e = _safe_mean(expected_pairs)

    if d_e == 0:
        return 1.0

    return 1.0 - (d_o / d_e)


def holm_bonferroni(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    ordered = sorted(pvalues.items(), key=lambda x: x[1])
    m = len(ordered)
    accepted: dict[str, bool] = {k: False for k in pvalues}
    for i, (key, pval) in enumerate(ordered):
        threshold = alpha / (m - i)
        if pval <= threshold:
            accepted[key] = True
        else:
            break
    return accepted


class ExperimentAggregator:
    """実験実行ディレクトリの集計を行う。"""

    def _load_single_condition_scores(
        self, run_dir: Path, mode: str = "all"
    ) -> list[ConditionScores]:
        """Single評価スコアを条件別に読み込む。

        Args:
            run_dir: 実行ディレクトリ
            mode: "all" で全提案を集計、"top" で各ファイルの最高スコア提案のみ
        """
        single_root = run_dir / "evaluations" / "single"
        if not single_root.exists():
            return []

        output: list[ConditionScores] = []
        for condition_dir in sorted(single_root.iterdir()):
            if not condition_dir.is_dir():
                continue
            metric_values: dict[str, list[float]] = {}
            for file in sorted(condition_dir.glob("*.json")):
                payload = json.loads(file.read_text(encoding="utf-8"))
                ranking = payload.get("ranking", [])
                if not ranking:
                    continue
                entries = [ranking[0]] if mode == "top" else ranking
                for entry in entries:
                    scores = entry.get("scores", [])
                    for metric in scores:
                        name = metric.get("metric")
                        score = metric.get("score")
                        if name is None or score is None:
                            continue
                        metric_values.setdefault(str(name), []).append(float(score))
                    metric_values.setdefault("overall", []).append(
                        float(entry.get("overall_score", 0.0))
                    )

            output.append(ConditionScores(condition=condition_dir.name, metric_values=metric_values))

        return output

    def _aggregate_single(self, scores: list[ConditionScores]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for condition_score in scores:
            metric_summary = {}
            for metric_name, values in condition_score.metric_values.items():
                metric_summary[metric_name] = {
                    "n": len(values),
                    "mean": _safe_mean(values),
                    "std": _safe_std(values),
                }
            summary[condition_score.condition] = metric_summary
        return summary

    def _pairwise_tests(self, scores: list[ConditionScores]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if len(scores) < 2:
            return out

        pvalues: dict[str, float] = {}
        for i in range(len(scores)):
            for j in range(i + 1, len(scores)):
                a = scores[i]
                b = scores[j]
                a_vals = a.metric_values.get("overall", [])
                b_vals = b.metric_values.get("overall", [])
                n = min(len(a_vals), len(b_vals))
                if n == 0:
                    continue
                a_vals = a_vals[:n]
                b_vals = b_vals[:n]
                key = f"{a.condition}_vs_{b.condition}"
                p = paired_permutation_pvalue(a_vals, b_vals)
                pvalues[key] = p
                out[key] = {
                    "n": n,
                    "pvalue_permutation": p,
                    "cohen_d": cohen_d(a_vals, b_vals),
                    "cliffs_delta": cliffs_delta(a_vals, b_vals),
                }

        corrected = holm_bonferroni(pvalues)
        for key, decision in corrected.items():
            if key in out:
                out[key]["holm_bonferroni_significant"] = decision
        return out

    def _aggregate_pairwise_files(self, run_dir: Path) -> dict[str, Any]:
        root = run_dir / "evaluations" / "pairwise"
        if not root.exists():
            return {}
        wins: dict[str, int] = {}
        for file in sorted(root.glob("*.json")):
            payload = json.loads(file.read_text(encoding="utf-8"))
            ranking = payload.get("ranking", [])
            if not ranking:
                continue
            top = ranking[0]
            source = str(top.get("source", "unknown"))
            wins[source] = wins.get(source, 0) + 1
        return {"top_rank_source_counts": wins}

    def _compute_inter_rater_reliability(self, run_dir: Path) -> dict[str, Any]:
        """repeat評価ファイル (*_r*.json) から Krippendorff's alpha を計算する。"""
        single_root = run_dir / "evaluations" / "single"
        if not single_root.exists():
            return {}

        result: dict[str, Any] = {}
        for condition_dir in sorted(single_root.iterdir()):
            if not condition_dir.is_dir():
                continue

            # paper_id ごとにrepeatファイルをグループ化
            repeat_groups: dict[str, dict[int, Path]] = {}
            for f in sorted(condition_dir.glob("*.json")):
                m = re.match(r"^(.+?)_r(\d+)\.json$", f.name)
                if m:
                    paper_key = m.group(1)
                    r_idx = int(m.group(2))
                    repeat_groups.setdefault(paper_key, {})[r_idx] = f

            if not repeat_groups:
                continue

            # 各指標に対して rater×item 行列を構築
            metric_matrices: dict[str, list[list[float | None]]] = {}
            n_repeats = max(max(reps.keys()) + 1 for reps in repeat_groups.values())
            items = sorted(repeat_groups.keys())

            for metric_name in METRICS + ["overall"]:
                matrix: list[list[float | None]] = []
                for r_idx in range(n_repeats):
                    row: list[float | None] = []
                    for item_key in items:
                        f = repeat_groups[item_key].get(r_idx)
                        if f is None:
                            row.append(None)
                            continue
                        payload = json.loads(f.read_text(encoding="utf-8"))
                        ranking = payload.get("ranking", [])
                        if not ranking:
                            row.append(None)
                            continue
                        top = ranking[0]
                        if metric_name == "overall":
                            val = top.get("overall_score")
                            row.append(float(val) if val is not None else None)
                        else:
                            found = None
                            for s in top.get("scores", []):
                                if s.get("metric") == metric_name:
                                    found = s.get("score")
                                    break
                            row.append(float(found) if found is not None else None)
                    matrix.append(row)
                metric_matrices[metric_name] = matrix

            condition_result: dict[str, float] = {}
            for metric_name, matrix in metric_matrices.items():
                alpha = krippendorffs_alpha(matrix)
                condition_result[metric_name] = round(alpha, 4)

            result[condition_dir.name] = {
                "n_items": len(items),
                "n_repeats": n_repeats,
                "krippendorffs_alpha": condition_result,
            }

        return result

    def aggregate(self, run_dir: str | Path) -> dict[str, Any]:
        run_path = Path(run_dir)
        if not run_path.exists():
            raise FileNotFoundError(f"run dir not found: {run_path}")

        condition_scores = self._load_single_condition_scores(run_path)
        single = self._aggregate_single(condition_scores)
        tests = self._pairwise_tests(condition_scores)
        pairwise = self._aggregate_pairwise_files(run_path)

        result: dict[str, Any] = {
            "run_dir": str(run_path),
            "single_summary": single,
            "comparison_tests": tests,
            "pairwise_summary": pairwise,
        }

        irr = self._compute_inter_rater_reliability(run_path)
        if irr:
            result["inter_rater_reliability"] = irr

        summary_dir = run_path / "summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / "aggregate.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    def compare(self, run_dirs: list[str | Path]) -> dict[str, Any]:
        if len(run_dirs) < 2:
            raise ValueError("compare requires at least two run directories")

        run_aggregates = [self.aggregate(run_dir) for run_dir in run_dirs]

        baseline = run_aggregates[0]
        baseline_metrics = baseline.get("single_summary", {})
        comparisons: dict[str, Any] = {}

        for current in run_aggregates[1:]:
            current_key = current["run_dir"]
            current_metrics = current.get("single_summary", {})
            delta: dict[str, Any] = {}
            all_conditions = sorted(set(baseline_metrics) | set(current_metrics))
            for condition in all_conditions:
                b = baseline_metrics.get(condition, {}).get("overall", {}).get("mean")
                c = current_metrics.get(condition, {}).get("overall", {}).get("mean")
                if b is None or c is None:
                    continue
                delta[condition] = c - b
            comparisons[current_key] = {"overall_mean_delta_vs_baseline": delta}

        return {
            "baseline": baseline["run_dir"],
            "comparisons": comparisons,
        }

    def export_human_eval_template(self, path: str | Path, proposal_ids: list[str]) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "proposal_id",
            "evaluator_id",
            "novelty",
            "significance",
            "feasibility",
            "clarity",
            "effectiveness",
            "comment",
        ]
        with output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for proposal_id in proposal_ids:
                writer.writerow({"proposal_id": proposal_id, "evaluator_id": ""})
        return output

    def load_human_eval(self, path: str | Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                record: dict[str, Any] = dict(row)
                for metric in ["novelty", "significance", "feasibility", "clarity", "effectiveness"]:
                    raw = record.get(metric)
                    record[metric] = float(raw) if raw not in {None, ""} else None
                records.append(record)
        return records

    def correlate_human_llm(
        self,
        human_csv: str | Path,
        llm_scores: dict[str, float],
    ) -> dict[str, float]:
        records = self.load_human_eval(human_csv)
        grouped: dict[str, list[float]] = {}
        for row in records:
            proposal_id = str(row.get("proposal_id", ""))
            metrics = [row.get(name) for name in ["novelty", "significance", "feasibility", "clarity", "effectiveness"]]
            valid = [float(v) for v in metrics if isinstance(v, (int, float))]
            if not proposal_id or not valid:
                continue
            grouped.setdefault(proposal_id, []).append(_safe_mean(valid))

        x: list[float] = []
        y: list[float] = []
        for proposal_id, human_values in grouped.items():
            if proposal_id not in llm_scores:
                continue
            x.append(_safe_mean(human_values))
            y.append(float(llm_scores[proposal_id]))

        return {
            "pearson_r": pearson(x, y),
            "spearman_rho": spearman(x, y),
            "n": float(len(x)),
        }
