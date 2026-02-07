"""CoI出力をProposal形式に変換するサービス

CoI-Agentの出力（非構造化テキスト）をLLMで解析し、
IdeaGraphのProposal形式に変換する。
"""

import logging
import re

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from idea_graph.config import settings
from idea_graph.constants import OUTPUT_CONSTRAINTS
from idea_graph.services.coi_runner import CoIResult
from idea_graph.services.proposal import Experiment, Grounding, Proposal

logger = logging.getLogger(__name__)

# 定数のエイリアス
_C = OUTPUT_CONSTRAINTS


class ExtractedProposal(BaseModel):
    """LLMで抽出されたProposal構造"""

    title: str = Field(description=f"Research idea title ({_C.TITLE})")
    motivation: str = Field(description=f"Problem and why it matters ({_C.MOTIVATION_WORDS})")
    method: str = Field(description=f"Proposed approach/solution ({_C.METHOD_WORDS})")
    differences: list[str] = Field(
        description=f"Key differences from existing work {_C.differences_constraint()}"
    )
    datasets: list[str] = Field(
        description=f"Datasets for experiments {_C.datasets_constraint()}"
    )
    baselines: list[str] = Field(
        description=f"Baseline methods {_C.baselines_constraint()}"
    )
    metrics: list[str] = Field(
        description=f"Evaluation metrics {_C.metrics_constraint()}"
    )
    ablations: list[str] = Field(
        description=f"Ablation studies {_C.ablations_constraint()}"
    )
    expected_results: str = Field(
        description=f"Expected experimental results ({_C.EXPECTED_RESULTS_WORDS})"
    )
    rationale: str = Field(
        description=f"Why the authors propose this specific approach ({_C.RATIONALE_WORDS})"
    )
    research_trends: str = Field(
        description=f"Related research context and trends ({_C.RESEARCH_TRENDS_WORDS})"
    )
    failure_interpretation: str = Field(
        description=f"Acknowledged limitations and failure modes ({_C.FAILURE_INTERPRETATION_WORDS})"
    )


