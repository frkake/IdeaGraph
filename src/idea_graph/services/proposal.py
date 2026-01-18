"""研究アイデア提案サービス"""

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.services.analysis import AnalysisResult, PathNode
from idea_graph.services.prompt_context import PromptContextBuilder, PromptExpansionOptions

logger = logging.getLogger(__name__)


class Experiment(BaseModel):
    """実験計画"""

    datasets: list[str] = Field(description="使用データセット候補")
    baselines: list[str] = Field(description="比較対象ベースライン")
    metrics: list[str] = Field(description="評価指標")
    ablations: list[str] = Field(description="アブレーション実験")
    expected_results: str = Field(description="期待される結果")
    failure_interpretation: str = Field(description="失敗時の解釈")


class Grounding(BaseModel):
    """根拠"""

    papers: list[str] = Field(description="参照論文リスト")
    entities: list[str] = Field(description="関連エンティティリスト")
    path_mermaid: str = Field(description="マルチホップ経路のMermaid図")


class Proposal(BaseModel):
    """提案"""

    title: str = Field(description="仮タイトル")
    rationale: str = Field(
        description="提案理由（なぜこの提案を生成したか：知識グラフのどの接続・パスから着想したか、どの論文の組み合わせからインスピレーションを得たか）"
    )
    research_trends: str = Field(
        description="研究動向（知識グラフから見える研究の流れ：どの技術が発展しているか、研究がどの方向に進んでいるか、関連手法の進化の系譜）"
    )
    motivation: str = Field(description="動機（何が未解決で、なぜ重要か）")
    method: str = Field(description="手法（何をどう変えるか）")
    experiment: Experiment = Field(description="実験計画")
    grounding: Grounding = Field(description="根拠")
    differences: list[str] = Field(description="既存との差分・貢献")


class TargetPaperInfo(BaseModel):
    """ターゲット論文の情報"""

    id: str = Field(description="論文ID")
    title: str = Field(description="論文タイトル")


class ProposalResult(BaseModel):
    """提案結果"""

    target_paper_id: str  # 後方互換性のため維持
    target_paper: TargetPaperInfo | None = Field(
        default=None, description="ターゲット論文の情報（後方互換性のためオプション）"
    )
    proposals: list[Proposal]
    prompt: str


class ProposalService:
    """研究アイデア提案サービス"""

    def __init__(self, model_name: str | None = None):
        """初期化"""
        self.model_name = model_name or settings.openai_model
        self._llm = None

    @property
    def llm(self) -> ChatOpenAI:
        """LLM インスタンスを取得"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.model_name,
                api_key=settings.openai_api_key,
                temperature=0.0,
            )
        return self._llm

    def _get_paper_context(self, paper_id: str) -> dict[str, Any]:
        """論文のコンテキストを取得"""
        with Neo4jConnection.session() as session:
            result = session.run(
                """
                MATCH (p:Paper {id: $id})
                OPTIONAL MATCH (p)-[:MENTIONS]->(e:Entity)
                RETURN p.title AS title,
                       p.summary AS summary,
                       p.claims AS claims,
                       collect(DISTINCT {type: e.type, name: e.name}) AS entities
                """,
                id=paper_id,
            )
            record = result.single()
            if record:
                return {
                    "title": record["title"],
                    "summary": record["summary"],
                    "claims": record["claims"] or [],
                    "entities": [e for e in record["entities"] if e["name"]],
                }
            return {}

    def _resolve_prompt_options(
        self,
        prompt_options: PromptExpansionOptions | dict | None,
    ) -> PromptExpansionOptions:
        if prompt_options is None:
            return PromptExpansionOptions()
        if isinstance(prompt_options, PromptExpansionOptions):
            return prompt_options
        if isinstance(prompt_options, dict):
            try:
                return PromptExpansionOptions(**prompt_options)
            except ValidationError as exc:
                raise ValueError(f"Invalid prompt options: {exc}") from exc
        raise ValueError("prompt_options must be a dict or PromptExpansionOptions")

    def _build_prompt(
        self,
        target_paper_id: str,
        paper_context: dict[str, Any],
        analysis_result: AnalysisResult,
        num_proposals: int,
        constraints: dict | None,
        prompt_options: PromptExpansionOptions | dict | None = None,
    ) -> str:
        """プロンプトを構築"""
        options = self._resolve_prompt_options(prompt_options)
        graph_context = PromptContextBuilder().build_context(
            target_paper_id,
            analysis_result,
            options,
        )

        constraints_text = ""
        if constraints:
            constraints_text = "\n".join([f"- {k}: {v}" for k, v in constraints.items()])

        prompt = f"""You are an AI research advisor. Based on the following analysis of research papers, propose {num_proposals} novel research ideas.

