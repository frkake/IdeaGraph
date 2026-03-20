"""Data loading utilities for experiment results.

Reads JSON files from experiment run directories and returns
structured data ready for visualization.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._style import METRICS

# ---------------------------------------------------------------------------
# Module-level paper ID filter (include / exclude)
# ---------------------------------------------------------------------------
_paper_id_filter: set[str] | None = None
_paper_id_exclude: set[str] | None = None


def set_paper_filter(
    paper_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
) -> None:
    """Set the active paper ID filter. Pass None to clear."""
    global _paper_id_filter, _paper_id_exclude
    _paper_id_filter = set(paper_ids) if paper_ids else None
    _paper_id_exclude = set(exclude_ids) if exclude_ids else None


def _file_matches_filter(f: Path) -> bool:
    """Check whether a JSON file's paper_id passes the current filter."""
    if _paper_id_filter is None and _paper_id_exclude is None:
        return True
    paper_id = re.sub(r"_r\d+$", "", f.stem)
    if _paper_id_exclude and paper_id in _paper_id_exclude:
        return False
    if _paper_id_filter is not None:
        return paper_id in _paper_id_filter
    return True


def load_experiment_meta(run_dir: Path) -> dict[str, Any]:
    """Load summary.json metadata."""
    p = run_dir / "summary.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_metadata(run_dir: Path) -> dict[str, Any]:
    """Load metadata.json (execution details)."""
    p = run_dir / "metadata.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_config(run_dir: Path) -> dict[str, Any]:
    """Load config.yaml (experiment configuration)."""
    p = run_dir / "config.yaml"
    if p.exists():
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def load_aggregate(run_dir: Path) -> dict[str, Any]:
    """Load summary/aggregate.json."""
    p = run_dir / "summary" / "aggregate.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_single_scores(run_dir: Path) -> dict[str, dict[str, list[float]]]:
    """Load single evaluation scores: {condition: {metric: [scores]}}."""
    result: dict[str, dict[str, list[float]]] = {}
    root = run_dir / "evaluations" / "single"
    if not root.exists():
        return result
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        scores: dict[str, list[float]] = {m: [] for m in METRICS}
        scores["overall"] = []
        for f in sorted(cond_dir.glob("*.json")):
            if not _file_matches_filter(f):
                continue
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
        result[cond_dir.name] = scores
    return result


def load_single_scores_per_paper(
    run_dir: Path,
) -> dict[str, dict[str, dict[str, float]]]:
    """Load {condition: {paper_id: {metric: mean_score}}}."""
    result: dict[str, dict[str, dict[str, float]]] = {}
    root = run_dir / "evaluations" / "single"
    if not root.exists():
        return result
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        papers: dict[str, dict[str, float]] = {}
        for f in sorted(cond_dir.glob("*.json")):
            if not _file_matches_filter(f):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                paper_id = re.sub(r"_r\d+$", "", f.stem)
                ranking = data.get("ranking", [])
                if not ranking:
                    continue
                top = ranking[0]
                scores: dict[str, float] = {}
                for s in top.get("scores", []):
                    metric = s.get("metric", "")
                    score = s.get("score")
                    if metric and score is not None:
                        scores[metric] = float(score)
                overall = top.get("overall_score")
                if overall is not None:
                    scores["overall"] = float(overall)
                papers[paper_id] = scores
            except Exception:
                continue
        result[cond_dir.name] = papers
    return result


def load_pairwise_wins(run_dir: Path) -> dict[str, int]:
    """Load source-level win counts from pairwise evaluations."""
    wins: dict[str, int] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return wins
    for f in sorted(root.glob("*.json")):
        if not _file_matches_filter(f):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ranking = data.get("ranking", [])
            if ranking:
                source = str(ranking[0].get("source", "unknown"))
                wins[source] = wins.get(source, 0) + 1
        except Exception:
            continue
    return wins


def load_pairwise_details(run_dir: Path) -> list[dict[str, Any]]:
    """Load all pairwise evaluation files as raw dicts."""
    results: list[dict[str, Any]] = []
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return results
    for f in sorted(root.glob("*.json")):
        if not _file_matches_filter(f):
            continue
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results


def load_pairwise_elo_by_source(
    run_dir: Path,
) -> dict[str, dict[str, list[float]]]:
    """Load {source: {metric: [elo_values]}} from pairwise files."""
    result: dict[str, dict[str, list[float]]] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return result
    for f in sorted(root.glob("*.json")):
        if not _file_matches_filter(f):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for entry in data.get("ranking", []):
                source = str(entry.get("source", "unknown"))
                overall = entry.get("overall_score")
                by_metric = entry.get("scores_by_metric", {})
                if source not in result:
                    result[source] = {}
                for metric, elo in by_metric.items():
                    if elo is not None:
                        result[source].setdefault(metric, []).append(float(elo))
                if overall is not None:
                    result[source].setdefault("overall", []).append(float(overall))
        except Exception:
            continue
    return result


