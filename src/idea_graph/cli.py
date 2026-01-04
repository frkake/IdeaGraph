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


def _print_analysis_json(result: "AnalysisResult") -> None:
    """分析結果をJSON形式で出力"""
    print(result.model_dump_json(indent=2))


def _print_path(path, index: int) -> None:
    """単一パスを表示"""
    print(f"{'=' * 70}")
    print(f"Path {index} (Score: {path.score:.1f})")
    print(f"{'=' * 70}")

    # ノードパスを表示（詳細エッジ情報付き）
    for j, node in enumerate(path.nodes):
        if node.label == "Paper":
            node_label = "[Paper]"
            node_display = node.name[:55]
        else:
            # Entity ノード
            entity_type = node.entity_type or "Entity"
            node_label = f"[{entity_type}]"
            node_display = node.name[:45]
            if node.description:
                node_display += f"\n          {node.description[:60]}..."

        print(f"  {node_label} {node_display}")

        if j < len(path.edges):
            edge = path.edges[j]
            edge_info = f"    ↓ --[{edge.type}]--"

            # CITES関係の詳細情報を追加
            if edge.type == "CITES":
                details = []
                if edge.importance_score is not None:
                    details.append(f"重要度:{edge.importance_score}/5")
                if edge.citation_type:
                    details.append(f"種別:{edge.citation_type}")
                if details:
                    edge_info += f" ({', '.join(details)})"

            print(edge_info)

            # コンテキストを表示
            if edge.context:
                context_lines = edge.context.split(". ")
                for line in context_lines[:2]:  # 最大2文まで
                    if line.strip():
                        print(f"       > {line.strip()[:65]}...")

    # スコア内訳
    if path.score_breakdown:
        print(f"\n  Score breakdown:")
        bd = path.score_breakdown

        # Paper引用関連
        cite_score = bd.get('cite_importance_score', 0) + bd.get('cite_type_score', 0)
        if cite_score > 0:
            print(f"    [Paper引用] {cite_score:.1f}")
            if bd.get('cite_extends', 0) > 0:
                print(f"      └ CITES(EXTENDS): {int(bd.get('cite_extends', 0))}件")
            if bd.get('cite_compares', 0) > 0:
                print(f"      └ CITES(COMPARES): {int(bd.get('cite_compares', 0))}件")
            if bd.get('cite_uses', 0) > 0:
                print(f"      └ CITES(USES): {int(bd.get('cite_uses', 0))}件")

        # Entity関連
        entity_score = bd.get('mentions_score', 0) + bd.get('entity_relation_score', 0)
        if entity_score > 0 or bd.get('entity_count', 0) > 0:
            print(f"    [Entity関連] {entity_score:.1f} (Entityノード数: {int(bd.get('entity_count', 0))})")
            if bd.get('mentions_score', 0) > 0:
                print(f"      └ MENTIONS: {bd.get('mentions_score', 0):.1f}")
            if bd.get('entity_uses', 0) > 0:
                print(f"      └ USES: {int(bd.get('entity_uses', 0))}件")
            if bd.get('entity_extends', 0) > 0:
                print(f"      └ EXTENDS: {int(bd.get('entity_extends', 0))}件")
            if bd.get('enables', 0) > 0:
                print(f"      └ ENABLES: {int(bd.get('enables', 0))}件")
            if bd.get('improves', 0) > 0:
                print(f"      └ IMPROVES: {int(bd.get('improves', 0))}件")

        print(f"    [距離ペナルティ] {bd.get('length_penalty', 0):.1f}")
    print()


