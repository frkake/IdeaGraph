"""Experiment ID -> visualizer function dispatch registry."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

VisFn = Callable[[Path, Path, str], list[Path]]
"""Visualizer function signature: (run_dir, figures_dir, exp_id) -> [saved_paths]"""

_REGISTRY: dict[str, VisFn] = {}


def register(exp_id: str):
    """Decorator: @register("EXP-101") to register a visualizer function."""
    def decorator(fn: VisFn) -> VisFn:
        _REGISTRY[exp_id] = fn
        return fn
    return decorator


def get_visualizer(exp_id: str) -> VisFn | None:
    """Look up a registered visualizer. Returns None if not found."""
    return _REGISTRY.get(exp_id)