def load_pairwise_wins_by_source(run_dir: Path) -> dict[str, dict[str, int]]:
    """Load {winner_source: {loser_source: win_count}}."""
    result: dict[str, dict[str, int]] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return result
    for f in sorted(root.glob("*.json")):
        if not _file_matches_filter(f):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            ranking = data.get("ranking", [])
            if len(ranking) < 2:
                continue
            source_best: dict[str, float] = {}
            for entry in ranking:
                source = str(entry.get("source", "unknown"))
                score = entry.get("overall_score", 0)
                if source not in source_best or score > source_best[source]:
                    source_best[source] = score
            sources = sorted(source_best, key=lambda s: source_best[s], reverse=True)
            if len(sources) >= 2:
                winner = sources[0]
                for loser in sources[1:]:
                    result.setdefault(winner, {})
                    result[winner][loser] = result[winner].get(loser, 0) + 1
        except Exception:
            continue
    return result


def load_pairwise_swap_data(run_dir: Path) -> dict[str, list[dict]]:
    """Load swap test data: {paper_id: [comparison_swap_entries]}."""
    result: dict[str, list[dict]] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return result
    for f in sorted(root.glob("*.json")):
        if not _file_matches_filter(f):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            entries = []
            for pr in data.get("pairwise_results", []):
                swap = pr.get("swap_test_raw")
                if swap:
                    entries.append(swap)
            if entries:
                result[f.stem] = entries
        except Exception:
            continue
    return result


def load_paper_degrees(run_dir: Path) -> dict[str, int]:
    """Load {paper_id: degree} from summary.json records."""
    p = run_dir / "summary.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        degrees: dict[str, int] = {}
        for rec in data.get("records", []):
            paper_id = rec.get("paper_id", "")
            degree = rec.get("degree")
            if paper_id and degree is not None:
                if _paper_id_exclude and paper_id in _paper_id_exclude:
                    continue
                if _paper_id_filter is not None and paper_id not in _paper_id_filter:
                    continue
                degrees[paper_id] = int(degree)
        return degrees
    except Exception:
        return {}


def load_repeat_scores(run_dir: Path) -> dict[str, dict[str, list[list[float]]]]:
    """Load repeat evaluation data: {condition: {metric: [[repeat_0_scores], [repeat_1_scores], ...]}}."""
    result: dict[str, dict[str, list[list[float]]]] = {}
    root = run_dir / "evaluations" / "single"
    if not root.exists():
        return result
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        repeat_data: dict[int, dict[str, list[float]]] = {}
        for f in sorted(cond_dir.glob("*.json")):
            if not _file_matches_filter(f):
                continue
            m = re.match(r"^(.+?)_r(\d+)\.json$", f.name)
            r_idx = int(m.group(2)) if m else 0
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                for entry in data.get("ranking", []):
                    if r_idx not in repeat_data:
                        repeat_data[r_idx] = {met: [] for met in METRICS + ["overall"]}
                    for s in entry.get("scores", []):
                        metric = s.get("metric", "")
                        score = s.get("score")
                        if metric in repeat_data[r_idx] and score is not None:
                            repeat_data[r_idx][metric].append(float(score))
                    overall = entry.get("overall_score")
                    if overall is not None:
                        repeat_data[r_idx]["overall"].append(float(overall))
            except Exception:
                continue
        if not repeat_data:
            continue
        metrics_by_repeat: dict[str, list[list[float]]] = {}
        for r_idx in sorted(repeat_data):
            for metric_name, vals in repeat_data[r_idx].items():
                metrics_by_repeat.setdefault(metric_name, []).append(vals)
        result[cond_dir.name] = metrics_by_repeat
    return result


def load_pairwise_elo_per_paper(
    run_dir: Path,
) -> dict[str, dict[str, float]]:
    """Load {paper_id: {source: mean_overall_elo}} from pairwise files.

    Unlike load_pairwise_elo_by_source which aggregates across papers,
    this keeps per-paper resolution — essential for mode consistency analysis.
    """
    result: dict[str, dict[str, float]] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return result
    for f in sorted(root.glob("*.json")):
        if not _file_matches_filter(f):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            paper_id = f.stem
            source_scores: dict[str, list[float]] = {}
            for entry in data.get("ranking", []):
                src = str(entry.get("source", ""))
                overall = entry.get("overall_score")
                if src and overall is not None:
                    source_scores.setdefault(src, []).append(float(overall))
            if source_scores:
                result[paper_id] = {
                    src: sum(vals) / len(vals)
                    for src, vals in source_scores.items()
                }
        except Exception:
            continue
    return result


def load_multi_model_scores(
    run_dir: Path,
) -> dict[str, dict[str, dict[str, list[float]]]]:
    """Load {model: {condition: {metric: [scores]}}} for cross-model evaluation."""
    result: dict[str, dict[str, dict[str, list[float]]]] = {}
    root = run_dir / "evaluations" / "single"
    if not root.exists():
        return result
    for cond_dir in sorted(root.iterdir()):
        if not cond_dir.is_dir():
            continue
        for f in sorted(cond_dir.glob("*.json")):
            if not _file_matches_filter(f):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                model = data.get("model_name", "unknown")
                if model not in result:
                    result[model] = {}
                if cond_dir.name not in result[model]:
                    result[model][cond_dir.name] = {m: [] for m in METRICS + ["overall"]}
                for entry in data.get("ranking", []):
                    for s in entry.get("scores", []):
                        metric = s.get("metric", "")
                        score = s.get("score")
                        if metric in result[model][cond_dir.name] and score is not None:
                            result[model][cond_dir.name][metric].append(float(score))
                    overall = entry.get("overall_score")
                    if overall is not None:
                        result[model][cond_dir.name]["overall"].append(float(overall))
            except Exception:
                continue
    return result
