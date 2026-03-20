"""Publication-quality style configuration for IEEE/ACM double-column papers.

Design decisions:
- Figure sizes: single-column 3.5in, double-column 7.16in (IEEE standard)
- Tol's bright palette (colorblind-safe, 7 distinct hues)
- Sans-serif fonts at readable sizes (8-10pt at final column width)
- Clean spines (top/right removed), light gridlines
- DPI 300 for PNG, vector SVG
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    import seaborn as sns
    HAS_SNS = True
except ImportError:
    HAS_SNS = False


# ── Publication-quality rcParams ──

def apply_rcparams() -> None:
    """Apply publication-quality matplotlib rcParams once at import time."""
    if not HAS_MPL:
        return
    plt.rcParams.update({
        # Fonts
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "figure.titlesize": 11,
        # Spines & ticks
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.8,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.direction": "out",
        "ytick.direction": "out",
        # Grid
        "axes.grid": False,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.5,
        # Figure
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        # Legend
        "legend.frameon": True,
        "legend.framealpha": 0.9,
        "legend.edgecolor": "#CCCCCC",
        "legend.fancybox": False,
        # Lines
        "lines.linewidth": 1.5,
        "lines.markersize": 5,
    })


apply_rcparams()

# ── Figure dimensions (inches) — IEEE double-column ──

SINGLE_COL = 3.5        # single column width
DOUBLE_COL = 7.16       # double column width
DPI = 300

# Standard figure sizes (width, height)
FIG_SINGLE = (SINGLE_COL, 2.6)         # compact single-column
FIG_SINGLE_TALL = (SINGLE_COL, 3.5)    # tall single-column (radar, violin)
FIG_DOUBLE = (DOUBLE_COL, 3.0)         # double-column wide
FIG_DOUBLE_TALL = (DOUBLE_COL, 4.5)    # tall double (multi-panel)
FIG_DOUBLE_WIDE = (DOUBLE_COL, 2.5)    # extra-wide, short (heatmaps)

# ── Tol's bright palette (colorblind-safe) ──

TOL_BLUE = "#4477AA"
TOL_RED = "#EE6677"
TOL_GREEN = "#228833"
TOL_YELLOW = "#CCBB44"
TOL_CYAN = "#66CCEE"
TOL_PURPLE = "#AA3377"
TOL_GREY = "#BBBBBB"

# Method → color mapping
METHOD_COLORS: dict[str, str] = {
    "ideagraph": TOL_BLUE,
    "ideagraph_default": TOL_BLUE,
    "direct_llm": TOL_RED,
    "direct_llm_baseline": TOL_RED,
    "coi": TOL_GREEN,
    "coi_agent": TOL_GREEN,
    "target_paper": TOL_YELLOW,
}

# Metric → color for per-metric line plots
METRIC_COLORS: dict[str, str] = {
    "novelty": TOL_BLUE,
    "significance": TOL_RED,
    "feasibility": TOL_GREEN,
    "clarity": TOL_YELLOW,
    "effectiveness": TOL_PURPLE,
    "overall": "#222222",
}

# Cycle palette for unnamed conditions
PALETTE = [TOL_BLUE, TOL_RED, TOL_GREEN, TOL_YELLOW, TOL_CYAN, TOL_PURPLE, TOL_GREY]


def color_for(name: str) -> str:
    """Resolve method/condition name to a color."""
    lower = name.lower()
    for key, c in METHOD_COLORS.items():
        if key in lower:
            return c
    return PALETTE[hash(name) % len(PALETTE)]


# ── Labels & names ──

METRICS = ["novelty", "significance", "feasibility", "clarity", "effectiveness"]

METRIC_SHORT: dict[str, str] = {
    "novelty": "Nov", "significance": "Sig", "feasibility": "Fea",
    "clarity": "Cla", "effectiveness": "Eff", "overall": "Overall",
}

METRIC_DISPLAY: dict[str, str] = {
    "novelty": "Novelty", "significance": "Significance",
    "feasibility": "Feasibility", "clarity": "Clarity",
    "effectiveness": "Effectiveness", "overall": "Overall",
}

METHOD_DISPLAY: dict[str, str] = {
    "ideagraph": "IdeaGraph",
    "ideagraph_default": "IdeaGraph",
    "direct_llm": "Baseline",
    "direct_llm_baseline": "Baseline",
    "coi": "Chain-of-Ideas",
    "coi_agent": "Chain-of-Ideas",
    "target_paper": "Target Paper",
}


def display_name(name: str) -> str:
    """Map internal names to paper-ready display names."""
    return METHOD_DISPLAY.get(name.lower(), name)


# ── Condition name cleaner (for ablation conditions) ──

_CONDITION_DISPLAY: dict[str, str] = {
    # EXP-202: format
    "format_mermaid": "Mermaid",
    "format_paths": "Paths",
    # EXP-203: scope
    "scope_path": "Path",
    "scope_k_hop": "k-hop",
    "scope_path_plus_k_hop": "Path+k-hop",
}


def clean_condition(name: str) -> str:
    """Map raw condition names to concise display labels."""
    if name in _CONDITION_DISPLAY:
        return _CONDITION_DISPLAY[name]
    # Fallback: strip common prefixes and clean up
    for prefix in ("hops_", "paths_", "proposals_", "format_", "scope_", "size_"):
        if name.startswith(prefix):
            return name[len(prefix):].replace("_", " ").title()
    return name.replace("_", " ").title()


# ── Experiment caption mapping (publication-ready) ──

EXP_CAPTION: dict[str, str] = {
    # 1xx: Main comparisons
    "EXP-101": "Pairwise ELO comparison across three methods",
    "EXP-102": "Generated ideas vs.\\ original paper (pairwise ELO)",
    "EXP-103": "IdeaGraph independent evaluation scores",
    "EXP-104": "Baseline independent evaluation scores",
    "EXP-105": "Chain-of-Ideas independent evaluation scores",
    "EXP-106": "Target paper independent evaluation scores",
    # 2xx: Ablations
    "EXP-201": "Multi-hop depth ablation",
    "EXP-202": "Graph representation format ablation",
    "EXP-203": "Prompt scope ablation",
    "EXP-204": "Path count ablation",
    "EXP-205": "Graph size effect",
    "EXP-206": "Number of proposals ablation",
    "EXP-207": "Quality--cost efficiency",
    "EXP-208": "Connectivity stability (out-degree stratification)",
    "EXP-209": "Citation stability (in-degree stratification)",
    "EXP-210": "Graph path order reversal ablation",
    # 3xx: Validity
    "EXP-301": "Evaluation mode consistency (independent vs.\\ pairwise)",
    "EXP-302": "Evaluation reproducibility",
    "EXP-303": "Position bias measurement",
    "EXP-304": "Cross-model evaluation consistency",
    "EXP-305": "Correlation with human evaluation",
    "EXP-306": "Evidence traceability",
}


def exp_caption(exp_id: str, suffix: str = "") -> str:
    """Return a publication-ready caption for *exp_id*.

    If *suffix* is given it is appended after a period+space.
    """
    base = EXP_CAPTION.get(exp_id.upper(), exp_id)
    # Capitalise first letter
    base = base[0].upper() + base[1:]
    if suffix:
        return f"{base}. {suffix}"
    return base


# ── Significance annotations ──

_P_THRESHOLDS = [(0.001, "***"), (0.01, "**"), (0.05, "*")]


def p_stars(p: float) -> str:
    """Convert p-value to significance stars."""
    for threshold, label in _P_THRESHOLDS:
        if p < threshold:
            return label
    return "n.s."


# ── Safe statistics ──


def safe_mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def safe_std(vals: list[float]) -> float:
    if len(vals) <= 1:
        return 0.0
    m = safe_mean(vals)
    return (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def safe_sem(vals: list[float]) -> float:
    if len(vals) <= 1:
        return 0.0
    return safe_std(vals) / (len(vals) ** 0.5)


# ── Save helper ──


def overlay_strip(
    ax,
    x_center: float,
    values: list[float],
    color: str,
    width: float = 0.15,
    size: int = 12,
    alpha: float = 0.45,
    seed: int = 42,
    zorder: int = 4,
) -> None:
    """Overlay individual data points as a jittered strip on a bar chart.

    Adds semi-transparent scatter dots around *x_center* so that each
    individual sample is visible alongside aggregate bars.
    """
    if not values or not HAS_MPL:
        return
    rng = np.random.default_rng(seed)
    jitter = rng.uniform(-width / 2, width / 2, size=len(values))
    ax.scatter(
        [x_center + j for j in jitter],
        values,
        s=size,
        color=color,
        alpha=alpha,
        edgecolors="white",
        linewidth=0.3,
        zorder=zorder,
    )


def annotate_n(
    ax,
    x: float,
    y: float,
    n: int,
    fontsize: int = 7,
    va: str = "top",
    color: str = "#666666",
) -> None:
    """Add a sample-size annotation (e.g. 'n=10') at (*x*, *y*)."""
    ax.text(
        x, y, f"n={n}",
        ha="center", va=va, fontsize=fontsize,
        color=color, style="italic",
    )


def annotate_n_header(
    ax,
    n: int,
    fontsize: int = 8,
) -> None:
    """Add 'N = X papers' text in the upper-right corner of *ax*.

    Currently disabled (no-op) to keep figures cleaner.
    """


def save_figure(fig, output_dir: Path, name: str) -> list[Path]:
    """Save figure as PNG (300 DPI) + SVG. Returns list of saved paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ext in ("png", "svg"):
        path = output_dir / f"{name}.{ext}"
        fig.savefig(
            str(path),
            dpi=DPI if ext == "png" else None,
            bbox_inches="tight",
            pad_inches=0.05,
        )
        paths.append(path)
    return paths
