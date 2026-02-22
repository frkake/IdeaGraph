"""共通スタイル・ヘルパー関数"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # サンセリフフォントで CoI の I と l を区別しやすくする
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica", "sans-serif"],
    })

    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import seaborn as sns

    HAS_SNS = True
except ImportError:
    HAS_SNS = False


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
        palette = ["#2563EB", "#DC2626", "#16A34A", "#F59E0B", "#8B5CF6",
                   "#EC4899", "#14B8A6", "#F97316"]
        return palette[hash(name) % len(palette)]


STYLE = ChartStyle()
METRICS = ["novelty", "significance", "feasibility", "clarity", "effectiveness"]
METRIC_SHORT = {
    "novelty": "Nov", "significance": "Sig", "feasibility": "Fea",
    "clarity": "Cla", "effectiveness": "Eff",
}

_P_ANNOTATIONS = {0.001: "***", 0.01: "**", 0.05: "*"}


def _p_label(p: float) -> str:
    for threshold, label in _P_ANNOTATIONS.items():
        if p < threshold:
            return label
    return "ns"


def _safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _safe_std(vals: list[float]) -> float:
    if len(vals) <= 1:
        return 0.0
    m = _safe_mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def _safe_sem(vals: list[float]) -> float:
    if len(vals) <= 1:
        return 0.0
    return _safe_std(vals) / (len(vals) ** 0.5)


def _save_figure(fig, output_dir: Path, name: str) -> list[Path]:
    """PNG + SVG で保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ["png", "svg"]:
        path = output_dir / f"{name}.{ext}"
        fig.savefig(str(path), dpi=STYLE.DPI if ext == "png" else None, bbox_inches="tight")
        paths.append(path)
    return paths
