"""Neo4j データベース接続のテスト"""

from unittest.mock import MagicMock, patch

import pytest


class TestNeo4jConnection:
    """Neo4jConnection クラスのテスト"""

    def test_get_driver_creates_singleton(self):
        """ドライバーがシングルトンとして作成されることを確認"""
        with patch("idea_graph.db.GraphDatabase.driver") as mock_driver:
            mock_driver.return_value = MagicMock()

            from idea_graph.db import Neo4jConnection

            # リセット
            Neo4jConnection._driver = None

            driver1 = Neo4jConnection.get_driver()
            driver2 = Neo4jConnection.get_driver()

            assert driver1 is driver2
            mock_driver.assert_called_once()

            # クリーンアップ
            Neo4jConnection._driver = None

    def test_close_clears_driver(self):
        """close() がドライバーをクリアすることを確認"""
        with patch("idea_graph.db.GraphDatabase.driver") as mock_driver:
            mock_instance = MagicMock()
            mock_driver.return_value = mock_instance

            from idea_graph.db import Neo4jConnection

            Neo4jConnection._driver = None
            Neo4jConnection.get_driver()
            Neo4jConnection.close()

            assert Neo4jConnection._driver is None
            mock_instance.close.assert_called_once()

    def test_verify_connectivity_success(self):
        """接続確認が成功する場合"""
        with patch("idea_graph.db.GraphDatabase.driver") as mock_driver:
            mock_instance = MagicMock()
            mock_driver.return_value = mock_instance

            from idea_graph.db import Neo4jConnection

            Neo4jConnection._driver = None
            result = Neo4jConnection.verify_connectivity()

            assert result is True
            mock_instance.verify_connectivity.assert_called_once()

            Neo4jConnection._driver = None

    def test_verify_connectivity_failure(self):
        """接続確認が失敗する場合"""
        with patch("idea_graph.db.GraphDatabase.driver") as mock_driver:
            mock_instance = MagicMock()
            mock_instance.verify_connectivity.side_effect = Exception("Connection failed")
            mock_driver.return_value = mock_instance

            from idea_graph.db import Neo4jConnection

            Neo4jConnection._driver = None
            result = Neo4jConnection.verify_connectivity()

            assert result is False

            Neo4jConnection._driver = None

    def test_session_context_manager(self):
        """session() がコンテキストマネージャとして機能することを確認"""
        with patch("idea_graph.db.GraphDatabase.driver") as mock_driver:
            mock_instance = MagicMock()
            mock_session = MagicMock()
            mock_instance.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_instance.session.return_value.__exit__ = MagicMock(return_value=False)
            mock_driver.return_value = mock_instance

            from idea_graph.db import Neo4jConnection

            Neo4jConnection._driver = None

            with Neo4jConnection.session() as session:
                assert session is mock_session

            Neo4jConnection._driver = None

    def test_ensure_indexes_creates_constraints_and_indexes(self):
        """ensure_indexes() が必要な制約とインデックスを作成することを確認"""
        with patch("idea_graph.db.GraphDatabase.driver") as mock_driver:
            mock_instance = MagicMock()
            mock_session = MagicMock()
            mock_instance.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_instance.session.return_value.__exit__ = MagicMock(return_value=False)
            mock_driver.return_value = mock_instance

            from idea_graph.db import Neo4jConnection

            Neo4jConnection._driver = None
            Neo4jConnection.ensure_indexes()

            # 5つのクエリが実行されることを確認
            assert mock_session.run.call_count == 5

            # 実行されたクエリを検証
            calls = [call[0][0] for call in mock_session.run.call_args_list]

            assert any("paper_id" in call and "CONSTRAINT" in call for call in calls)
            assert any("entity_id" in call and "CONSTRAINT" in call for call in calls)
            assert any("paper_title" in call and "INDEX" in call for call in calls)
            assert any("entity_name" in call and "INDEX" in call for call in calls)
            assert any("entity_type" in call and "INDEX" in call for call in calls)

            Neo4jConnection._driver = None
