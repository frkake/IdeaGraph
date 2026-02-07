"""FastAPI アプリケーション"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.services.evaluation import EvaluationService
from idea_graph.services.prompt_context import PromptExpansionOptions

# パス設定
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="IdeaGraph API",
    description="AI論文のナレッジグラフ構築・可視化API",
    version="0.1.0",
)

# 静的ファイルとテンプレート
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR)) if TEMPLATES_DIR.exists() else None


# ========== ヘルスチェック ==========


@app.get("/health")
def health_check():
    """ヘルスチェック"""
    neo4j_ok = Neo4jConnection.verify_connectivity()
    return {
        "status": "ok" if neo4j_ok else "degraded",
        "neo4j": "connected" if neo4j_ok else "disconnected",
    }


# ========== 可視化 API ==========


class VisualizationConfig(BaseModel):
    """可視化設定"""

    neo4j_uri: str
    user: str
    initial_cypher: str
    styling: dict


@app.get("/api/visualization/config")
def get_visualization_config() -> VisualizationConfig:
    """可視化設定を取得"""
    return VisualizationConfig(
        neo4j_uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        initial_cypher="MATCH (p:Paper)-[r]->(n) RETURN p, r, n LIMIT 100",
        styling={
            "Paper": {"color": "#4A90D9", "size": 25, "caption": "title"},
            "Entity": {"color": "#7CB342", "size": 20, "caption": "name"},
        },
    )


class CypherQuery(BaseModel):
    """Cypher クエリ"""

    cypher: str
    params: dict | None = None


class GraphData(BaseModel):
    """グラフデータ"""

    nodes: list[dict]
    edges: list[dict]


@app.post("/api/visualization/query")
def execute_visualization_query(query: CypherQuery) -> GraphData:
    """Cypher クエリを実行してグラフデータを返す"""
    # 安全性チェック: 読み取り専用クエリのみ許可
    cypher_upper = query.cypher.upper()
    if any(keyword in cypher_upper for keyword in ["CREATE", "DELETE", "SET", "REMOVE", "MERGE"]):
        raise HTTPException(status_code=400, detail="Only read queries are allowed")

    try:
        nodes = []
        edges = []
        seen_nodes = set()
        seen_edges = set()

        with Neo4jConnection.session() as session:
            result = session.run(query.cypher, query.params or {})

            for record in result:
                for value in record.values():
                    if hasattr(value, "id") and hasattr(value, "labels"):
                        # Node
                        node_id = value.element_id
                        if node_id not in seen_nodes:
                            seen_nodes.add(node_id)
                            nodes.append({
                                "id": node_id,
                                "labels": list(value.labels),
                                "properties": dict(value),
                            })
                    elif hasattr(value, "type") and hasattr(value, "start_node"):
                        # Relationship
                        edge_id = value.element_id
                        if edge_id not in seen_edges:
                            seen_edges.add(edge_id)
                            edges.append({
                                "id": edge_id,
                                "type": value.type,
                                "source": value.start_node.element_id,
                                "target": value.end_node.element_id,
                                "properties": dict(value),
                            })

        return GraphData(nodes=nodes, edges=edges)

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== 分析 API ==========


class AnalyzeRequest(BaseModel):
    """分析リクエスト"""

    target_paper_id: str
    multihop_k: int = 3
    top_n: int = 10
    response_limit: int | None = None
    save: bool = False


class PathNode(BaseModel):
    """パスノード"""

    id: str
    label: str
    name: str
    entity_type: str | None = None
    description: str | None = None


class PathEdge(BaseModel):
    """パスエッジ"""

    type: str
    from_id: str | None = None
    to_id: str | None = None
    importance_score: int | None = None
    citation_type: str | None = None
    context: str | None = None


class RankedPath(BaseModel):
    """ランク付きパス"""

    nodes: list[PathNode]
    edges: list[PathEdge]
    score: float
    # NOTE:
    # `score_breakdown` には `rel_types: list[str]` のような非float値も含まれるため、
    # dict[str, float] だと FastAPI のレスポンス検証で ResponseValidationError になる。
    score_breakdown: dict[str, Any] | None = None


class AnalysisResult(BaseModel):
    """分析結果"""

    target_paper_id: str
    candidates: list[RankedPath]
    paper_paths: list[RankedPath] | None = None
    entity_paths: list[RankedPath] | None = None
    multihop_k: int
    total_paths: int | None = None
    total_paper_paths: int | None = None
    total_entity_paths: int | None = None
    total_nodes: int | None = None
    total_edges: int | None = None
    analysis_id: str | None = None


@app.post("/api/analyze")
def analyze_paper(request: AnalyzeRequest) -> AnalysisResult:
    """論文のマルチホップ分析を実行"""
    from idea_graph.services.analysis import AnalysisService

    service = AnalysisService()
    try:
        result = service.analyze(
            target_paper_id=request.target_paper_id,
            multihop_k=request.multihop_k,
            top_n=request.top_n,
        )
        analysis_id = None
        if request.save:
            from idea_graph.services.storage import StorageService

            storage = StorageService()
            saved = storage.save_analysis(
                target_paper_id=request.target_paper_id,
                analysis_result=result.model_dump(),
            )
            analysis_id = saved.id

        response_result = result
        if request.response_limit is not None:
            limit = max(0, request.response_limit)
            response_result = result.model_copy(update={
                "candidates": result.candidates[:limit],
            })

        payload = response_result.model_dump()
        payload["analysis_id"] = analysis_id
        return payload
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== 提案 API ==========


class ProposeRequest(BaseModel):
    """提案リクエスト"""

    target_paper_id: str
    analysis_id: str | None = None
    analysis_result: AnalysisResult | None = None
    num_proposals: int = 3
    constraints: dict | None = None
    prompt_options: PromptExpansionOptions | None = None
    model_name: str | None = None


class Experiment(BaseModel):
    """実験計画"""

    datasets: list[str]
    baselines: list[str]
    metrics: list[str]
    ablations: list[str]
    expected_results: str
    failure_interpretation: str


class Grounding(BaseModel):
    """根拠"""

    papers: list[str]
    entities: list[str]
    path_mermaid: str


class Proposal(BaseModel):
    """提案"""

    title: str
    rationale: str
    research_trends: str
    motivation: str
    method: str
    experiment: Experiment
    grounding: Grounding
    differences: list[str]


class ProposalResult(BaseModel):
    """提案結果"""

    target_paper_id: str
    proposals: list[Proposal]
    prompt: str | None = None


@app.post("/api/propose")
def propose_ideas(request: ProposeRequest) -> ProposalResult:
    """研究アイデアを提案"""
    from idea_graph.services.analysis import AnalysisResult as ServiceAnalysisResult
    from idea_graph.services.proposal import ProposalService

    service = ProposalService(model_name=request.model_name)
    try:
        analysis_result = None
        if request.analysis_id:
            from idea_graph.services.storage import StorageService

            storage = StorageService()
            saved = storage.load_analysis(request.analysis_id)
            if saved is None:
                raise HTTPException(status_code=404, detail="Analysis not found")
            analysis_result = ServiceAnalysisResult.model_validate(saved.data)
        elif request.analysis_result:
            analysis_payload = request.analysis_result.model_dump(exclude={"analysis_id"})
            analysis_result = ServiceAnalysisResult.model_validate(analysis_payload)
        else:
            raise HTTPException(status_code=400, detail="analysis_id or analysis_result is required")

        result = service.propose(
            target_paper_id=request.target_paper_id,
            analysis_result=analysis_result,
            num_proposals=request.num_proposals,
            constraints=request.constraints,
            prompt_options=request.prompt_options,
        )
        return result
    except (ValueError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class PromptPreviewRequest(BaseModel):
    """プロンプトプレビューリクエスト"""

    target_paper_id: str
    analysis_id: str | None = None
    analysis_result: dict[str, Any] | None = None
    num_proposals: int = 3
    constraints: dict | None = None
    prompt_options: PromptExpansionOptions | None = None


class PromptPreviewResult(BaseModel):
    """プロンプトプレビュー結果"""

    prompt: str


@app.post("/api/propose/preview")
def preview_prompt(request: PromptPreviewRequest) -> PromptPreviewResult:
    """提案生成用プロンプトをプレビュー（LLM呼び出しなし）"""
    from idea_graph.services.analysis import AnalysisResult as ServiceAnalysisResult
    from idea_graph.services.proposal import ProposalService

    service = ProposalService()
    try:
        if request.analysis_id:
            from idea_graph.services.storage import StorageService

            storage = StorageService()
            saved = storage.load_analysis(request.analysis_id)
            if saved is None:
                raise HTTPException(status_code=404, detail="Analysis not found")
            analysis_result = ServiceAnalysisResult.model_validate(saved.data)
        elif request.analysis_result:
            analysis_payload = dict(request.analysis_result)
            analysis_payload.pop("analysis_id", None)
            analysis_result = ServiceAnalysisResult.model_validate(analysis_payload)
        else:
            raise HTTPException(status_code=400, detail="analysis_id or analysis_result is required")

        prompt = service.build_prompt_preview(
            target_paper_id=request.target_paper_id,
            analysis_result=analysis_result,
            num_proposals=request.num_proposals,
            constraints=request.constraints,
            prompt_options=request.prompt_options,
        )
        return PromptPreviewResult(prompt=prompt)
    except (ValueError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== ストレージ API ==========


class SaveAnalysisRequest(BaseModel):
    """分析保存リクエスト"""

    target_paper_id: str
    target_paper_title: str | None = None
    analysis_result: dict[str, Any]


class SaveProposalRequest(BaseModel):
    """提案保存リクエスト"""

    target_paper_id: str
    target_paper_title: str | None = None
    analysis_id: str | None = None
    proposal: dict[str, Any]
    prompt: str | None = None
    rating: int | None = None
    notes: str | None = None
    proposal_type: str | None = None
    model_name: str | None = None


class UpdateProposalRequest(BaseModel):
    """提案更新リクエスト"""

    rating: int | None = None
    notes: str | None = None


@app.post("/api/storage/analyses")
def save_analysis_result(request: SaveAnalysisRequest):
    """分析結果を保存"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    saved = service.save_analysis(
        target_paper_id=request.target_paper_id,
        analysis_result=request.analysis_result,
        target_paper_title=request.target_paper_title,
    )
    return saved


