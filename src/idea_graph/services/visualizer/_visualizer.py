"""メインビジュアライザ — ディスパッチ + フォールバック"""

from __future__ import annotations

import re
from pathlib import Path

from ._style import HAS_MPL, METRICS, METRIC_SHORT, _safe_mean, _safe_std, logger
from ._loaders import load_single_scores, load_pairwise_wins, load_experiment_meta
from ._renderers import (
    BoxPlotRenderer,
    RadarRenderer,
    LineRenderer,
    HeatmapRenderer,
    BarRenderer,
)
from ._registry import get_visualizer
from ._paper_figures import PaperFigureGenerator
from ._paper_tables import PaperTableGenerator

# 実験専用モジュールをインポートして @register デコレータを発火させる
from . import _exp_1xx  # noqa: F401
from . import _exp_2xx  # noqa: F401
from . import _exp_3xx  # noqa: F401


class ExperimentVisualizer:
    """メインエントリポイント: run_dir から適切なチャートを自動生成する。"""

    def visualize(self, run_dir: str | Path) -> list[Path]:
        if not HAS_MPL:
            logger.warning("matplotlib not installed. Skipping visualization.")
            return []

        run_path = Path(run_dir)
        figures_dir = run_path / "figures"
        meta = load_experiment_meta(run_path)
        exp_id = meta.get("experiment_id", run_path.name.split("_")[0])

        # レジストリから専用可視化関数を検索
        vis_fn = get_visualizer(exp_id)
        if vis_fn is not None:
            logger.info("Using specialized visualizer for %s", exp_id)
            all_paths = vis_fn(run_path, figures_dir, exp_id)
            logger.info("Generated %d figure files in %s", len(all_paths), figures_dir)
            return all_paths

        # フォールバック: 汎用ロジック
        logger.info("No specialized visualizer for %s, using fallback", exp_id)
        return self._fallback(run_path, figures_dir, exp_id)

    def generate_paper_figures(
        self,
        output_dir: str | Path | None = None,
        runs_base: str | Path | None = None,
        formats: list[str] | None = None,
    ) -> dict[str, list[Path]]:
        """全実験データを横断して論文品質の合成図 + LaTeX テーブルを生成する。"""
        if not HAS_MPL:
            logger.warning("matplotlib not installed. Skipping paper figures.")
            return {}

        runs = Path(runs_base) if runs_base else Path("experiments/runs")
        out = Path(output_dir) if output_dir else Path("experiments/paper_figures")

        results: dict[str, list[Path]] = {}

        fig_gen = PaperFigureGenerator(runs)
        results.update(fig_gen.generate_all(out, formats))

        tbl_gen = PaperTableGenerator(runs)
        results.update(tbl_gen.generate_all(out))

        return results

    def _fallback(self, run_path: Path, figures_dir: Path, exp_id: str) -> list[Path]:
        """旧ロジック（汎用チャートセット）。"""
        scores = load_single_scores(run_path)
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

        # パラメータスイープ検出
        param_values = self._detect_parameter_sweep(conditions, scores)
        if param_values:
            x_vals, y_means, y_stds = param_values
            all_paths.extend(LineRenderer.render(
                x_vals, y_means, y_stds, figures_dir, exp_id,
            ))

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
        wins = load_pairwise_wins(run_path)
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
