"""Chain-of-Ideas実行サービス

Chain-of-Ideas をサブプロセスとして実行し、
進捗をストリーミングで取得するサービス。
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from pydantic import BaseModel, Field

from idea_graph.coi.config import COI_AGENT_DIR, coi_settings
from idea_graph.config import settings

logger = logging.getLogger(__name__)


def _normalize_related_experiments(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        parts = [line.strip() for line in value.splitlines() if line.strip()]
        return parts or [value]
    return [str(value)]


def _normalize_entities(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item is not None)
    return str(value)


class CoIArgs(BaseModel):
    """CoI実行時の引数"""

    topic: str = Field(description="研究トピック")
    max_chain_length: int = Field(description="アイデアチェーン最大長")
    min_chain_length: int = Field(description="アイデアチェーン最小長")
    max_chain_numbers: int = Field(description="処理するチェーン最大数")
    improve_cnt: int = Field(description="実験改善反復回数")
    publication_date: str | None = Field(default=None, description="検索対象の出版日範囲（Semantic Scholar形式、例: ':2022-12-01'）")


class CoIResult(BaseModel):
    """Chain-of-Ideasの出力モデル"""

    idea: str = Field(description="生成されたアイデア（Title, Motivation, Methodology含む長文）")
    idea_chain: str = Field(default="", description="複数論文のアイデアチェーン")
    experiment: str = Field(default="", description="実験設計（文字列）")
    related_experiments: list[str] = Field(default_factory=list, description="関連実験のステップ")
    entities: str = Field(default="", description="エンティティ一覧（文字列）")
    trend: str = Field(default="", description="研究トレンド")
    future: str = Field(default="", description="将来研究方向")
    year: list[int] = Field(default_factory=list, description="関連する年度リスト")
    ideas: list[str] = Field(default_factory=list, description="生成されたアイデアリスト")
    human: str = Field(default="", description="人間可読な説明")
    prompt: str = Field(default="", description="最終的に使用したCoIプロンプト")
    args: CoIArgs | None = Field(default=None, description="CoI実行時の引数")


class CoIProgress(BaseModel):
    """CoI実行進捗"""

    status: str = Field(description="running | completed | error")
    progress: str = Field(default="", description="進捗メッセージ")
    result: CoIResult | None = Field(default=None, description="完了時の結果")
    error: str | None = Field(default=None, description="エラーメッセージ")


class CoIRunner:
    """Chain-of-Ideas実行サービス"""

    def __init__(
        self,
        max_chain_length: int = 5,
        min_chain_length: int = 3,
        max_chain_numbers: int = 1,
        improve_cnt: int = 1,
        main_model: str | None = None,
        cheap_model: str | None = None,
        publication_date: str | None = None,
    ) -> None:
        """初期化

        Args:
            max_chain_length: アイデアチェーンの最大長
            min_chain_length: アイデアチェーンの最小長
            max_chain_numbers: 処理するチェーンの最大数
            improve_cnt: 実験改善の反復回数
            main_model: CoIメインLLMモデル名（Noneならcoi_settingsのデフォルト）
            cheap_model: CoI安価LLMモデル名（Noneならcoi_settingsのデフォルト）
            publication_date: 検索対象の出版日範囲（Semantic Scholar形式、例: ':2022-12-01'）
        """
        self.max_chain_length = max_chain_length
        self.min_chain_length = min_chain_length
        self.max_chain_numbers = max_chain_numbers
        self.improve_cnt = improve_cnt
        self.main_model = main_model
        self.cheap_model = cheap_model
        self.publication_date = publication_date

    def _setup_environment(self) -> dict[str, str]:
        """Chain-of-Ideas用の環境変数を準備

        Returns:
            設定された環境変数の辞書
        """
        env = os.environ.copy()

        # Chain-of-Ideasが期待する環境変数を設定
        env["SEMENTIC_SEARCH_API_KEY"] = coi_settings.semantic_search_api_key
        env["is_azure"] = "true" if coi_settings.is_azure else ""
        env["OPENAI_API_KEY"] = coi_settings.openai_api_key
        if coi_settings.openai_base_url:
            env["OPENAI_BASE_URL"] = coi_settings.openai_base_url
        elif "OPENAI_BASE_URL" in env:
            del env["OPENAI_BASE_URL"]
        env["MAIN_LLM_MODEL"] = self.main_model or coi_settings.main_llm_model
        env["CHEAP_LLM_MODEL"] = self.cheap_model or coi_settings.cheap_llm_model

        # Azure設定
        if coi_settings.is_azure:
            env["AZURE_OPENAI_ENDPOINT"] = coi_settings.azure_endpoint
            env["AZURE_OPENAI_KEY"] = coi_settings.azure_key
            env["AZURE_OPENAI_API_VERSION"] = coi_settings.azure_api_version

        # Embedding設定
        if coi_settings.embedding_api_key:
            env["EMBEDDING_API_KEY"] = coi_settings.embedding_api_key
        if coi_settings.embedding_api_endpoint:
            env["EMBEDDING_API_ENDPOINT"] = coi_settings.embedding_api_endpoint
        if coi_settings.embedding_model:
            env["EMBEDDING_MODEL"] = coi_settings.embedding_model

        return env

    async def run(
        self,
        topic: str,
        save_dir: str | None = None,
    ) -> CoIResult:
        """Chain-of-Ideasを実行してアイデアを生成（同期版）

        Args:
            topic: 研究トピック
            save_dir: 保存先ディレクトリ

        Returns:
            Chain-of-Ideasの実行結果
        """
        result: CoIResult | None = None
        error_msg: str | None = None

        async for progress in self.run_streaming(topic, save_dir):
            if progress.status == "completed" and progress.result:
                result = progress.result
            elif progress.status == "error":
                error_msg = progress.error

        if result:
            return result
        raise RuntimeError(error_msg or "Chain-of-Ideas execution failed without result")

    async def run_streaming(
        self,
        topic: str,
        save_dir: str | None = None,
    ) -> AsyncIterator[CoIProgress]:
        """Chain-of-Ideasを実行して進捗をストリーミング

        Args:
            topic: 研究トピック
            save_dir: 保存先ディレクトリ

        Yields:
            CoIProgress: 進捗情報
        """
        # 保存先ディレクトリの設定
        if save_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_dir = str((settings.cache_dir / "coi" / f"run_{timestamp}").resolve())

        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        yield CoIProgress(status="running", progress="Chain-of-Ideasを起動中...")

        # 環境変数を準備
        env = self._setup_environment()

        # コマンドを構築（uv run --group coi 経由で実行）
        import shutil

        uv_path = shutil.which("uv")
        if uv_path:
            cmd = [
                uv_path,
                "run",
                "--group",
                "coi",
                "python",
                "-m",
                "idea_graph.coi.cli",
            ]
        else:
            cmd = [
                sys.executable,
                "-m",
                "idea_graph.coi.cli",
            ]
        cmd += [
            "--topic",
            topic,
            "--save-file",
            str(save_path),
            "--max-chain-length",
            str(self.max_chain_length),
            "--min-chain-length",
            str(self.min_chain_length),
            "--max-chain-numbers",
            str(self.max_chain_numbers),
            "--improve-cnt",
            str(self.improve_cnt),
        ]
        if self.publication_date is not None:
            cmd += ["--publication-date", self.publication_date]

        logger.info(f"Starting Chain-of-Ideas with topic: {topic}")
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            # サブプロセスを開始
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(COI_AGENT_DIR),
            )

            # 出力をストリーミング
            if process.stdout:
                async for line in process.stdout:
                    decoded_line = line.decode("utf-8", errors="replace").strip()
                    if decoded_line:
                        logger.debug(f"CoI output: {decoded_line}")
                        yield CoIProgress(status="running", progress=decoded_line)

            # プロセスの完了を待つ
            return_code = await process.wait()

            if return_code != 0:
                error_msg = f"Chain-of-Ideas exited with code {return_code}"
                logger.error(error_msg)
                yield CoIProgress(status="error", error=error_msg)
                return

            # 結果ファイルを読み込み
            result_path = save_path / "result.json"
            if not result_path.exists():
                error_msg = f"Result file not found: {result_path}"
                logger.error(error_msg)
                yield CoIProgress(status="error", error=error_msg)
                return

            with open(result_path, encoding="utf-8") as f:
                result_data = json.load(f)

            # CoIResultに変換（引数情報を含める）
            coi_args = CoIArgs(
                topic=topic,
                max_chain_length=self.max_chain_length,
                min_chain_length=self.min_chain_length,
                max_chain_numbers=self.max_chain_numbers,
                improve_cnt=self.improve_cnt,
                publication_date=self.publication_date,
            )
            result = CoIResult(
                idea=result_data.get("idea", ""),
                idea_chain=result_data.get("idea_chain", ""),
                experiment=result_data.get("experiment", ""),
                related_experiments=_normalize_related_experiments(
                    result_data.get("related_experiments")
                ),
                entities=_normalize_entities(result_data.get("entities")),
                trend=result_data.get("trend", ""),
                future=result_data.get("future", ""),
                year=result_data.get("year", []),
                ideas=result_data.get("ideas", []),
                human=result_data.get("human", ""),
                prompt=result_data.get("prompt", ""),
                args=coi_args,
            )

            logger.info("Chain-of-Ideas completed successfully")
            yield CoIProgress(status="completed", progress="完了", result=result)

        except FileNotFoundError as e:
            error_msg = f"Chain-of-Ideas executable not found: {e}"
            logger.error(error_msg)
            yield CoIProgress(status="error", error=error_msg)
        except asyncio.TimeoutError:
            error_msg = "Chain-of-Ideas execution timed out"
            logger.error(error_msg)
            yield CoIProgress(status="error", error=error_msg)
        except Exception as e:
            error_msg = f"Chain-of-Ideas execution failed: {e}"
            logger.exception(error_msg)
            yield CoIProgress(status="error", error=error_msg)

    @staticmethod
    def load_result_from_file(result_path: str | Path) -> CoIResult:
        """結果ファイルからCoIResultを読み込み

        Args:
            result_path: result.jsonのパス

        Returns:
            CoIResult
        """
        path = Path(result_path)
        if not path.exists():
            raise FileNotFoundError(f"Result file not found: {path}")

        with open(path, encoding="utf-8") as f:
            result_data = json.load(f)

        return CoIResult(
            idea=result_data.get("idea", ""),
            idea_chain=result_data.get("idea_chain", ""),
            experiment=result_data.get("experiment", ""),
            related_experiments=_normalize_related_experiments(
                result_data.get("related_experiments")
            ),
            entities=_normalize_entities(result_data.get("entities")),
            trend=result_data.get("trend", ""),
            future=result_data.get("future", ""),
            year=result_data.get("year", []),
            ideas=result_data.get("ideas", []),
            human=result_data.get("human", ""),
            prompt=result_data.get("prompt", ""),
        )