@app.get("/api/storage/analyses")
def list_saved_analyses(target_paper_id: str | None = None, limit: int = 50):
    """保存された分析結果の一覧を取得"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    analyses = service.list_analyses(target_paper_id=target_paper_id, limit=limit)
    return {"analyses": [a.model_dump() for a in analyses]}


@app.get("/api/storage/analyses/{analysis_id}")
def get_saved_analysis(analysis_id: str, preview_limit: int | None = None):
    """保存された分析結果を取得"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    analysis = service.load_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if preview_limit is None:
        return analysis

    limit = max(0, preview_limit)
    analysis_copy = analysis.model_copy(deep=True)
    data = analysis_copy.data
    candidates = data.get("candidates")
    if isinstance(candidates, list):
        data["candidates"] = candidates[:limit]
    analysis_copy.data = data
    return analysis_copy


@app.delete("/api/storage/analyses/{analysis_id}")
def delete_saved_analysis(analysis_id: str):
    """保存された分析結果を削除"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    if not service.delete_analysis(analysis_id):
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"status": "deleted"}


@app.post("/api/storage/proposals")
def save_proposal_result(request: SaveProposalRequest):
    """提案を保存"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    saved = service.save_proposal(
        target_paper_id=request.target_paper_id,
        proposal=request.proposal,
        target_paper_title=request.target_paper_title,
        analysis_id=request.analysis_id,
        prompt=request.prompt,
        rating=request.rating,
        notes=request.notes,
        proposal_type=request.proposal_type or "idea-graph",
        model_name=request.model_name,
    )
    return saved


