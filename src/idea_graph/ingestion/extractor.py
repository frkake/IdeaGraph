"""Gemini API による論文情報抽出モジュール"""

import base64
import io
import json
import logging
import random
import re
import tarfile
import time
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from idea_graph.config import settings
from idea_graph.ingestion.downloader import FileType

logger = logging.getLogger(__name__)

EXTRACTION_CACHE_VERSION = 2


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
    reference_number: int | None = Field(
        default=None,
        description=(
            "参考文献リスト上の番号（[n]）。LaTeX から抽出できる場合のみ。"
            "指定されている場合は、この番号に基づいてタイトルが補完される。"
        ),
    )
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
   - Method: Named algorithms, models, architectures with explicit names (e.g., "Transformer", "BERT", "Adam optimizer")
   - Approach: Research approaches or techniques WITHOUT a specific name (e.g., "attention mechanism", "contrastive learning", "multi-task learning")
   - Framework: Conceptual or analytical frameworks (e.g., "reinforcement learning from human feedback", "chain-of-thought prompting")
   - Finding: Key empirical findings or insights (e.g., "scaling laws", "in-context learning emerges at scale")
   - Dataset: Datasets used or created (e.g., "ImageNet", "COCO")
   - Benchmark: Evaluation benchmarks (e.g., "GLUE", "SQuAD")
   - Challenge: Problems or challenges addressed (e.g., "vanishing gradient", "long-range dependencies")
   - Task: ML/AI tasks (e.g., "image classification", "machine translation")
   - Metric: Evaluation metrics (e.g., "BLEU score", "F1 score")

   Note: For survey/analysis papers without novel methods, focus on extracting Approach, Framework, Finding, Challenge, and Task entities instead of Method.
4. **cited_papers**: Important cited papers with their relevance to this work (top 10-15 most important):
   - reference_number: If a numbered reference list is provided (e.g., [12]), output the reference number for each cited paper.
     - Prefer returning reference_number over guessing a title.
     - If reference_number is available, set title to an empty string (it will be filled deterministically from the reference entry).
   - title: The exact title of the cited paper (only if reference_number is not available)
   - citation_type: The type of citation relationship (see below)
   - importance_score (1-5): MUST be consistent with citation_type as follows:
     - EXTENDS: Score 5 (this paper directly builds upon/extends the cited work)
     - COMPARES: Score 4-5 (main comparison baseline or competing method)
     - USES: Score 3-4 (uses method, dataset, or technique from the cited work)
     - BACKGROUND: Score 2-3 (provides theoretical foundation or general context)
     - MENTIONS: Score 1-2 (peripheral or brief mention)
   - context: Brief explanation of WHY this paper is cited and HOW it relates to this work (1-2 sentences)

Citation type definitions:
- EXTENDS: This paper directly extends, improves, or builds upon the cited work's method/approach
- COMPARES: The cited work is a baseline or competing method that this paper compares against
- USES: This paper uses a method, dataset, benchmark, or technique from the cited work
- BACKGROUND: The cited work provides theoretical background, motivation, or general context
- MENTIONS: Brief or peripheral mention without deep engagement

