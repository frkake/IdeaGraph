"""CLI エントリーポイント"""

import argparse
import logging
import sys
from typing import NoReturn

from tqdm import tqdm

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection


def setup_logging(verbose: bool = False) -> None:
    """ロギングの設定"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    """インジェストコマンド"""
    from idea_graph.ingestion import (
        DatasetLoaderService,
        DownloaderService,
        ExtractorService,
        GraphWriterService,
        CitationCrawler,
    )
    from idea_graph.ingestion.progress import ProgressManager

    logging.info("Starting ingestion pipeline...")

    # 設定の確認
    settings.ensure_cache_dirs()

    # サービスの初期化
    loader = DatasetLoaderService()
    downloader = DownloaderService()
    extractor = ExtractorService()
    writer = GraphWriterService()
    progress = ProgressManager()

    # インデックスの作成
    logging.info("Ensuring Neo4j indexes...")
    try:
        writer.ensure_indexes()
    except Exception as e:
        logging.error(f"Failed to create indexes: {e}")
        logging.error("Make sure Neo4j is running (docker compose up -d)")
        return 1

    # データセットの読み込み
    logging.info("Loading dataset...")
    papers = list(loader.load())
    progress.set_total(len(papers))
    logging.info(f"Found {len(papers)} papers")

    # 制限がある場合
    if args.limit:
        papers = papers[: args.limit]
        logging.info(f"Limited to {args.limit} papers")

    # 完了済みをスキップ
    completed = progress.get_completed_papers()
    papers_to_process = [p for p in papers if p.paper_id not in completed]
    logging.info(f"Skipping {len(completed)} already processed papers")
    logging.info(f"Processing {len(papers_to_process)} papers")

    # Paper ノードを作成
    if not args.skip_write:
        logging.info("Writing Paper nodes...")
        writer.write_papers(papers)

        # 引用関係を作成
        logging.info("Writing citation relationships...")
        citations = []
        for paper in papers:
            for ref_title in paper.references:
                # 参照論文のIDを生成
                from idea_graph.ingestion.dataset_loader import generate_paper_id

                ref_id = generate_paper_id(ref_title)
                citations.append((paper.paper_id, ref_id, ref_title))
        writer.write_citations(citations)

    # 各論文を処理
    extractions = []
    for paper in tqdm(papers_to_process, desc="Processing papers"):
        progress.register_paper(paper.paper_id, paper.title)

        if args.skip_download:
            continue

        # ダウンロード
        progress.update_status(paper.paper_id, "downloading")
        result = downloader.download(paper.paper_id, paper.title)

        if not result.success:
            progress.update_status(paper.paper_id, "failed", result.error_message)
            continue

        if args.skip_extract:
            progress.update_status(paper.paper_id, "completed")
            continue

        # 抽出
        progress.update_status(paper.paper_id, "extracting")
        extracted = extractor.extract(paper.paper_id, result.file_path, result.file_type)

        if extracted is None:
            progress.update_status(paper.paper_id, "failed", "Extraction failed")
            continue

        extractions.append(extracted)
        progress.update_status(paper.paper_id, "completed")

    # 抽出結果をグラフに書き込み
    if extractions and not args.skip_write:
        logging.info(f"Writing {len(extractions)} extractions to graph...")
        writer.write_extracted(extractions)

    # 引用論文のクロール（max_depth > 0 の場合）
    if args.max_depth > 0 and not args.skip_download:
        logging.info(f"Starting citation crawl (max_depth={args.max_depth})...")
        crawler = CitationCrawler(
            downloader=downloader,
            extractor=extractor,
            writer=writer,
            progress=progress,
            max_depth=args.max_depth,
            crawl_limit=args.crawl_limit,
        )
        crawler.add_seeds(papers)

        crawl_stats = {"completed": 0, "failed": 0, "not_found": 0, "skipped": 0}
        for result in tqdm(crawler.crawl(), desc="Crawling citations"):
            crawl_stats[result.status] = crawl_stats.get(result.status, 0) + 1

        logging.info(f"Crawl completed: {crawl_stats}")

    # サマリー
    summary = progress.get_summary()
    logging.info(f"Completed: {summary['processed']}/{summary['total']}")
    logging.info(f"Failed: {summary['failed']}")
    logging.info(f"Pending: {summary['pending']}")

    return 0


def cmd_serve(args: argparse.Namespace) -> NoReturn:
    """Web サーバーを起動"""
    import uvicorn

    logging.info(f"Starting server on {args.host}:{args.port}")
    uvicorn.run(
        "idea_graph.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def cmd_status(args: argparse.Namespace) -> int:
    """ステータスを表示"""
    from idea_graph.ingestion.progress import ProgressManager

    progress = ProgressManager()
    summary = progress.get_summary()

    print("=== IdeaGraph Status ===")
    print(f"Total papers: {summary['total']}")
    print(f"Processed: {summary['processed']}")
    print(f"Failed: {summary['failed']}")
    print(f"Pending: {summary['pending']}")
    print(f"Last updated: {summary['last_updated']}")

    # Neo4j 接続確認
    print("\n=== Neo4j Connection ===")
    if Neo4jConnection.verify_connectivity():
        print("Status: Connected")

        with Neo4jConnection.session() as session:
            result = session.run("MATCH (n) RETURN labels(n) AS labels, count(*) AS count")
            print("\nNode counts:")
            for record in result:
                print(f"  {record['labels']}: {record['count']}")

            result = session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count")
            print("\nRelationship counts:")
            for record in result:
                print(f"  {record['type']}: {record['count']}")
    else:
        print("Status: Disconnected")
        print("Run: docker compose up -d")

    return 0


def main() -> int:
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="IdeaGraph - AI論文ナレッジグラフツール",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログを表示")

    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # ingest コマンド
    ingest_parser = subparsers.add_parser("ingest", help="論文データをインジェスト")
    ingest_parser.add_argument("--limit", type=int, help="処理する論文数の制限")
    ingest_parser.add_argument("--skip-download", action="store_true", help="ダウンロードをスキップ")
    ingest_parser.add_argument("--skip-extract", action="store_true", help="抽出をスキップ")
    ingest_parser.add_argument("--skip-write", action="store_true", help="グラフ書き込みをスキップ")
    ingest_parser.add_argument(
        "--max-depth",
        type=int,
        default=1,
        help="引用論文の再帰的探索の最大深度 (0=メイン論文のみ, 1=直接引用)",
    )
    ingest_parser.add_argument(
        "--crawl-limit",
        type=int,
        default=None,
        help="クロールする引用論文の最大数",
    )

    # serve コマンド
    serve_parser = subparsers.add_parser("serve", help="Web サーバーを起動")
    serve_parser.add_argument("--host", default="0.0.0.0", help="ホスト")
    serve_parser.add_argument("--port", type=int, default=8000, help="ポート")
    serve_parser.add_argument("--reload", action="store_true", help="自動リロード")

    # status コマンド
    subparsers.add_parser("status", help="ステータスを表示")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "ingest":
        return cmd_ingest(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "status":
        return cmd_status(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
