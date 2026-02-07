"""実験キャッシュシステム (PLAN 10.3)"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1


class ExperimentCache:
    """実験パイプラインの中間結果キャッシュ。

    キャッシュキーは各ステージの入力パラメータから SHA-256 (先頭12文字) で生成する。
    """

    def __init__(self, base_dir: str | Path = "experiments/cache") -> None:
        self._base_dir = Path(base_dir)

    @staticmethod
    def _compute_key(*parts: Any) -> str:
        """パラメータからキャッシュキー (SHA-256 先頭12文字) を生成する。"""
        raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _stage_dir(self, stage: str) -> Path:
        return self._base_dir / stage

    def get(self, stage: str, *key_parts: Any) -> dict | None:
        """キャッシュからデータを取得する。ヒット/ミスをログ出力する。"""
        key = self._compute_key(*key_parts)
        path = self._stage_dir(stage) / f"{key}.json"
        if not path.exists():
            logger.info("[CACHE MISS] %s key=%s", stage, key)
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("[CACHE CORRUPT] %s key=%s", stage, key)
            return None

        if data.get("_cache_version") != _CACHE_VERSION:
            logger.info("[CACHE STALE] %s key=%s (version mismatch)", stage, key)
            return None

        logger.info("[CACHE HIT] %s key=%s", stage, key)
        return data.get("data")

    def put(self, stage: str, data: Any, *key_parts: Any) -> Path:
        """データをキャッシュに書き込む。"""
        key = self._compute_key(*key_parts)
        directory = self._stage_dir(stage)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.json"

        payload = {
            "_cache_version": _CACHE_VERSION,
            "_cache_key": list(key_parts),
            "data": data,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def clear(self, stage: str | None = None) -> int:
        """キャッシュを削除する。stage=None で全削除。"""
        count = 0
        if stage:
            target = self._stage_dir(stage)
            if target.exists():
                for f in target.glob("*.json"):
                    f.unlink()
                    count += 1
        else:
            if self._base_dir.exists():
                for f in self._base_dir.rglob("*.json"):
                    f.unlink()
                    count += 1
        return count

    def status(self) -> dict[str, int]:
        """ステージごとのキャッシュファイル数を返す。"""
        result: dict[str, int] = {}
        if not self._base_dir.exists():
            return result
        for stage_dir in sorted(self._base_dir.iterdir()):
            if stage_dir.is_dir():
                count = len(list(stage_dir.rglob("*.json")))
                if count > 0:
                    result[stage_dir.name] = count
        return result
