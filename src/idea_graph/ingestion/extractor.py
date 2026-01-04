"""Gemini API による論文情報抽出モジュール"""

import base64
import io
import json
import logging
import random
import tarfile
import time
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from idea_graph.config import settings
from idea_graph.ingestion.downloader import FileType

logger = logging.getLogger(__name__)


class Entity(BaseModel):
    """抽出されたエンティティ"""

    type: str = Field(description="エンティティのタイプ (Method, Dataset, Benchmark, Challenge, etc.)")
    name: str = Field(description="エンティティの名前")
    description: str | None = Field(default=None, description="エンティティの説明")


class InternalRelation(BaseModel):
    """エンティティ間の関係"""

    source: str = Field(description="関係元のエンティティ名")
    target: str = Field(description="関係先のエンティティ名")
    relation_type: str = Field(description="関係のタイプ (EXTENDS, ALIAS_OF, COMPONENT_OF, etc.)")


class CitedPaper(BaseModel):
    """引用論文とその重要度"""

    title: str = Field(description="引用論文のタイトル")
    importance_score: int = Field(
        ge=1, le=5,
        description="この引用の重要度 (1=低, 5=高). 5: 本研究の基盤・直接拡張, 4: 主要手法・比較対象, 3: 関連手法, 2: 背景・一般参照, 1: 付随的言及"
    )
    citation_type: str = Field(
        description="引用のタイプ: EXTENDS(拡張), COMPARES(比較), USES(使用), BACKGROUND(背景), MENTIONS(言及)"
    )
    context: str | None = Field(default=None, description="引用のコンテキスト（なぜ重要か）")


class ExtractedInfo(BaseModel):
    """抽出された論文情報"""

    paper_id: str = Field(default="", description="論文ID")
    paper_summary: str = Field(description="論文の要約 (1-3文)")
    claims: list[str] = Field(description="論文の主張・貢献のリスト")
    entities: list[Entity] = Field(description="抽出されたエンティティのリスト")
    relations: list[InternalRelation] = Field(default_factory=list, description="エンティティ間の関係のリスト")
    cited_papers: list[CitedPaper] = Field(default_factory=list, description="重要な引用論文のリスト（重要度付き）")
    raw_extended: dict | None = Field(default=None, description="拡張テンプレートの結果")


EXTRACTION_PROMPT = """You are an expert AI research paper analyzer. Extract structured information from the following academic paper.

Please extract:
1. **paper_summary**: A concise summary of the paper (1-3 sentences) focusing on the main contribution.
2. **claims**: List of main claims/contributions made by the paper (short sentences).
3. **entities**: Key entities mentioned in the paper with their types:
   - Method: Algorithms, models, architectures (e.g., "Transformer", "BERT", "Adam optimizer")
   - Dataset: Datasets used or created (e.g., "ImageNet", "COCO")
   - Benchmark: Evaluation benchmarks (e.g., "GLUE", "SQuAD")
   - Challenge: Problems or challenges addressed (e.g., "vanishing gradient", "long-range dependencies")
   - Task: ML/AI tasks (e.g., "image classification", "machine translation")
   - Metric: Evaluation metrics (e.g., "BLEU score", "F1 score")
4. **relations**: Relationships between entities (optional):
   - EXTENDS: One method extends/improves another
   - ALIAS_OF: Alternative names for the same concept
   - COMPONENT_OF: One entity is a component of another
   - INSPIRED_BY: One method is inspired by another
5. **cited_papers**: Important cited papers with their relevance to this work (top 10-15 most important):
   - title: The exact title of the cited paper
   - importance_score (1-5): How important this citation is for understanding this paper
     - 5: Foundation of this work / directly extended by this paper
     - 4: Key method used or main comparison baseline
     - 3: Related method / relevant prior work
     - 2: Background reference / general context
     - 1: Peripheral mention
   - citation_type: EXTENDS (builds upon), COMPARES (compared against), USES (uses method/data from), BACKGROUND (general background), MENTIONS (peripheral)
   - context: Brief explanation of why this paper is cited (1 sentence)

Focus on extracting information that would be useful for building a knowledge graph of AI research.
Prioritize papers that are directly extended, compared against, or whose methods are used in this work.
"""


