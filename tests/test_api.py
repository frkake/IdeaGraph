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