@app.get("/api/storage/proposals")
def list_saved_proposals(target_paper_id: str | None = None, limit: int = 50):
    """保存された提案の一覧を取得"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    proposals = service.list_proposals(target_paper_id=target_paper_id, limit=limit)
    return {"proposals": [p.model_dump() for p in proposals]}


@app.get("/api/storage/proposals/{proposal_id}")
def get_saved_proposal(proposal_id: str):
    """保存された提案を取得"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    proposal = service.load_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@app.patch("/api/storage/proposals/{proposal_id}")
def update_saved_proposal(proposal_id: str, request: UpdateProposalRequest):
    """提案の評価・メモを更新"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    updated = service.update_proposal(
        proposal_id=proposal_id,
        rating=request.rating,
        notes=request.notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return updated


@app.delete("/api/storage/proposals/{proposal_id}")
def delete_saved_proposal(proposal_id: str):
    """保存された提案を削除"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    if not service.delete_proposal(proposal_id):
        raise HTTPException(status_code=404, detail="Proposal not found")
    return {"status": "deleted"}


@app.get("/api/storage/export/proposals")
def export_proposals(
    format: str = "markdown",
    target_paper_id: str | None = None,
    proposal_ids: str | None = None,
):
    """提案をエクスポート"""
    from fastapi.responses import PlainTextResponse

    from idea_graph.services.storage import StorageService

    service = StorageService()

    ids = proposal_ids.split(",") if proposal_ids else None

    if format == "json":
        content = service.export_proposals_json(proposal_ids=ids, target_paper_id=target_paper_id)
        return PlainTextResponse(content, media_type="application/json")
    else:
        content = service.export_proposals_markdown(
            proposal_ids=ids, target_paper_id=target_paper_id
        )
        return PlainTextResponse(content, media_type="text/markdown")


