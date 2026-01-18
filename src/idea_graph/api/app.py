"""FastAPI アプリケーション"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.services.evaluation import EvaluationService

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


class PathNode(BaseModel):
    """パスノード"""

    id: str
    label: str
    name: str


class PathEdge(BaseModel):
    """パスエッジ"""

    type: str


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
    multihop_k: int


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
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== 提案 API ==========


class ProposeRequest(BaseModel):
    """提案リクエスト"""

    target_paper_id: str
    analysis_result: AnalysisResult
    num_proposals: int = 3
    constraints: dict | None = None


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
    from idea_graph.services.proposal import ProposalService

    service = ProposalService()
    try:
        result = service.propose(
            target_paper_id=request.target_paper_id,
            analysis_result=request.analysis_result,
            num_proposals=request.num_proposals,
            constraints=request.constraints,
        )
        return result
    except ValueError as e:
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
def get_saved_analysis(analysis_id: str):
    """保存された分析結果を取得"""
    from idea_graph.services.storage import StorageService

    service = StorageService()
    analysis = service.load_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


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
    include_experiment: bool = True
    model_name: str | None = None


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

    # バリデーション
    if len(request.proposals) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least 2 proposals are required for pairwise comparison"
        )

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
    service = EvaluationService(model_name=request.model_name)
    result = service.evaluate(proposals, include_experiment=request.include_experiment)

    # レスポンスを構築
    ranking_response = [
        RankingEntryResponse(
            rank=entry.rank,
            idea_id=entry.idea_id,
            idea_title=entry.idea_title,
            overall_score=entry.overall_score,
            scores_by_metric={m.value: s for m, s in entry.scores_by_metric.items()},
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


# ========== フロントエンド ==========


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """メインページ"""
    if templates is None:
        return HTMLResponse(content="<h1>IdeaGraph</h1><p>Templates not found</p>")
    return templates.TemplateResponse("index.html", {"request": request})
