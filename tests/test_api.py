"""API エンドポイントのテスト"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestHealthCheck:
    """ヘルスチェックのテスト"""

    def test_health_check_connected(self):
        """Neo4j 接続時のヘルスチェック"""
        with patch("idea_graph.api.app.Neo4jConnection") as mock_conn:
            mock_conn.verify_connectivity.return_value = True

            from idea_graph.api.app import app

            client = TestClient(app)
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["neo4j"] == "connected"

    def test_health_check_disconnected(self):
        """Neo4j 未接続時のヘルスチェック"""
        with patch("idea_graph.api.app.Neo4jConnection") as mock_conn:
            mock_conn.verify_connectivity.return_value = False

            from idea_graph.api.app import app

            client = TestClient(app)
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["neo4j"] == "disconnected"


class TestVisualizationAPI:
    """可視化 API のテスト"""

    def test_get_config(self):
        """可視化設定の取得"""
        from idea_graph.api.app import app

        client = TestClient(app)
        response = client.get("/api/visualization/config")

        assert response.status_code == 200
        data = response.json()
        assert "neo4j_uri" in data
        assert "user" in data
        assert "initial_cypher" in data
        assert "styling" in data

    def test_query_blocks_write_operations(self):
        """書き込みクエリがブロックされること"""
        from idea_graph.api.app import app

        client = TestClient(app)

        # CREATE
        response = client.post(
            "/api/visualization/query",
            json={"cypher": "CREATE (n:Test) RETURN n"},
        )
        assert response.status_code == 400

        # DELETE
        response = client.post(
            "/api/visualization/query",
            json={"cypher": "MATCH (n) DELETE n"},
        )
        assert response.status_code == 400

        # MERGE
        response = client.post(
            "/api/visualization/query",
            json={"cypher": "MERGE (n:Test) RETURN n"},
        )
        assert response.status_code == 400


class TestAnalyzeAPI:
    """分析 API のテスト"""

    def test_analyze_paper_not_found(self):
        """論文が見つからない場合"""
        with patch("idea_graph.services.analysis.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()
            mock_session.run.return_value.single.return_value = None
            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            from idea_graph.api.app import app

            client = TestClient(app)
            response = client.post(
                "/api/analyze",
                json={
                    "target_paper_id": "nonexistent",
                    "multihop_k": 3,
                    "top_n": 10,
                },
            )

            assert response.status_code == 404

    def test_analyze_valid_request(self):
        """有効なリクエスト"""
        with patch("idea_graph.services.analysis.Neo4jConnection") as mock_conn:
            mock_session = MagicMock()

            # 論文存在確認
            mock_session.run.return_value.single.return_value = {"p": MagicMock()}

            mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_conn.session.return_value.__exit__ = MagicMock(return_value=False)

            from idea_graph.api.app import app

            client = TestClient(app)
            response = client.post(
                "/api/analyze",
                json={
                    "target_paper_id": "test_paper",
                    "multihop_k": 2,
                    "top_n": 5,
                },
            )

            # 論文が見つかればエラーにはならない（空の結果は OK）
            assert response.status_code in [200, 404]


class TestProposeAPI:
    """提案 API のテスト"""

    def test_propose_empty_analysis(self):
        """分析結果が空の場合"""
        from idea_graph.api.app import app

        client = TestClient(app)
        response = client.post(
            "/api/propose",
            json={
                "target_paper_id": "test_paper",
                "analysis_result": {
                    "target_paper_id": "test_paper",
                    "candidates": [],
                    "multihop_k": 3,
                },
                "num_proposals": 3,
            },
        )

        assert response.status_code == 400
        assert "no candidates" in response.json()["detail"].lower()


class TestEvaluateAPI:
    """評価 API のテスト"""

    def test_evaluate_empty_proposals(self):
        """提案が空の場合"""
        from idea_graph.api.app import app

        client = TestClient(app)
        response = client.post(
            "/api/evaluate",
            json={
                "proposals": [],
            },
        )

        assert response.status_code == 400
        assert "at least 2 proposals" in response.json()["detail"].lower()

    def test_evaluate_single_proposal(self):
        """提案が1つだけの場合"""
        from idea_graph.api.app import app

        client = TestClient(app)
        response = client.post(
            "/api/evaluate",
            json={
                "proposals": [
                    {
                        "title": "Single Idea",
                        "rationale": "R",
                        "research_trends": "T",
                        "motivation": "M",
                        "method": "Method description",
                        "experiment": {
                            "datasets": ["d"],
                            "baselines": ["b"],
                            "metrics": ["m"],
                            "ablations": ["a"],
                            "expected_results": "e",
                            "failure_interpretation": "f",
                        },
                        "grounding": {
                            "papers": ["p"],
                            "entities": ["e"],
                            "path_mermaid": "g",
                        },
                        "differences": ["d"],
                    }
                ],
            },
        )

        assert response.status_code == 400
        assert "at least 2 proposals" in response.json()["detail"].lower()

    def test_evaluate_valid_request(self):
        """有効なリクエスト（モック使用）"""
        from datetime import datetime
        from idea_graph.models.evaluation import (
            EvaluationResult,
            EloRatings,
            RankingEntry,
            EvaluationMetric,
        )

        mock_result = EvaluationResult(
            evaluated_at=datetime(2026, 1, 18, 12, 0, 0),
            model_name="gpt-4o-mini",
            proposals=[],
            pairwise_results=[],
            elo_ratings=EloRatings(
                ratings_by_metric={},
                overall_ratings={"idea_0": 1016.0, "idea_1": 984.0},
            ),
            ranking=[
                RankingEntry(
                    rank=1,
                    idea_id="idea_0",
                    idea_title="Idea A",
                    overall_score=1016.0,
                    scores_by_metric={EvaluationMetric.NOVELTY: 1016.0},
                ),
                RankingEntry(
                    rank=2,
                    idea_id="idea_1",
                    idea_title="Idea B",
                    overall_score=984.0,
                    scores_by_metric={EvaluationMetric.NOVELTY: 984.0},
                ),
            ],
        )

        with patch("idea_graph.api.app.EvaluationService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.evaluate.return_value = mock_result
            mock_service_class.return_value = mock_service

            from idea_graph.api.app import app

            client = TestClient(app)
            response = client.post(
                "/api/evaluate",
                json={
                    "proposals": [
                        {
                            "title": "Idea A",
                            "rationale": "R",
                            "research_trends": "T",
                            "motivation": "M",
                            "method": "Method A",
                            "experiment": {
                                "datasets": ["d"],
                                "baselines": ["b"],
                                "metrics": ["m"],
                                "ablations": ["a"],
                                "expected_results": "e",
                                "failure_interpretation": "f",
                            },
                            "grounding": {
                                "papers": ["p"],
                                "entities": ["e"],
                                "path_mermaid": "g",
                            },
                            "differences": ["d"],
                        },
                        {
                            "title": "Idea B",
                            "rationale": "R",
                            "research_trends": "T",
                            "motivation": "M",
                            "method": "Method B",
                            "experiment": {
                                "datasets": ["d"],
                                "baselines": ["b"],
                                "metrics": ["m"],
                                "ablations": ["a"],
                                "expected_results": "e",
                                "failure_interpretation": "f",
                            },
                            "grounding": {
                                "papers": ["p"],
                                "entities": ["e"],
                                "path_mermaid": "g",
                            },
                            "differences": ["d"],
                        },
                    ],
                    "include_experiment": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert "ranking" in data
            assert len(data["ranking"]) == 2
            assert data["ranking"][0]["rank"] == 1
            assert data["ranking"][0]["idea_title"] == "Idea A"

    def test_evaluate_with_model_option(self):
        """モデル指定オプション"""
        from datetime import datetime
        from idea_graph.models.evaluation import (
            EvaluationResult,
            EloRatings,
            RankingEntry,
            EvaluationMetric,
        )

        mock_result = EvaluationResult(
            evaluated_at=datetime(2026, 1, 18, 12, 0, 0),
            model_name="gpt-4o",
            proposals=[],
            pairwise_results=[],
            elo_ratings=EloRatings(
                ratings_by_metric={},
                overall_ratings={"idea_0": 1000.0, "idea_1": 1000.0},
            ),
            ranking=[
                RankingEntry(
                    rank=1,
                    idea_id="idea_0",
                    idea_title="A",
                    overall_score=1000.0,
                    scores_by_metric={},
                ),
                RankingEntry(
                    rank=2,
                    idea_id="idea_1",
                    idea_title="B",
                    overall_score=1000.0,
                    scores_by_metric={},
                ),
            ],
        )

        with patch("idea_graph.api.app.EvaluationService") as mock_service_class:
            mock_service = MagicMock()
            mock_service.evaluate.return_value = mock_result
            mock_service_class.return_value = mock_service

            from idea_graph.api.app import app

            client = TestClient(app)
            response = client.post(
                "/api/evaluate",
                json={
                    "proposals": [
                        {
                            "title": "A",
                            "rationale": "R",
                            "research_trends": "T",
                            "motivation": "M",
                            "method": "M",
                            "experiment": {
                                "datasets": ["d"],
                                "baselines": ["b"],
                                "metrics": ["m"],
                                "ablations": ["a"],
                                "expected_results": "e",
                                "failure_interpretation": "f",
                            },
                            "grounding": {"papers": ["p"], "entities": ["e"], "path_mermaid": "g"},
                            "differences": ["d"],
                        },
                        {
                            "title": "B",
                            "rationale": "R",
                            "research_trends": "T",
                            "motivation": "M",
                            "method": "M",
                            "experiment": {
                                "datasets": ["d"],
                                "baselines": ["b"],
                                "metrics": ["m"],
                                "ablations": ["a"],
                                "expected_results": "e",
                                "failure_interpretation": "f",
                            },
                            "grounding": {"papers": ["p"], "entities": ["e"], "path_mermaid": "g"},
                            "differences": ["d"],
                        },
                    ],
                    "model_name": "gpt-4o",
                },
            )

            assert response.status_code == 200
            # EvaluationService が指定されたモデル名で初期化されることを確認
            mock_service_class.assert_called_once_with(model_name="gpt-4o")