# ========== 評価 API ==========


class EvaluateProposal(BaseModel):
    """評価対象の提案"""

    title: str
    rationale: str
    research_trends: str
    motivation: str
    method: str
    experiment: Experiment
    grounding: Grounding
    differences: list[str]


class EvaluateRequest(BaseModel):
    """評価リクエスト"""

    proposals: list[EvaluateProposal]
    proposal_sources: list[str] | None = None  # 各提案のソース（ideagraph, coi）
    include_experiment: bool = True
    model_name: str | None = None
    target_paper_id: str | None = None  # 論文IDを指定すると自動で内容を取得
    target_paper_content: str | None = None
    target_paper_title: str | None = None


class MetricScoreResponse(BaseModel):
    """指標スコアレスポンス"""

    metric: str
    winner: int
    reasoning: str


class PairwiseResultResponse(BaseModel):
    """ペアワイズ比較結果レスポンス"""

    idea_a_id: str
    idea_b_id: str
    scores: list[MetricScoreResponse]


class RankingEntryResponse(BaseModel):
    """ランキングエントリレスポンス"""

    rank: int
    idea_id: str
    idea_title: str | None
    overall_score: float
    scores_by_metric: dict[str, float]
    is_target_paper: bool = False
    source: str = "ideagraph"  # ideagraph, coi, target_paper


class EvaluateResponse(BaseModel):
    """評価レスポンス"""

    evaluated_at: str
    model_name: str
    ranking: list[RankingEntryResponse]
    pairwise_results: list[PairwiseResultResponse]


@app.post("/api/evaluate")
def evaluate_proposals(request: EvaluateRequest) -> EvaluateResponse:
    """提案をペアワイズ比較して評価"""
    from idea_graph.services.proposal import Proposal as ProposalModel
    from idea_graph.services.proposal import Experiment as ExperimentModel
    from idea_graph.services.proposal import Grounding as GroundingModel
    from idea_graph.cli import _get_paper_full_text

    # バリデーション
    if len(request.proposals) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 proposals are required for pairwise comparison"
        )

    # ターゲット論文の内容を取得（IDが指定されていて内容がない場合）
    target_paper_content = request.target_paper_content
    target_paper_title = request.target_paper_title
    if request.target_paper_id and not target_paper_content:
        target_paper_content = _get_paper_full_text(request.target_paper_id)
        if not target_paper_title:
            # タイトルがない場合はIDを使用
            target_paper_title = request.target_paper_id

    # リクエストをProposalモデルに変換
    proposals = []
    for p in request.proposals:
        proposal = ProposalModel(
            title=p.title,
            rationale=p.rationale,
            research_trends=p.research_trends,
            motivation=p.motivation,
            method=p.method,
            experiment=ExperimentModel(
                datasets=p.experiment.datasets,
                baselines=p.experiment.baselines,
                metrics=p.experiment.metrics,
                ablations=p.experiment.ablations,
                expected_results=p.experiment.expected_results,
                failure_interpretation=p.experiment.failure_interpretation,
            ),
            grounding=GroundingModel(
                papers=p.grounding.papers,
                entities=p.grounding.entities,
                path_mermaid=p.grounding.path_mermaid,
            ),
            differences=p.differences,
        )
        proposals.append(proposal)

    # 評価を実行
    service = EvaluationService()
    result = service.evaluate(
        proposals,
        include_experiment=request.include_experiment,
        target_paper_content=target_paper_content,
        target_paper_title=target_paper_title,
        target_paper_id=request.target_paper_id,
        proposal_sources=request.proposal_sources,
    )

    # レスポンスを構築
    ranking_response = [
        RankingEntryResponse(
            rank=entry.rank,
            idea_id=entry.idea_id,
            idea_title=entry.idea_title,
            overall_score=entry.overall_score,
            scores_by_metric={m.value: s for m, s in entry.scores_by_metric.items()},
            is_target_paper=entry.is_target_paper,
            source=entry.source.value if hasattr(entry, 'source') else "ideagraph",
        )
        for entry in result.ranking
    ]

    pairwise_response = [
        PairwiseResultResponse(
            idea_a_id=pr.idea_a_id,
            idea_b_id=pr.idea_b_id,
            scores=[
                MetricScoreResponse(
                    metric=ms.metric.value,
                    winner=ms.winner.value,
                    reasoning=ms.reasoning,
                )
                for ms in pr.scores
            ],
        )
        for pr in result.pairwise_results
    ]

    return EvaluateResponse(
        evaluated_at=result.evaluated_at.isoformat(),
        model_name=result.model_name,
        ranking=ranking_response,
        pairwise_results=pairwise_response,
    )


