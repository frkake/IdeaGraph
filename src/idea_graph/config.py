"""設定管理モジュール"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    """アプリケーション設定"""

    # Google API
    google_api_key: str = Field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))

    # OpenAI API
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))

    # Neo4j
    neo4j_uri: str = Field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_user: str = Field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    neo4j_password: str = Field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))

    # Paths
    cache_dir: Path = Field(default=Path("cache"))
    papers_cache_dir: Path = Field(default=Path("cache/papers"))
    extractions_cache_dir: Path = Field(default=Path("cache/extractions"))

    # Download settings
    download_delay_seconds: float = Field(default=3.0)
    max_download_retries: int = Field(default=3)

    # arXiv API settings (rate limit / retry)
    # NOTE: arXiv API は 429/503 を返すことがあるため、検索側にもバックオフを入れる
    arxiv_search_max_retries: int = Field(default_factory=lambda: int(os.getenv("ARXIV_SEARCH_MAX_RETRIES", "6")))
    arxiv_search_backoff_base_seconds: float = Field(
        default_factory=lambda: float(os.getenv("ARXIV_SEARCH_BACKOFF_BASE_SECONDS", "2.0"))
    )
    arxiv_search_backoff_max_seconds: float = Field(
        default_factory=lambda: float(os.getenv("ARXIV_SEARCH_BACKOFF_MAX_SECONDS", "60.0"))
    )
    arxiv_search_jitter_seconds: float = Field(
        default_factory=lambda: float(os.getenv("ARXIV_SEARCH_JITTER_SECONDS", "1.0"))
    )

    # Batch settings
    batch_size: int = Field(default=1000)

    # LLM settings
    gemini_model: str = Field(default="gemini-3-flash-preview")
    openai_model: str = Field(default="gpt-5.2-2025-12-11")
    evaluation_model: str = Field(default="gpt-5.2-2025-12-11")

    def ensure_cache_dirs(self) -> None:
        """キャッシュディレクトリを作成"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.papers_cache_dir.mkdir(parents=True, exist_ok=True)
        self.extractions_cache_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