def _print_analysis_table(result: "AnalysisResult") -> None:
    """分析結果をテーブル形式で出力"""
    print(f"\n=== Analysis Results for {result.target_paper_id} ===")
    print(f"Max hops: {result.multihop_k}")

    paper_count = len(result.paper_paths) if result.paper_paths else 0
    entity_count = len(result.entity_paths) if result.entity_paths else 0
    print(f"Found {paper_count} paper paths, {entity_count} entity paths\n")

    # Paper引用パスを表示
    if result.paper_paths:
        print(f"\n{'#' * 70}")
        print(f"# Paper引用パス ({len(result.paper_paths)}件)")
        print(f"{'#' * 70}")
        for i, path in enumerate(result.paper_paths, 1):
            _print_path(path, i)

    # Entity関連パスを表示
    if result.entity_paths:
        print(f"\n{'#' * 70}")
        print(f"# Entity関連パス ({len(result.entity_paths)}件)")
        print(f"{'#' * 70}")
        for i, path in enumerate(result.entity_paths, 1):
            _print_path(path, i)

    if not result.paper_paths and not result.entity_paths:
        print("No paths found.")


def _format_proposals_markdown(result: "ProposalResult") -> str:
    """提案結果をMarkdown形式でフォーマット"""
    lines = [
        f"# Research Proposals for {result.target_paper_id}",
        "",
        f"Generated {len(result.proposals)} proposals.",
        "",
    ]

    for i, proposal in enumerate(result.proposals, 1):
        lines.extend([
            f"## Proposal {i}: {proposal.title}",
            "",
            "### Motivation",
            proposal.motivation,
            "",
            "### Method",
            proposal.method,
            "",
            "### Experiment Plan",
            "",
            "**Datasets:**",
            *[f"- {ds}" for ds in proposal.experiment.datasets],
            "",
            "**Baselines:**",
            *[f"- {bl}" for bl in proposal.experiment.baselines],
            "",
            "**Metrics:**",
            *[f"- {m}" for m in proposal.experiment.metrics],
            "",
            "**Ablation Studies:**",
            *[f"- {ab}" for ab in proposal.experiment.ablations],
            "",
            "**Expected Results:**",
            proposal.experiment.expected_results,
            "",
            "**Failure Interpretation:**",
            proposal.experiment.failure_interpretation,
            "",
            "### Grounding",
            "",
            "**Related Papers:**",
            *[f"- {p}" for p in proposal.grounding.papers],
            "",
            "**Related Entities:**",
            *[f"- {e}" for e in proposal.grounding.entities],
            "",
            "**Knowledge Graph Path:**",
            "```mermaid",
            proposal.grounding.path_mermaid,
            "```",
            "",
            "### Key Differences from Existing Work",
            *[f"- {d}" for d in proposal.differences],
            "",
            "---",
            "",
        ])

    return "\n".join(lines)


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
    logging.info("Writing Paper nodes...")
    writer.write_papers(papers)

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
    if extractions:
        logging.info(f"Writing {len(extractions)} extractions to graph...")
        writer.write_extracted(extractions)

    # 引用論文のクロール（max_depth > 0 の場合）
    if args.max_depth > 0 and not args.skip_download:
        logging.info(
            f"Starting citation crawl (max_depth={args.max_depth}, "
            f"top_n_citations={args.top_n_citations})..."
        )
        crawler = CitationCrawler(
            downloader=downloader,
            extractor=extractor,
            writer=writer,
            progress=progress,
            max_depth=args.max_depth,
            crawl_limit=args.crawl_limit,
            top_n_citations=args.top_n_citations,
        )
        crawler.add_seeds(papers)

        total_estimate = crawler.get_total_estimate()
        crawl_stats = {"completed": 0, "failed": 0, "not_found": 0, "skipped": 0}
        with tqdm(total=total_estimate, desc="Crawling citations") as pbar:
            for result in crawler.crawl():
                crawl_stats[result.status] = crawl_stats.get(result.status, 0) + 1
                pbar.update(1)

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


