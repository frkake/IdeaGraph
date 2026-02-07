"""並列処理ユーティリティ"""

from idea_graph.config import settings
from idea_graph.ingestion.rate_limiter import ServiceRateLimiter


class RateLimiters:
    """外部サービスごとのレートリミッターを一括管理するファクトリ"""

    def __init__(self) -> None:
        self.arxiv = ServiceRateLimiter(
            "arXiv",
            max_concurrent=1,
            min_interval_seconds=settings.download_delay_seconds,
        )
        self.semantic_scholar = ServiceRateLimiter(
            "S2",
            max_concurrent=1,
            min_interval_seconds=settings.semantic_scholar_request_delay_seconds,
        )
        self.gemini = ServiceRateLimiter(
            "Gemini",
            max_concurrent=settings.gemini_max_concurrent,
        )
