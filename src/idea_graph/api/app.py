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
    motivation: str
    method: str
    experiment: Experiment
    grounding: Grounding
    differences: list[str]


class ProposalResult(BaseModel):
    """提案結果"""

    target_paper_id: str
    proposals: list[Proposal]


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


# ========== フロントエンド ==========


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """メインページ"""
    if templates is None:
        return HTMLResponse(content="<h1>IdeaGraph</h1><p>Templates not found</p>")
    return templates.TemplateResponse("index.html", {"request": request})