class EvaluationProgressResponse(BaseModel):
    """評価進捗レスポンス"""

    event_type: str  # progress, extracting_target, completed, error
    current_comparison: int = 0
    total_comparisons: int = 0
    phase: str = "comparing"
    message: str | None = None
    error: str | None = None
    result: EvaluateResponse | None = None


@app.post("/api/evaluate/stream")
async def evaluate_proposals_stream(request: EvaluateRequest):
    """提案をペアワイズ比較して評価（SSEストリーミング版）"""
    from fastapi.responses import StreamingResponse

    from idea_graph.services.proposal import Proposal as ProposalModel
    from idea_graph.services.proposal import Experiment as ExperimentModel
    from idea_graph.services.proposal import Grounding as GroundingModel
    from idea_graph.cli import _get_paper_full_text
    from idea_graph.models.evaluation import EvaluationProgressEvent, EvaluationResult

    # バリデーション
    if len(request.proposals) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 proposals are required for pairwise comparison"
        )

    # ターゲット論文の内容を取得
    target_paper_content = request.target_paper_content
    target_paper_title = request.target_paper_title
    if request.target_paper_id and not target_paper_content:
        target_paper_content = _get_paper_full_text(request.target_paper_id)
        if not target_paper_title:
            target_paper_title = request.target_paper_id

    # リクエストをProposalモデルに変換
    proposals = []
    for p in request.proposals:
        proposal = ProposalModel(
            title=p.title,
            rationale=p.rationale,
            research_trends=p.research_trends,
            motivation=p.motivation,
            method=p.method,
            experiment=ExperimentModel(
                datasets=p.experiment.datasets,
                baselines=p.experiment.baselines,
                metrics=p.experiment.metrics,
                ablations=p.experiment.ablations,
                expected_results=p.experiment.expected_results,
                failure_interpretation=p.experiment.failure_interpretation,
            ),
            grounding=GroundingModel(
                papers=p.grounding.papers,
                entities=p.grounding.entities,
                path_mermaid=p.grounding.path_mermaid,
            ),
            differences=p.differences,
        )
        proposals.append(proposal)

    async def generate():
        service = EvaluationService()

        try:
            async for event in service.evaluate_streaming(
                proposals,
                include_experiment=request.include_experiment,
                target_paper_content=target_paper_content,
                target_paper_title=target_paper_title,
                target_paper_id=request.target_paper_id,
                proposal_sources=request.proposal_sources,
            ):
                if isinstance(event, EvaluationProgressEvent):
                    response = EvaluationProgressResponse(
                        event_type=event.event_type,
                        current_comparison=event.current_comparison,
                        total_comparisons=event.total_comparisons,
                        phase=event.phase,
                        message=event.message,
                    )
                    yield f"data: {response.model_dump_json()}\n\n"
                elif isinstance(event, EvaluationResult):
                    # 最終結果
                    ranking_response = [
                        RankingEntryResponse(
                            rank=entry.rank,
                            idea_id=entry.idea_id,
                            idea_title=entry.idea_title,
                            overall_score=entry.overall_score,
                            scores_by_metric={m.value: s for m, s in entry.scores_by_metric.items()},
                            is_target_paper=entry.is_target_paper,
                            source=entry.source.value if hasattr(entry, 'source') else "ideagraph",
                        )
                        for entry in event.ranking
                    ]

                    pairwise_response = [
                        PairwiseResultResponse(
                            idea_a_id=pr.idea_a_id,
                            idea_b_id=pr.idea_b_id,
                            scores=[
                                MetricScoreResponse(
                                    metric=ms.metric.value,
                                    winner=ms.winner.value,
                                    reasoning=ms.reasoning,
                                )
                                for ms in pr.scores
                            ],
                        )
                        for pr in event.pairwise_results
                    ]

                    eval_response = EvaluateResponse(
                        evaluated_at=event.evaluated_at.isoformat(),
                        model_name=event.model_name,
                        ranking=ranking_response,
                        pairwise_results=pairwise_response,
                    )

                    response = EvaluationProgressResponse(
                        event_type="completed",
                        current_comparison=len(event.pairwise_results),
                        total_comparisons=len(event.pairwise_results),
                        phase="completed",
                        message="評価完了",
                        result=eval_response,
                    )
                    yield f"data: {response.model_dump_json()}\n\n"
        except Exception as e:
            response = EvaluationProgressResponse(
                event_type="error",
                phase="error",
                error=str(e),
            )
            yield f"data: {response.model_dump_json()}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ========== 単体（絶対）評価 API ==========


