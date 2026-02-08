"""実験ID → 可視化関数のディスパッチレジストリ"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

VisFn = Callable[[Path, Path, str], list[Path]]
"""可視化関数の型: (run_dir, figures_dir, exp_id) -> [saved_paths]"""

_REGISTRY: dict[str, VisFn] = {}


def register(exp_id: str):
    """デコレータ: @register("EXP-101") で可視化関数を登録する。"""
    def decorator(fn: VisFn) -> VisFn:
        _REGISTRY[exp_id] = fn
        return fn
    return decorator


def get_visualizer(exp_id: str) -> VisFn | None:
    """登録済みの可視化関数を返す。なければ None。"""
    return _REGISTRY.get(exp_id)