## Graph Context
{graph_context or 'No graph context available'}

## Constraints
{constraints_text or 'No specific constraints'}

## Requirements for each proposal
1. **Title**: A concise, descriptive title for the research idea
2. **Rationale (Why This Proposal)**: Explain WHY you are proposing this specific idea:
   - Which path/connection in the knowledge graph led to this insight?
   - Which combination of papers inspired this direction?
   - What gap or opportunity did you identify from the multi-hop analysis?
   - Why did you choose this approach over other possible directions?
3. **Research Trends**: Describe the research trends observed from the knowledge graph:
   - What technologies/methods are evolving and in which direction?
   - What is the lineage of related techniques (e.g., A → B → C)?
   - Where is the research heading based on citation patterns and entity relationships?
4. **Motivation**: What problem remains unsolved? Why is it important? Connect to the target paper and analysis results.
5. **Method**: Specifically what to change (model/algorithm/training/inference/data/evaluation)
6. **Experiment Plan**:
   - Datasets to use (existing or new collection)
   - Baselines for comparison
   - Evaluation metrics
   - At least one ablation study
   - Expected results and failure interpretation
7. **Grounding**: Which papers and entities support this idea
8. **Differences**: How this differs from existing work (at least 1 point)

Generate diverse ideas that don't overlap. Focus on practical, implementable research directions.
"""
        return prompt

    def _generate_mermaid(self, path_nodes: list[PathNode]) -> str:
        """Mermaid 図を生成"""
        if not path_nodes:
            return "graph LR\n  A[No path]"

        lines = ["graph LR"]
        for i, node in enumerate(path_nodes):
            node_id = f"N{i}"
            label = node.name[:30] + "..." if len(node.name) > 30 else node.name
            lines.append(f"  {node_id}[{label}]")
            if i > 0:
                lines.append(f"  N{i-1} --> {node_id}")

        return "\n".join(lines)

    def propose(
        self,
        target_paper_id: str,
        analysis_result: AnalysisResult,
        num_proposals: int = 3,
        constraints: dict | None = None,
        prompt_options: PromptExpansionOptions | dict | None = None,
    ) -> ProposalResult:
        """研究アイデアを提案

        Args:
            target_paper_id: ターゲット論文ID
            analysis_result: 分析結果
            num_proposals: 提案数
            constraints: 制約条件

        Returns:
            提案結果

        Raises:
            ValueError: 分析結果が空の場合
        """
        if not analysis_result.candidates:
            raise ValueError("Analysis result has no candidates. Run analysis first.")

        # コンテキストを取得
        paper_context = self._get_paper_context(target_paper_id)
        if not paper_context:
            paper_context = {"title": target_paper_id, "summary": "", "claims": [], "entities": []}

        # プロンプトを構築
        prompt = self._build_prompt(
            target_paper_id,
            paper_context,
            analysis_result,
            num_proposals,
            constraints,
            prompt_options,
        )

        # 構造化出力で生成
        class ProposalsOutput(BaseModel):
            proposals: list[Proposal]

        try:
            structured_llm = self.llm.with_structured_output(ProposalsOutput)
            message = HumanMessage(content=prompt)
            result = structured_llm.invoke([message])

            # 根拠情報を補完
            for proposal in result.proposals:
                # 分析結果から関連論文とエンティティを抽出
                papers = []
                entities = []
                for path in analysis_result.candidates[:3]:
                    for node in path.nodes:
                        if node.label == "Paper":
                            papers.append(node.name)
                        else:
                            entities.append(node.name)

                proposal.grounding.papers = list(set(papers))[:5]
                proposal.grounding.entities = list(set(entities))[:5]

                # Mermaid 図を生成
                if analysis_result.candidates:
                    proposal.grounding.path_mermaid = self._generate_mermaid(
                        analysis_result.candidates[0].nodes
                    )

            # ターゲット論文情報を作成
            target_paper_info = TargetPaperInfo(
                id=target_paper_id,
                title=paper_context.get("title", target_paper_id),
            )

            return ProposalResult(
                target_paper_id=target_paper_id,
                target_paper=target_paper_info,
                proposals=result.proposals[:num_proposals],
                prompt=prompt,
            )

        except Exception as e:
            logger.error(f"Proposal generation failed: {e}")
            raise ValueError(f"Failed to generate proposals: {e}")