class SingleEvaluateRequest(BaseModel):
    """単体評価リクエスト"""

    proposals: list[EvaluateProposal]
    proposal_sources: list[str] | None = None
    model_name: str | None = None


class AbsoluteMetricScoreResponse(BaseModel):
    """絶対スコアレスポンス"""

    metric: str
    score: int
    reasoning: str


class SingleIdeaResultResponse(BaseModel):
    """単一アイデア評価結果レスポンス"""

    idea_id: str
    idea_title: str | None
    scores: list[AbsoluteMetricScoreResponse]
    overall_score: float
    source: str = "ideagraph"


class SingleEvaluateResponse(BaseModel):
    """単体評価レスポンス"""

    evaluated_at: str
    model_name: str
    evaluation_mode: str = "single"
    ranking: list[SingleIdeaResultResponse]


class SingleEvaluationProgressResponse(BaseModel):
    """単体評価進捗レスポンス"""

    event_type: str
    current_evaluation: int = 0
    total_evaluations: int = 0
    phase: str = "evaluating"
    message: str | None = None
    error: str | None = None
    result: SingleEvaluateResponse | None = None


def _convert_evaluate_proposals(proposals: list[EvaluateProposal]) -> list:
    """EvaluateProposalリストをサービス用Proposalモデルに変換"""
    from idea_graph.services.proposal import Proposal as ProposalModel
    from idea_graph.services.proposal import Experiment as ExperimentModel
    from idea_graph.services.proposal import Grounding as GroundingModel

    result = []
    for p in proposals:
        proposal = ProposalModel(
            title=p.title,
            rationale=p.rationale,
            research_trends=p.research_trends,
            motivation=p.motivation,
            method=p.method,
            experiment=ExperimentModel(
                datasets=p.experiment.datasets,
                baselines=p.experiment.baselines,
                metrics=p.experiment.metrics,
                ablations=p.experiment.ablations,
                expected_results=p.experiment.expected_results,
                failure_interpretation=p.experiment.failure_interpretation,
            ),
            grounding=GroundingModel(
                papers=p.grounding.papers,
                entities=p.grounding.entities,
                path_mermaid=p.grounding.path_mermaid,
            ),
            differences=p.differences,
        )
        result.append(proposal)
    return result


def _build_single_evaluate_response(result) -> SingleEvaluateResponse:
    """SingleEvaluationResultからレスポンスを構築"""
    ranking_response = [
        SingleIdeaResultResponse(
            idea_id=entry.idea_id,
            idea_title=entry.idea_title,
            scores=[
                AbsoluteMetricScoreResponse(
                    metric=s.metric.value,
                    score=s.score,
                    reasoning=s.reasoning,
                )
                for s in entry.scores
            ],
            overall_score=entry.overall_score,
            source=entry.source.value if hasattr(entry, "source") else "ideagraph",
        )
        for entry in result.ranking
    ]

    return SingleEvaluateResponse(
        evaluated_at=result.evaluated_at.isoformat(),
        model_name=result.model_name,
        ranking=ranking_response,
    )


@app.post("/api/evaluate/single")
def evaluate_proposals_single(request: SingleEvaluateRequest) -> SingleEvaluateResponse:
    """提案を単体（絶対）評価"""
    if len(request.proposals) < 1:
        raise HTTPException(
            status_code=400,
            detail="At least 1 proposal is required for single evaluation",
        )

    proposals = _convert_evaluate_proposals(request.proposals)
    service = EvaluationService()
    result = service.evaluate_single(
        proposals,
        proposal_sources=request.proposal_sources,
    )

    return _build_single_evaluate_response(result)


