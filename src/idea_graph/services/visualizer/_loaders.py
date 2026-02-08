"""データ読み込み関数"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._style import METRICS


def load_single_scores(run_dir: Path) -> dict[str, dict[str, list[float]]]:
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


def load_pairwise_wins(run_dir: Path) -> dict[str, int]:
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


def load_pairwise_details(run_dir: Path) -> list[dict[str, Any]]:
    """Pairwise 評価の全ファイルを詳細ロードする。"""
    results: list[dict[str, Any]] = []
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return results
    for f in sorted(root.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except Exception:
            continue
    return results


def load_experiment_meta(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {}


def load_metadata(run_dir: Path) -> dict[str, Any]:
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def load_aggregate(run_dir: Path) -> dict[str, Any]:
    """summary/aggregate.json をロードする。"""
    agg_path = run_dir / "summary" / "aggregate.json"
    if agg_path.exists():
        return json.loads(agg_path.read_text(encoding="utf-8"))
    return {}


def load_single_scores_per_paper(
    run_dir: Path,
) -> dict[str, dict[str, dict[str, float]]]:
    """条件別 → 論文ID別 → 指標別平均スコアを返す。"""
    result: dict[str, dict[str, dict[str, float]]] = {}
    single_root = run_dir / "evaluations" / "single"
    if not single_root.exists():
        return result
    for condition_dir in sorted(single_root.iterdir()):
        if not condition_dir.is_dir():
            continue
        papers: dict[str, dict[str, float]] = {}
        for f in sorted(condition_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                paper_id = f.stem
                # _r0, _r1 等のsuffixを除去
                paper_id = re.sub(r"_r\d+$", "", paper_id)
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
        result[condition_dir.name] = papers
    return result


def load_repeat_scores(run_dir: Path) -> dict[str, dict[str, list[list[float]]]]:
    """repeat評価 (*_r*.json) から 条件 → 指標 → [repeat0のスコア列, repeat1のスコア列, ...] を返す。"""
    result: dict[str, dict[str, list[list[float]]]] = {}
    single_root = run_dir / "evaluations" / "single"
    if not single_root.exists():
        return result
    for condition_dir in sorted(single_root.iterdir()):
        if not condition_dir.is_dir():
            continue
        # repeatインデックスごとにスコアを集約
        repeat_data: dict[int, dict[str, list[float]]] = {}
        for f in sorted(condition_dir.glob("*.json")):
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
        for r_idx in sorted(repeat_data.keys()):
            for metric_name, vals in repeat_data[r_idx].items():
                metrics_by_repeat.setdefault(metric_name, []).append(vals)
        result[condition_dir.name] = metrics_by_repeat
    return result


def load_pairwise_swap_data(run_dir: Path) -> dict[str, dict[str, str]]:
    """ABとBAのペアワイズ結果をロードし、ポジションバイアス分析用データを返す。
    Returns: {paper_id: {"ab_winner": source, "ba_winner": source}} （swap_testフィールドから）
    """
    result: dict[str, dict[str, str]] = {}
    root = run_dir / "evaluations" / "pairwise"
    if not root.exists():
        return result
    for f in sorted(root.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            swap = data.get("swap_test", {})
            if swap:
                paper_id = f.stem
                result[paper_id] = {
                    "ab_winner": str(swap.get("ab_winner", "")),
                    "ba_winner": str(swap.get("ba_winner", "")),
                    "consistent": swap.get("consistent", True),
                }
        except Exception:
            continue
    return result


def load_multi_model_scores(
    run_dir: Path,
) -> dict[str, dict[str, dict[str, list[float]]]]:
    """モデル別 → 条件別 → 指標別スコアを返す（EXP-304用）。
    ファイル名パターン: paper_id_modelname.json
    """
    result: dict[str, dict[str, dict[str, list[float]]]] = {}
    single_root = run_dir / "evaluations" / "single"
    if not single_root.exists():
        return result
    for condition_dir in sorted(single_root.iterdir()):
        if not condition_dir.is_dir():
            continue
        for f in sorted(condition_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                model_name = data.get("model_name", "unknown")
                if model_name not in result:
                    result[model_name] = {}
                if condition_dir.name not in result[model_name]:
                    result[model_name][condition_dir.name] = {m: [] for m in METRICS + ["overall"]}
                for entry in data.get("ranking", []):
                    for s in entry.get("scores", []):
                        metric = s.get("metric", "")
                        score = s.get("score")
                        if metric in result[model_name][condition_dir.name] and score is not None:
                            result[model_name][condition_dir.name][metric].append(float(score))
                    overall = entry.get("overall_score")
                    if overall is not None:
                        result[model_name][condition_dir.name]["overall"].append(float(overall))
            except Exception:
                continue
    return result