Focus on extracting information that would be useful for building a knowledge graph of AI research.
Prioritize papers that are directly extended, compared against, or whose methods are used in this work.
"""


def _strip_latex_commands(text: str) -> str:
    """LaTeX 記法を雑に除去（参考文献のタイトル抽出用途の軽量版）"""
    # コメント除去
    text = re.sub(r"(?m)^%.*$", "", text)
    # コマンド \command{...} / \command[...] {..} を中身だけ残す方向で軽く削る
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    # コマンド \command を削除
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", text)
    # 波括弧・チルダ等の置換
    text = text.replace("{", " ").replace("}", " ").replace("~", " ")
    # 連続空白圧縮
    text = " ".join(text.split())
    return text.strip()


def _extract_numbered_references_from_latex(text: str, max_entries: int = 200) -> dict[int, str]:
    """LaTeX から numbered reference list を作る（thebibliography / bbl の \\bibitem を想定）"""
    refs: dict[int, str] = {}

    # thebibliography ブロック優先（無ければ全体から探す）
    m = re.search(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", text, flags=re.S)
    bib_block = m.group(0) if m else text

    # \\bibitem{key} ... を粗く分割
    parts = re.split(r"\\bibitem(?:\[[^\]]*\])?\{[^}]*\}", bib_block)
    if len(parts) <= 1:
        return refs

    # parts[0] は先頭（\\begin...等）なのでスキップ
    idx = 0
    for p in parts[1:]:
        if idx >= max_entries:
            break
        entry = p.strip()
        if not entry:
            continue
        idx += 1
        refs[idx] = _strip_latex_commands(entry)

    return refs


def _extract_title_from_reference_entry(entry_text: str) -> str | None:
    """参考文献エントリ（プレーンテキスト）からタイトルらしき部分を抽出する"""
    if not entry_text:
        return None

    t = " ".join(entry_text.split())

    # 1) 引用符で囲まれたタイトル（最優先）
    for pattern in [
        r"“([^”]{8,})”",
        r"\"([^\"]{8,})\"",
        r"``([^`]{8,})''",
    ]:
        m = re.search(pattern, t)
        if m:
            cand = m.group(1).strip()
            return cand.rstrip(" .")

    # 2) 典型パターン: "... . Title . arXiv/Proc/Journal/..." を拾う
    #    例: "B. Author. Another Great Title. arXiv:1234.5678."
    venue_markers = (
        r"arxiv|arxiveprint|preprint|in\s|proceedings|proc\.|journal|transactions|"
        r"conference|workshop|neurips|nips|icml|iclr|acl|emnlp|naacl|cvpr|eccv|iccv|aaai|ijcai|www|kdd|sigir"
    )
    m = re.search(rf"\.\s+([^\.]{{8,}}?)\.\s+(?:{venue_markers})", t, flags=re.I)
    if m:
        cand = m.group(1).strip().strip(" ,;:")
        # 変に短い/著者名っぽいものを除外
        if len(cand.split()) >= 2 and not re.fullmatch(r"[A-Z]\w*", cand):
            return cand.rstrip(" .")

    # 3) 年で区切れるパターン: "... . Title . 2021 ..."
    m = re.search(r"\.\s+([^\.]{8,}?)\.\s+(?:19|20)\d{2}\b", t)
    if m:
        cand = m.group(1).strip().strip(" ,;:")
        if len(cand.split()) >= 2:
            return cand.rstrip(" .")

    return None


def _looks_like_full_citation(text: str) -> bool:
    """title に“タイトル”ではなく“参考文献全文”が入っていそうかを雑に判定"""
    if not text:
        return False
    t = " ".join(text.split())
    if len(t) >= 140:
        return True
    low = t.lower()
    if "arxiv" in low or "proceedings" in low or "journal" in low or "doi" in low:
        return True
    # 年 + 句読点多め（著者列っぽさ）
    if re.search(r"\b(19|20)\d{2}\b", t) and (t.count(",") >= 2 or t.count(".") >= 4):
        return True
    return False


class _FreeformTitleItem(BaseModel):
    index: int = Field(description="Input index")
    title: str = Field(description="Extracted paper title only (no authors/venue/year)")


class _FreeformTitleExtraction(BaseModel):
    results: list[_FreeformTitleItem] = Field(default_factory=list)


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
                temperature=0.0,
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
                cache_version = data.get("_cache_version")
                if cache_version != EXTRACTION_CACHE_VERSION:
                    logger.info(
                        f"Ignoring cached extraction for {paper_id} due to version mismatch "
                        f"(cache={cache_version}, expected={EXTRACTION_CACHE_VERSION})"
                    )
                    return None
                data.pop("_cache_version", None)
                return ExtractedInfo(**data)
            except Exception as e:
                logger.warning(f"Failed to load cache for {paper_id}: {e}")
        return None

    def _save_cache(self, info: ExtractedInfo) -> None:
        """キャッシュに保存"""
        cache_path = self._get_cache_path(info.paper_id)
        try:
            payload = info.model_dump()
            payload["_cache_version"] = EXTRACTION_CACHE_VERSION
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save cache for {info.paper_id}: {e}")

    def _extract_latex_from_tar(self, file_path: Path) -> str | None:
        """tar.gz から LaTeX ファイルを抽出してテキストを返す"""
        try:
            content = file_path.read_bytes()
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                tex_files = []
                bbl_files = []
                for member in tar.getmembers():
                    if member.isfile() and member.name.endswith(".tex"):
                        tex_files.append(member)
                    if member.isfile() and member.name.endswith(".bbl"):
                        bbl_files.append(member)

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
                extra_bbl = ""
                if bbl_files:
                    # .bbl は複数あることがあるので最大サイズを採用
                    bbl = max(bbl_files, key=lambda x: x.size)
                    bf = tar.extractfile(bbl)
                    if bf is not None:
                        extra_bbl = bf.read().decode("utf-8", errors="ignore")
                        logger.info(f"Extracted {bbl.name} ({len(extra_bbl)} chars)")

                combined = tex_content
                if extra_bbl:
                    combined = f"{tex_content}\n\n% --- BEGIN BBL ---\n{extra_bbl}\n% --- END BBL ---\n"

                logger.info(
                    f"Extracted {main_file.name} (+bbl={bool(extra_bbl)}) ({len(combined)} chars)"
                )
                return combined

        except Exception as e:
            logger.error(f"Failed to extract LaTeX from {file_path}: {e}")
            return None

    def _read_file_content(self, file_path: Path, file_type: FileType) -> tuple[list, dict[int, str] | None]:
        """ファイル内容を読み込んでメッセージ形式に変換（参考文献マップも返す）"""
        content = file_path.read_bytes()

        if file_type == FileType.PDF:
            # PDF はマルチモーダルで送信
            return ([
                {"type": "text", "text": EXTRACTION_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:application/pdf;base64,{base64.b64encode(content).decode()}"
                    },
                },
            ], None)
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

            # 参考文献（番号付き）を抽出して、LLM に番号ベースの出力を促す
            references_map = _extract_numbered_references_from_latex(text_content)
            references_hint = ""
            if references_map:
                lines = []
                for n in sorted(references_map.keys()):
                    lines.append(f"[{n}] {references_map[n]}")
                references_hint = (
                    "\n\n---\n\n"
                    "NUMBERED_REFERENCE_LIST:\n"
                    + "\n".join(lines)
                    + "\n"
                )

            # テキストを制限（トークン制限対策）
            max_chars = 10000000
            if len(text_content) > max_chars:
                text_content = text_content[:max_chars]
                logger.info(f"Truncated LaTeX content to {max_chars} chars")

            return ([
                {
                    "type": "text",
                    "text": f"{EXTRACTION_PROMPT}{references_hint}\n\n---\n\n{text_content}",
                },
            ], references_map if references_map else None)

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
            message_content, references_map = self._read_file_content(file_path, file_type)
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

                # === citation タイトルの決定（番号ベース）===
                # LaTeX から参考文献を抽出できた場合、LLM の title 推測に依存せず、
                # reference_number からタイトルを決定して表記ゆれ/誤字を減らす。
                needs_llm_freeform: list[tuple[int, str]] = []
                if references_map and result.cited_papers:
                    for cited in result.cited_papers:
                        n = cited.reference_number
                        if not n or n not in references_map:
                            continue
                        entry = references_map[n]
                        title = _extract_title_from_reference_entry(entry)
                        if title:
                            cited.title = title
                        elif not (cited.title and cited.title.strip()):
                            # タイトル抽出に失敗した場合は、LLM が title を埋めていればそれを使う。
                            # title も空の場合のみ、空のままにせず参考文献テキストを入れる
                            # （以降の ID 生成やグラフ表示の破綻を避ける）
                            cited.title = entry

                # === title に引用全文が入ってしまうケースの後処理 ===
                # 1) まずは正規表現で citation text -> title 抽出を試みる
                for i, cited in enumerate(result.cited_papers or []):
                    if cited.title and _looks_like_full_citation(cited.title):
                        candidate = _extract_title_from_reference_entry(cited.title)
                        if candidate:
                            cited.title = candidate
                        else:
                            # 2) 失敗したら LLM に「タイトルだけ」を抽出させる（バッチ化）
                            needs_llm_freeform.append((i, cited.title))

                # LLM フォールバック（必要最小限・最大20件）
                if needs_llm_freeform:
                    limited = needs_llm_freeform[:20]
                    prompt = (
                        "Extract ONLY the paper title from each bibliography/citation text.\n"
                        "Rules:\n"
                        "- Output the title only (no authors, venue, year, arXiv/DOI).\n"
                        "- Preserve original capitalization.\n"
                        "- If you cannot find a title, output an empty string.\n\n"
                        "INPUTS:\n"
                    )
                    for idx, txt in limited:
                        prompt += f"[{idx}] {txt}\n"

                    title_llm = self.llm.with_structured_output(_FreeformTitleExtraction)
                    try:
                        extracted = title_llm.invoke([HumanMessage(content=[{"type": "text", "text": prompt}])])
                        if extracted and extracted.results:
                            by_index = {r.index: (r.title or "").strip() for r in extracted.results}
                            for idx, _txt in limited:
                                new_title = by_index.get(idx, "").strip()
                                if new_title:
                                    result.cited_papers[idx].title = new_title
                    except Exception as e:
                        logger.warning(f"LLM title post-processing failed for {paper_id}: {e}")

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