class ExtractorService:
    """論文情報抽出サービス"""

    def __init__(
        self,
        model_name: str | None = None,
        cache_dir: Path | None = None,
        max_retries: int = 3,
    ):
        """初期化

        Args:
            model_name: Gemini モデル名
            cache_dir: キャッシュディレクトリ
            max_retries: 最大リトライ回数
        """
        self.model_name = model_name or settings.gemini_model
        self.cache_dir = cache_dir or settings.extractions_cache_dir
        self.max_retries = max_retries

        # キャッシュディレクトリを作成
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # LLM の初期化
        self._llm = None

    @property
    def llm(self) -> ChatGoogleGenerativeAI:
        """LLM インスタンスを取得（遅延初期化）"""
        if self._llm is None:
            self._llm = ChatGoogleGenerativeAI(
                model=self.model_name,
                google_api_key=settings.google_api_key,
            )
        return self._llm

    def _get_cache_path(self, paper_id: str) -> Path:
        """キャッシュファイルのパスを取得"""
        return self.cache_dir / f"{paper_id}.json"

    def _check_cache(self, paper_id: str) -> ExtractedInfo | None:
        """キャッシュを確認

        Returns:
            キャッシュがあれば ExtractedInfo、なければ None
        """
        cache_path = self._get_cache_path(paper_id)
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text())
                return ExtractedInfo(**data)
            except Exception as e:
                logger.warning(f"Failed to load cache for {paper_id}: {e}")
        return None

    def _save_cache(self, info: ExtractedInfo) -> None:
        """キャッシュに保存"""
        cache_path = self._get_cache_path(info.paper_id)
        try:
            cache_path.write_text(info.model_dump_json(indent=2))
        except Exception as e:
            logger.warning(f"Failed to save cache for {info.paper_id}: {e}")

    def _extract_latex_from_tar(self, file_path: Path) -> str | None:
        """tar.gz から LaTeX ファイルを抽出してテキストを返す"""
        try:
            content = file_path.read_bytes()
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                tex_files = []
                for member in tar.getmembers():
                    if member.isfile() and member.name.endswith(".tex"):
                        tex_files.append(member)

                if not tex_files:
                    logger.warning(f"No .tex files found in {file_path}")
                    return None

                # main.tex または最大のファイルを優先
                main_file = None
                for tf in tex_files:
                    name_lower = tf.name.lower()
                    if "main" in name_lower or "paper" in name_lower:
                        main_file = tf
                        break

                if main_file is None:
                    # 最大のファイルを選択
                    main_file = max(tex_files, key=lambda x: x.size)

                # ファイルを読み込み
                f = tar.extractfile(main_file)
                if f is None:
                    return None

                tex_content = f.read().decode("utf-8", errors="ignore")
                logger.info(f"Extracted {main_file.name} ({len(tex_content)} chars)")
                return tex_content

        except Exception as e:
            logger.error(f"Failed to extract LaTeX from {file_path}: {e}")
            return None

    def _read_file_content(self, file_path: Path, file_type: FileType) -> list:
        """ファイル内容を読み込んでメッセージ形式に変換"""
        content = file_path.read_bytes()

        if file_type == FileType.PDF:
            # PDF はマルチモーダルで送信
            return [
                {"type": "text", "text": EXTRACTION_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:application/pdf;base64,{base64.b64encode(content).decode()}"
                    },
                },
            ]
        else:
            # LaTeX: tar.gz を展開して .tex ファイルを読み込む
            if file_path.suffix == ".gz" or str(file_path).endswith(".tar.gz"):
                text_content = self._extract_latex_from_tar(file_path)
                if text_content is None:
                    # フォールバック: そのまま読み込み
                    text_content = content.decode("utf-8", errors="ignore")[:50000]
            else:
                # 通常のテキストファイル
                try:
                    text_content = content.decode("utf-8", errors="ignore")
                except Exception:
                    text_content = str(content[:10000])

            # テキストを制限（トークン制限対策）
            max_chars = 10000000
            if len(text_content) > max_chars:
                text_content = text_content[:max_chars]
                logger.info(f"Truncated LaTeX content to {max_chars} chars")

            return [
                {"type": "text", "text": f"{EXTRACTION_PROMPT}\n\n---\n\n{text_content}"},
            ]

    def extract(
        self,
        paper_id: str,
        file_path: Path,
        file_type: FileType,
    ) -> ExtractedInfo | None:
        """論文から構造化情報を抽出

        Args:
            paper_id: 論文ID
            file_path: ファイルパス
            file_type: ファイルタイプ

        Returns:
            抽出された情報、失敗時は None
        """
        # キャッシュを確認
        cached = self._check_cache(paper_id)
        if cached:
            logger.info(f"Using cached extraction for {paper_id}")
            return cached

        # ファイル内容を読み込み
        try:
            message_content = self._read_file_content(file_path, file_type)
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return None

        # 構造化出力を設定
        structured_llm = self.llm.with_structured_output(ExtractedInfo)

        # リトライ付きで抽出
        last_error = None
        for attempt in range(self.max_retries):
            try:
                message = HumanMessage(content=message_content)
                result = structured_llm.invoke([message])

                # paper_id を設定
                result.paper_id = paper_id

                # キャッシュに保存
                self._save_cache(result)

                return result

            except Exception as e:
                last_error = e
                logger.warning(f"Extraction attempt {attempt + 1} failed for {paper_id}: {e}")

                if attempt < self.max_retries - 1:
                    # 指数バックオフ + ジッター
                    wait_time = (2**attempt) + random.uniform(0, 1)
                    time.sleep(wait_time)

        logger.error(f"Extraction failed for {paper_id} after {self.max_retries} attempts: {last_error}")
        return None