class CoIConverter:
    """CoI出力をProposal形式に変換するコンバーター"""

    CONVERSION_PROMPT_TEMPLATE = """You are an expert AI research analyst. Extract and elaborate structured information from the following CoI-generated research idea.

## CoI-Generated Idea:
{idea}

## CoI-Generated Experiment Plan:
{experiment}

## Research Trend (Context):
{trend}

## Related Entities:
{entities}

## Instructions
Extract and elaborate the following structured fields from the above text. For each field, provide comprehensive, detailed content that fully explains the research idea.

1. **title**: A concise, descriptive title for the research idea ({title_constraint})
2. **motivation**: The problem being addressed and why it matters ({motivation_constraint})
   - What specific gap or limitation exists in current approaches?
   - Why is this problem important for the research community?
   - What are the real-world implications of solving this problem?
   - What prior attempts have been made and why were they insufficient?
3. **method**: The proposed approach or solution ({method_constraint})
   - What is the core technical innovation?
   - How does the proposed method work step by step?
   - What are the key components or modules of the approach?
   - How do the components interact to achieve the desired outcome?
4. **differences**: Key differences from prior work {differences_constraint}
5. **datasets**: Datasets to use in experiments {datasets_constraint}
6. **baselines**: Baseline methods to compare against {baselines_constraint}
7. **metrics**: Evaluation metrics to use {metrics_constraint}
8. **ablations**: Ablation studies to conduct {ablations_constraint}
9. **expected_results**: Expected experimental outcomes ({expected_results_constraint})
10. **rationale**: Why the authors propose this specific approach ({rationale_constraint})
    - What insight from the idea chain or trend analysis led to this direction?
    - What combination of existing techniques or findings inspired this approach?
    - Why was this approach chosen over other possible directions?
    - What theoretical or empirical evidence supports this direction?
11. **research_trends**: Related research context and trends ({research_trends_constraint})
    - What technologies or methods are evolving and in which direction?
    - What is the lineage of related techniques?
    - Where is the research heading based on recent developments?
    - How does this idea fit into the broader research landscape?
12. **failure_interpretation**: Limitations and failure modes ({failure_interpretation_constraint})
    - Under what conditions might the proposed method underperform?
    - What assumptions could be violated in practice?

CRITICAL: Each field MUST meet its minimum word count. Do NOT produce short summaries or single-sentence answers. Provide thorough, detailed explanations for every field.

Focus on extracting concrete, actionable research information. If information is not clearly stated, make reasonable inferences based on the context."""

    def __init__(self, model_name: str | None = None) -> None:
        """初期化

        Args:
            model_name: 使用するLLMモデル名
        """
        self.model_name = model_name or settings.openai_model
        self._llm = None

    @property
    def llm(self) -> ChatOpenAI:
        """LLMインスタンスを取得"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.model_name,
                api_key=settings.openai_api_key,
                temperature=0.0,
            )
        return self._llm

    def _build_conversion_prompt(self, coi_result: CoIResult) -> str:
        """変換プロンプトを構築

        Args:
            coi_result: CoI-Agentの出力

        Returns:
            変換プロンプト
        """
        return self.CONVERSION_PROMPT_TEMPLATE.format(
            idea=coi_result.idea or "No idea provided",
            experiment=coi_result.experiment or "No experiment plan provided",
            trend=coi_result.trend or "No trend information",
            entities=coi_result.entities or "No entities listed",
            title_constraint=_C.TITLE,
            motivation_constraint=_C.MOTIVATION_WORDS,
            method_constraint=_C.METHOD_WORDS,
            differences_constraint=_C.differences_constraint(),
            datasets_constraint=_C.datasets_constraint(),
            baselines_constraint=_C.baselines_constraint(),
            metrics_constraint=_C.metrics_constraint(),
            ablations_constraint=_C.ablations_constraint(),
            expected_results_constraint=_C.EXPECTED_RESULTS_WORDS,
            rationale_constraint=_C.RATIONALE_WORDS,
            research_trends_constraint=_C.RESEARCH_TRENDS_WORDS,
            failure_interpretation_constraint=_C.FAILURE_INTERPRETATION_WORDS,
        )

    def _extract_title_from_idea(self, idea: str) -> str:
        """アイデアテキストからタイトルを抽出（フォールバック用）

        Args:
            idea: アイデアテキスト

        Returns:
            抽出されたタイトル
        """
        # "Title:" や "##" で始まる行を探す
        lines = idea.split("\n")
        for line in lines:
            line = line.strip()
            if line.lower().startswith("title:"):
                return line[6:].strip()
            if line.startswith("# ") or line.startswith("## "):
                return line.lstrip("#").strip()

        # 最初の非空行を使用
        for line in lines:
            line = line.strip()
            if line and len(line) < 200:
                return line[:100]

        return "Untitled Research Idea"

    def convert_to_proposal(self, coi_result: CoIResult) -> Proposal:
        """CoI出力をProposal形式に変換

        Args:
            coi_result: CoI-Agentの出力

        Returns:
            変換されたProposal
        """
        logger.info("Converting CoI result to Proposal format")

        # LLMで構造化抽出
        prompt = self._build_conversion_prompt(coi_result)
        message = HumanMessage(content=prompt)

        try:
            structured_llm = self.llm.with_structured_output(ExtractedProposal)
            extracted: ExtractedProposal = structured_llm.invoke([message])
        except Exception as e:
            logger.warning(f"LLM extraction failed, using fallback: {e}")
            extracted = self._fallback_extraction(coi_result)

        # アイデアチェーンからrelated papers を抽出（簡易的な方法）
        related_papers = self._extract_papers_from_chain(coi_result.idea_chain)

        # Proposalを構築
        proposal = Proposal(
            title=extracted.title,
            rationale=extracted.rationale,
            research_trends=extracted.research_trends,
            motivation=extracted.motivation,
            method=extracted.method,
            experiment=Experiment(
                datasets=extracted.datasets,
                baselines=extracted.baselines,
                metrics=extracted.metrics,
                ablations=extracted.ablations,
                expected_results=extracted.expected_results,
                failure_interpretation=extracted.failure_interpretation,
            ),
            grounding=Grounding(
                papers=related_papers,
                entities=self._parse_entities(coi_result.entities),
                path_mermaid=self._generate_chain_mermaid(coi_result.idea_chain),
            ),
            differences=extracted.differences,
        )

        logger.info(f"Converted CoI result to Proposal: {proposal.title}")
        return proposal

    def _fallback_extraction(self, coi_result: CoIResult) -> ExtractedProposal:
        """LLM抽出失敗時のフォールバック

        Args:
            coi_result: CoI-Agentの出力

        Returns:
            フォールバックで抽出されたProposal構造
        """
        title = self._extract_title_from_idea(coi_result.idea)

        # アイデアテキストを分割して各セクションを抽出
        idea_text = coi_result.idea or ""
        exp_text = coi_result.experiment or ""

        return ExtractedProposal(
            title=title,
            motivation=self._extract_section(idea_text, ["motivation", "problem", "background"], default="See full idea text"),
            method=self._extract_section(idea_text, ["method", "approach", "methodology", "proposed"], default="See full idea text"),
            differences=["Novel approach based on CoI idea chain analysis"],
            datasets=self._extract_list_items(exp_text, ["dataset", "data"]),
            baselines=self._extract_list_items(exp_text, ["baseline", "comparison", "benchmark"]),
            metrics=self._extract_list_items(exp_text, ["metric", "evaluation", "measure"]),
            ablations=self._extract_list_items(exp_text, ["ablation", "analysis"]),
            expected_results="Performance improvement over baseline methods as described in experiment plan",
            rationale=self._extract_section(idea_text, ["rationale", "reason", "why", "justification"], default="Generated by CoI-Agent from idea chain analysis"),
            research_trends=self._extract_section(idea_text, ["trend", "direction", "evolution"], default=coi_result.trend or "Not available from CoI output"),
            failure_interpretation=self._extract_section(exp_text, ["failure", "limitation", "risk"], default="If the proposed method does not outperform baselines, it may indicate that the key assumptions need revision or the approach requires further refinement."),
        )

    def _extract_section(self, text: str, keywords: list[str], default: str = "") -> str:
        """テキストからセクションを抽出

        Args:
            text: 元テキスト
            keywords: 検索キーワード
            default: デフォルト値

        Returns:
            抽出されたセクション
        """
        lines = text.split("\n")
        capturing = False
        captured = []

        for line in lines:
            line_lower = line.lower()
            # キーワードを含む見出しを探す
            if any(kw in line_lower for kw in keywords) and (":" in line or line.startswith("#")):
                capturing = True
                # 見出し行自体にコンテンツがある場合
                if ":" in line:
                    content = line.split(":", 1)[1].strip()
                    if content:
                        captured.append(content)
                continue

            if capturing:
                # 新しいセクションの開始を検出
                if line.startswith("#") or (line.strip() and line.strip().endswith(":")):
                    break
                if line.strip():
                    captured.append(line.strip())

        if captured:
            return " ".join(captured)[:1000]
        return default

    def _extract_list_items(self, text: str, keywords: list[str]) -> list[str]:
        """テキストからリストアイテムを抽出

        Args:
            text: 元テキスト
            keywords: 検索キーワード

        Returns:
            抽出されたリスト
        """
        items = []
        lines = text.split("\n")

        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords):
                # この行または続く行からアイテムを抽出
                # 箇条書きを探す
                for j in range(i, min(i + 10, len(lines))):
                    check_line = lines[j].strip()
                    if check_line.startswith(("-", "*", "•", "1.", "2.", "3.")):
                        item = check_line.lstrip("-*•0123456789. ").strip()
                        if item and len(item) < 200:
                            items.append(item)

        return items[:5] if items else ["See experiment plan"]

    def _extract_papers_from_chain(self, idea_chain: str) -> list[str]:
        """アイデアチェーンから論文タイトルを抽出

        Args:
            idea_chain: アイデアチェーン文字列

        Returns:
            論文タイトルリスト
        """
        if not idea_chain:
            return []

        papers = []
        # "Paper:" や引用形式を探す
        lines = idea_chain.split("\n")
        for line in lines:
            line = line.strip()
            if "paper" in line.lower() or ":" in line:
                # 引用符で囲まれた部分を抽出
                matches = re.findall(r'"([^"]+)"', line)
                papers.extend(matches)
                # または行全体が論文タイトルの可能性
                if not matches and len(line) > 10 and len(line) < 200:
                    # 行番号やステップ番号を除去
                    cleaned = re.sub(r"^[\d\.\)\-\s]+", "", line)
                    if cleaned and not cleaned.lower().startswith(("step", "idea", "then", "next")):
                        papers.append(cleaned)

        return list(set(papers))[:5]

    def _parse_entities(self, entities_str: str) -> list[str]:
        """エンティティ文字列をリストに変換

        Args:
            entities_str: エンティティ文字列

        Returns:
            エンティティリスト
        """
        if not entities_str:
            return []

        entities = []
        # カンマ、改行、セミコロンで分割
        for sep in ["\n", ",", ";"]:
            if sep in entities_str:
                parts = entities_str.split(sep)
                for part in parts:
                    part = part.strip().strip("-*•").strip()
                    if part and len(part) < 100:
                        entities.append(part)
                return list(set(entities))[:10]

        # 分割できない場合はそのまま返す
        return [entities_str[:100]] if entities_str else []

    def _generate_chain_mermaid(self, idea_chain: str) -> str:
        """アイデアチェーンからMermaid図を生成

        Args:
            idea_chain: アイデアチェーン文字列

        Returns:
            Mermaid図文字列
        """
        if not idea_chain:
            return "graph LR\n  A[CoI Generated Idea]"

        lines = ["graph LR"]

        # 簡易的なチェーン解析
        steps = []
        for line in idea_chain.split("\n"):
            line = line.strip()
            if line and len(line) > 5:
                # ステップ番号を除去してラベルを作成
                label = re.sub(r"^[\d\.\)\-\s]+", "", line)[:40]
                if label:
                    steps.append(label)

        if not steps:
            return "graph LR\n  A[CoI Generated Idea]"

        # 最大5ステップに制限
        steps = steps[:5]
        for i, step in enumerate(steps):
            node_id = f"N{i}"
            # 特殊文字をエスケープ
            safe_label = step.replace('"', "'").replace("[", "(").replace("]", ")")
            lines.append(f'  {node_id}["{safe_label}"]')
            if i > 0:
                lines.append(f"  N{i-1} --> {node_id}")

        return "\n".join(lines)