@app.post("/api/evaluate/single/stream")
async def evaluate_proposals_single_stream(request: SingleEvaluateRequest):
    """提案を単体（絶対）評価（SSEストリーミング版）"""
    from fastapi.responses import StreamingResponse

    from idea_graph.models.evaluation import EvaluationProgressEvent, SingleEvaluationResult

    if len(request.proposals) < 1:
        raise HTTPException(
            status_code=400,
            detail="At least 1 proposal is required for single evaluation",
        )

    proposals = _convert_evaluate_proposals(request.proposals)

    async def generate():
        service = EvaluationService()

        try:
            async for event in service.evaluate_single_streaming(
                proposals,
                proposal_sources=request.proposal_sources,
            ):
                if isinstance(event, EvaluationProgressEvent):
                    response = SingleEvaluationProgressResponse(
                        event_type=event.event_type,
                        current_evaluation=event.current_comparison,
                        total_evaluations=event.total_comparisons,
                        phase=event.phase,
                        message=event.message,
                    )
                    yield f"data: {response.model_dump_json()}\n\n"
                elif isinstance(event, SingleEvaluationResult):
                    eval_response = _build_single_evaluate_response(event)
                    response = SingleEvaluationProgressResponse(
                        event_type="completed",
                        current_evaluation=len(event.idea_results),
                        total_evaluations=len(event.idea_results),
                        phase="completed",
                        message="評価完了",
                        result=eval_response,
                    )
                    yield f"data: {response.model_dump_json()}\n\n"
        except Exception as e:
            response = SingleEvaluationProgressResponse(
                event_type="error",
                phase="error",
                error=str(e),
            )
            yield f"data: {response.model_dump_json()}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ========== CoI API ==========


class CoIRunRequest(BaseModel):
    """CoI実行リクエスト"""

    topic: str
    max_chain_length: int = 5
    min_chain_length: int = 3
    max_chain_numbers: int = 1
    improve_cnt: int = 1
    coi_main_model: str | None = None
    coi_cheap_model: str | None = None


class CoIArgsResponse(BaseModel):
    """CoI引数レスポンス"""

    topic: str
    max_chain_length: int
    min_chain_length: int
    max_chain_numbers: int
    improve_cnt: int


class CoIResultResponse(BaseModel):
    """CoI結果レスポンス"""

    idea: str
    idea_chain: str
    experiment: str
    related_experiments: list[str]
    entities: str
    trend: str
    future: str
    year: list[int]
    prompt: str | None = None
    args: CoIArgsResponse | None = None


class CoIRunResponse(BaseModel):
    """CoI実行レスポンス"""

    status: str  # running, completed, error
    progress: str
    result: CoIResultResponse | None = None
    error: str | None = None


class CoIConvertRequest(BaseModel):
    """CoI変換リクエスト"""

    coi_result: CoIResultResponse
    model_name: str | None = None


class CoIConvertResponse(BaseModel):
    """CoI変換レスポンス"""

    proposal: Proposal
    source: str = "coi"


class CoILoadRequest(BaseModel):
    """CoI結果ファイル読み込みリクエスト"""

    result_path: str


@app.post("/api/coi/run")
async def run_coi(request: CoIRunRequest):
    """CoI-Agentを実行してアイデアを生成（ストリーミング）"""
    from fastapi.responses import StreamingResponse
    import json

    from idea_graph.services.coi_runner import CoIRunner

    runner = CoIRunner(
        max_chain_length=request.max_chain_length,
        min_chain_length=request.min_chain_length,
        max_chain_numbers=request.max_chain_numbers,
        improve_cnt=request.improve_cnt,
        main_model=request.coi_main_model,
        cheap_model=request.coi_cheap_model,
    )

    async def generate():
        async for progress in runner.run_streaming(topic=request.topic):
            response = CoIRunResponse(
                status=progress.status,
                progress=progress.progress,
                error=progress.error,
            )
            if progress.result:
                args_response = None
                if progress.result.args:
                    args_response = CoIArgsResponse(
                        topic=progress.result.args.topic,
                        max_chain_length=progress.result.args.max_chain_length,
                        min_chain_length=progress.result.args.min_chain_length,
                        max_chain_numbers=progress.result.args.max_chain_numbers,
                        improve_cnt=progress.result.args.improve_cnt,
                    )
                response.result = CoIResultResponse(
                    idea=progress.result.idea,
                    idea_chain=progress.result.idea_chain,
                    experiment=progress.result.experiment,
                    related_experiments=progress.result.related_experiments,
                    entities=progress.result.entities,
                    trend=progress.result.trend,
                    future=progress.result.future,
                    year=progress.result.year,
                    prompt=progress.result.prompt or None,
                    args=args_response,
                )
            yield f"data: {response.model_dump_json()}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/coi/run/sync")
