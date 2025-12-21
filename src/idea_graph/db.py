"""Neo4j データベース接続管理"""

from contextlib import contextmanager
from typing import Generator

from neo4j import GraphDatabase, Driver, Session

from idea_graph.config import settings


class Neo4jConnection:
    """Neo4j 接続管理クラス"""

    _driver: Driver | None = None

    @classmethod
    def get_driver(cls) -> Driver:
        """ドライバーを取得（シングルトン）"""
        if cls._driver is None:
            cls._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return cls._driver

    @classmethod
    def close(cls) -> None:
        """接続を閉じる"""
        if cls._driver is not None:
            cls._driver.close()
            cls._driver = None

    @classmethod
    @contextmanager
    def session(cls) -> Generator[Session, None, None]:
        """セッションをコンテキストマネージャとして提供"""
        driver = cls.get_driver()
        with driver.session() as session:
            yield session

    @classmethod
    def verify_connectivity(cls) -> bool:
        """接続を確認"""
        try:
            driver = cls.get_driver()
            driver.verify_connectivity()
            return True
        except Exception:
            return False

    @classmethod
    def ensure_indexes(cls) -> None:
        """必要なインデックスと制約を作成"""
        with cls.session() as session:
            # Paper ノードの一意制約
            session.run(
                "CREATE CONSTRAINT paper_id IF NOT EXISTS "
                "FOR (p:Paper) REQUIRE p.id IS UNIQUE"
            )

            # Entity ノードの一意制約
            session.run(
                "CREATE CONSTRAINT entity_id IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.id IS UNIQUE"
            )

            # Paper タイトル検索用インデックス
            session.run(
                "CREATE INDEX paper_title IF NOT EXISTS "
                "FOR (p:Paper) ON (p.title)"
            )

            # Entity 名前検索用インデックス
            session.run(
                "CREATE INDEX entity_name IF NOT EXISTS "
                "FOR (e:Entity) ON (e.name)"
            )

            # Entity タイプ検索用インデックス
            session.run(
                "CREATE INDEX entity_type IF NOT EXISTS "
                "FOR (e:Entity) ON (e.type)"
            )