def cmd_analyze(args: argparse.Namespace) -> int:
    """分析コマンド"""
    from idea_graph.services.analysis import AnalysisService

    # Neo4j接続確認
    if not Neo4jConnection.verify_connectivity():
        logging.error("Neo4j is not connected. Run: docker compose up -d")
        return 1

    logging.info(f"Analyzing paper: {args.paper_id}")
    logging.info(f"Max hops: {args.max_hops}, Top K: {args.top_k}")

    service = AnalysisService()

    try:
        result = service.analyze(
            target_paper_id=args.paper_id,
            multihop_k=args.max_hops,
            top_n=args.top_k,
        )
    except ValueError as e:
        logging.error(str(e))
        return 1

    # 結果表示
    if args.format == "json":
        _print_analysis_json(result)
    else:
        _print_analysis_table(result)

    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    """提案コマンド"""
    from idea_graph.services.analysis import AnalysisService
    from idea_graph.services.proposal import ProposalService

    # Neo4j接続確認
    if not Neo4jConnection.verify_connectivity():
        logging.error("Neo4j is not connected. Run: docker compose up -d")
        return 1

    # APIキー確認
    if not settings.google_api_key:
        logging.error("GOOGLE_API_KEY is not set. Please set it in .env file.")
        return 1

    logging.info(f"Generating proposals for paper: {args.paper_id}")

    # Step 1: 分析を実行
    logging.info("Running analysis...")
    analysis_service = AnalysisService()

    try:
        analysis_result = analysis_service.analyze(
            target_paper_id=args.paper_id,
            multihop_k=args.max_hops,
            top_n=args.top_k,
        )
    except ValueError as e:
        logging.error(str(e))
        return 1

    if not analysis_result.candidates:
        logging.error("No analysis candidates found. Cannot generate proposals.")
        return 1

    logging.info(f"Found {len(analysis_result.candidates)} paths")

    # Step 2: 提案を生成
    logging.info(f"Generating {args.num_proposals} proposals...")
    proposal_service = ProposalService()

    try:
        proposal_result = proposal_service.propose(
            target_paper_id=args.paper_id,
            analysis_result=analysis_result,
            num_proposals=args.num_proposals,
        )
    except ValueError as e:
        logging.error(str(e))
        return 1
    except Exception as e:
        logging.error(f"Proposal generation failed: {e}")
        return 1

    # Step 3: 結果出力
    if args.format == "json":
        output = proposal_result.model_dump_json(indent=2)
    else:
        output = _format_proposals_markdown(proposal_result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        logging.info(f"Output written to: {args.output}")
    else:
        print(output)

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
    ingest_parser.add_argument(
        "--top-n-citations",
        type=int,
        default=5,
        help="各論文から探索する引用の最大数（重要度上位N件）",
    )

    # serve コマンド
    serve_parser = subparsers.add_parser("serve", help="Web サーバーを起動")
    serve_parser.add_argument("--host", default="0.0.0.0", help="ホスト")
    serve_parser.add_argument("--port", type=int, default=8000, help="ポート")
    serve_parser.add_argument("--reload", action="store_true", help="自動リロード")

    # status コマンド
    subparsers.add_parser("status", help="ステータスを表示")

    # analyze コマンド
    analyze_parser = subparsers.add_parser("analyze", help="論文のマルチホップ分析を実行")
    analyze_parser.add_argument("paper_id", type=str, help="ターゲット論文のID")
    analyze_parser.add_argument(
        "--max-hops",
        type=int,
        default=3,
        help="最大ホップ数 (デフォルト: 3)",
    )
    analyze_parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="返すパス数 (デフォルト: 10)",
    )
    analyze_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="出力形式 (デフォルト: table)",
    )

    # propose コマンド
    propose_parser = subparsers.add_parser("propose", help="研究アイデアを提案")
    propose_parser.add_argument("paper_id", type=str, help="ターゲット論文のID")
    propose_parser.add_argument(
        "--num-proposals",
        type=int,
        default=3,
        help="生成する提案数 (デフォルト: 3)",
    )
    propose_parser.add_argument(
        "--max-hops",
        type=int,
        default=3,
        help="分析時の最大ホップ数 (デフォルト: 3)",
    )
    propose_parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="分析時に使用するパス数 (デフォルト: 10)",
    )
    propose_parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="出力形式 (デフォルト: markdown)",
    )
    propose_parser.add_argument(
        "-o", "--output",
        type=str,
        help="出力ファイルパス（指定しない場合は標準出力）",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "ingest":
        return cmd_ingest(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "analyze":
        return cmd_analyze(args)
    elif args.command == "propose":
        return cmd_propose(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