async def run_coi_sync(request: CoIRunRequest) -> CoIRunResponse:
    """CoI-Agentを実行してアイデアを生成（同期版）"""
    from idea_graph.services.coi_runner import CoIRunner

    runner = CoIRunner(
        max_chain_length=request.max_chain_length,
        min_chain_length=request.min_chain_length,
        max_chain_numbers=request.max_chain_numbers,
        improve_cnt=request.improve_cnt,
        main_model=request.coi_main_model,
        cheap_model=request.coi_cheap_model,
    )

    try:
        result = await runner.run(topic=request.topic)
        args_response = None
        if result.args:
            args_response = CoIArgsResponse(
                topic=result.args.topic,
                max_chain_length=result.args.max_chain_length,
                min_chain_length=result.args.min_chain_length,
                max_chain_numbers=result.args.max_chain_numbers,
                improve_cnt=result.args.improve_cnt,
            )
        return CoIRunResponse(
            status="completed",
            progress="完了",
            result=CoIResultResponse(
                idea=result.idea,
                idea_chain=result.idea_chain,
                experiment=result.experiment,
                related_experiments=result.related_experiments,
                entities=result.entities,
                trend=result.trend,
                future=result.future,
                year=result.year,
                prompt=result.prompt or None,
                args=args_response,
            ),
        )
    except Exception as e:
        return CoIRunResponse(
            status="error",
            progress="エラー",
            error=str(e),
        )


@app.post("/api/coi/convert")
def convert_coi_result(request: CoIConvertRequest) -> CoIConvertResponse:
    """CoI結果をProposal形式に変換"""
    from idea_graph.services.coi_runner import CoIResult
    from idea_graph.services.coi_converter import CoIConverter

    # CoIResultResponseをCoIResultに変換
    coi_result = CoIResult(
        idea=request.coi_result.idea,
        idea_chain=request.coi_result.idea_chain,
        experiment=request.coi_result.experiment,
        related_experiments=request.coi_result.related_experiments,
        entities=request.coi_result.entities,
        trend=request.coi_result.trend,
        future=request.coi_result.future,
        year=request.coi_result.year,
        prompt=request.coi_result.prompt or "",
    )

    # 変換
    converter = CoIConverter(model_name=request.model_name)
    proposal = converter.convert_to_proposal(coi_result)

    # ProposalをAPI用のProposalモデルに変換
    api_proposal = Proposal(
        title=proposal.title,
        rationale=proposal.rationale,
        research_trends=proposal.research_trends,
        motivation=proposal.motivation,
        method=proposal.method,
        experiment=Experiment(
            datasets=proposal.experiment.datasets,
            baselines=proposal.experiment.baselines,
            metrics=proposal.experiment.metrics,
            ablations=proposal.experiment.ablations,
            expected_results=proposal.experiment.expected_results,
            failure_interpretation=proposal.experiment.failure_interpretation,
        ),
        grounding=Grounding(
            papers=proposal.grounding.papers,
            entities=proposal.grounding.entities,
            path_mermaid=proposal.grounding.path_mermaid,
        ),
        differences=proposal.differences,
    )

    return CoIConvertResponse(proposal=api_proposal, source="coi")


@app.post("/api/coi/load")
def load_coi_result(request: CoILoadRequest) -> CoIResultResponse:
    """CoI結果ファイルを読み込み"""
    from idea_graph.services.coi_runner import CoIRunner

    try:
        result = CoIRunner.load_result_from_file(request.result_path)
        return CoIResultResponse(
            idea=result.idea,
            idea_chain=result.idea_chain,
            experiment=result.experiment,
            related_experiments=result.related_experiments,
            entities=result.entities,
            trend=result.trend,
            future=result.future,
            year=result.year,
            prompt=result.prompt or None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========== フロントエンド ==========


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """メインページ"""
    if templates is None:
        return HTMLResponse(content="<h1>IdeaGraph</h1><p>Templates not found</p>")
    return templates.TemplateResponse("index.html", {"request": request})
