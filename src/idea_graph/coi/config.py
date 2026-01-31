"""CoI-Agent 設定管理モジュール"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# CoI-Agentディレクトリのパス
COI_AGENT_DIR = Path(__file__).parent.parent.parent.parent / "3rdparty" / "CoI-Agent"


class CoISettings:
    """CoI-Agent設定クラス

    既存の.envファイルから設定を読み込み、CoI-Agent形式の環境変数に変換する。
    """

    def __init__(self) -> None:
        # 既存のOPENAI_API_KEYを再利用
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url: str = os.getenv("COI_OPENAI_BASE_URL", "")

        # CoI-Agent固有設定（.envから読み込み、なければデフォルト）
        self.semantic_search_api_key: str = os.getenv("COI_SEMANTIC_SEARCH_API_KEY", "")
        self.is_azure: bool = os.getenv("COI_IS_AZURE", "false").lower() == "true"
        self.main_llm_model: str = os.getenv("COI_MAIN_LLM_MODEL", "gpt-4o")
        self.cheap_llm_model: str = os.getenv("COI_CHEAP_LLM_MODEL", "gpt-4o-mini")

        # Azure設定（オプション）
        self.azure_endpoint: str = os.getenv("COI_AZURE_OPENAI_ENDPOINT", "")
        self.azure_key: str = os.getenv("COI_AZURE_OPENAI_KEY", "")
        self.azure_api_version: str = os.getenv("COI_AZURE_OPENAI_API_VERSION", "")

        # Embedding設定（オプション）
        self.embedding_api_key: str = os.getenv("COI_EMBEDDING_API_KEY", "")
        self.embedding_api_endpoint: str = os.getenv("COI_EMBEDDING_API_ENDPOINT", "")
        self.embedding_model: str = os.getenv("COI_EMBEDDING_MODEL", "")


coi_settings = CoISettings()

