"""CLI エントリーポイント"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import NoReturn, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from pydantic import ValidationError

from idea_graph.config import settings
from idea_graph.db import Neo4jConnection
from idea_graph.services.prompt_context import PromptExpansionOptions

console = Console()

if TYPE_CHECKING:
    from idea_graph.services.analysis import AnalysisResult
    from idea_graph.services.proposal import ProposalResult


def setup_logging(verbose: bool = False) -> None:
    """ロギングの設定"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _parse_prompt_type_fields(raw: str | None) -> dict[str, list[str]] | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("prompt type fields must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("prompt type fields must be a JSON object")
    normalized: dict[str, list[str]] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("prompt type field keys must be non-empty strings")
        if not isinstance(value, list):
            raise ValueError(f"prompt type fields for {key} must be a list")
        items = [str(item).strip() for item in value if str(item).strip()]
        normalized[key] = items
    return normalized


def _build_prompt_options(args: argparse.Namespace) -> dict:
    options = {
        "graph_format": args.prompt_graph_format,
        "scope": args.prompt_scope,
        "include_inline_edges": args.prompt_inline_edges,
        "include_target_paper": args.prompt_include_target_paper,
        "exclude_future_papers": args.prompt_exclude_future_papers,
    }
    if args.prompt_max_paths is not None:
        options["max_paths"] = args.prompt_max_paths
    if args.prompt_max_nodes is not None:
        options["max_nodes"] = args.prompt_max_nodes
    if args.prompt_max_edges is not None:
        options["max_edges"] = args.prompt_max_edges
    if args.prompt_neighbor_k is not None:
        options["neighbor_k"] = args.prompt_neighbor_k
    node_type_fields = _parse_prompt_type_fields(args.prompt_node_type_fields)
    if node_type_fields is not None:
        options["node_type_fields"] = node_type_fields
    edge_type_fields = _parse_prompt_type_fields(args.prompt_edge_type_fields)
    if edge_type_fields is not None:
        options["edge_type_fields"] = edge_type_fields

    try:
        PromptExpansionOptions(**options)
    except ValidationError as exc:
        raise ValueError(f"Invalid prompt options: {exc}") from exc

    return options


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
    total_paper = result.total_paper_paths
    total_entity = result.total_entity_paths
    paper_label = f"{paper_count}"
    entity_label = f"{entity_count}"
    if total_paper is not None:
        paper_label = f"{paper_count}/{total_paper}"
    if total_entity is not None:
        entity_label = f"{entity_count}/{total_entity}"
    print(f"Found {paper_label} paper paths, {entity_label} entity paths\n")

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


def _print_analysis_rich(result: "AnalysisResult") -> None:
    """分析結果をrich形式で出力"""
    # ヘッダー
    console.print()
    console.print(Panel(
        f"[bold blue]論文ID:[/] {result.target_paper_id}\n"
        f"[bold blue]最大ホップ:[/] {result.multihop_k}",
        title="[bold]分析結果[/]",
        border_style="blue"
    ))

    paper_count = len(result.paper_paths) if result.paper_paths else 0
    entity_count = len(result.entity_paths) if result.entity_paths else 0
    total_paper = result.total_paper_paths
    total_entity = result.total_entity_paths
    paper_label = f"{paper_count}件"
    entity_label = f"{entity_count}件"
    if total_paper is not None:
        paper_label = f"{paper_count}/{total_paper}件"
    if total_entity is not None:
        entity_label = f"{entity_count}/{total_entity}件"

    console.print(f"\n[green]Paper引用パス:[/] {paper_label}  [cyan]Entity関連パス:[/] {entity_label}\n")

    # Paper引用パス
    if result.paper_paths:
        console.print("[bold green]━━━ Paper引用パス ━━━[/]")
        for i, path in enumerate(result.paper_paths, 1):
            _print_path_rich(path, i, "paper")

    # Entity関連パス
    if result.entity_paths:
        console.print("\n[bold cyan]━━━ Entity関連パス ━━━[/]")
        for i, path in enumerate(result.entity_paths, 1):
            _print_path_rich(path, i, "entity")

    if not result.paper_paths and not result.entity_paths:
        console.print("[yellow]パスが見つかりませんでした[/]")


def _print_path_rich(path, index: int, path_type: str = "paper") -> None:
    """単一パスをrich形式で表示"""
    color = "green" if path_type == "paper" else "cyan"
    max_score = 100.0  # スコアの正規化用

    # スコアバー
    score_percent = min(path.score / max_score * 100, 100) if max_score > 0 else 0
    score_bar_len = int(score_percent / 5)
    score_bar = "█" * score_bar_len + "░" * (20 - score_bar_len)

    # スコアの色
    if score_percent >= 70:
        score_color = "green"
    elif score_percent >= 40:
        score_color = "yellow"
    else:
        score_color = "red"

    console.print(f"\n[bold {color}]#{index}[/] [dim]Score:[/] [{score_color}]{path.score:.1f}[/]  [{score_color}]{score_bar}[/]")

    # ノードパスを表示
    path_parts = []
    for j, node in enumerate(path.nodes):
        if node.label == "Paper":
            node_text = f"[blue]📄 {node.name[:40]}[/]"
        else:
            entity_type = node.entity_type or "Entity"
            type_emoji = {
                "Method": "🔧",
                "Dataset": "📊",
                "Benchmark": "📏",
                "Task": "🎯",
                "Framework": "🏗️",
                "Metric": "📐",
            }.get(entity_type, "📌")
            node_text = f"[magenta]{type_emoji} {node.name[:35]}[/]"
        path_parts.append(node_text)

        if j < len(path.edges):
            edge = path.edges[j]
            edge_color = {
                "CITES": "yellow",
                "MENTIONS": "green",
                "EXTENDS": "orange3",
                "USES": "cyan",
                "COMPARES": "blue",
            }.get(edge.type, "white")
            path_parts.append(f" [{edge_color}]→{edge.type}→[/] ")

    console.print("  " + "".join(path_parts))

    # スコア内訳をコンパクトに表示
    if path.score_breakdown:
        bd = path.score_breakdown
        breakdown_parts = []

        cite_score = bd.get('cite_importance_score', 0) + bd.get('cite_type_score', 0)
        if cite_score > 0:
            breakdown_parts.append(f"[yellow]引用:{cite_score:.1f}[/]")

        entity_score = bd.get('mentions_score', 0) + bd.get('entity_relation_score', 0)
        if entity_score > 0:
            breakdown_parts.append(f"[cyan]Entity:{entity_score:.1f}[/]")

        penalty = bd.get('length_penalty', 0)
        if penalty != 0:
            breakdown_parts.append(f"[red]距離:{penalty:.1f}[/]")

        if breakdown_parts:
            console.print(f"  [dim]スコア内訳:[/] {' | '.join(breakdown_parts)}")


def _print_proposals_rich(result: "ProposalResult", compare: bool = False) -> None:
    """提案結果をrich形式で出力"""
    console.print()
    console.print(Panel(
        f"[bold blue]対象論文:[/] {result.target_paper_id}\n"
        f"[bold blue]提案数:[/] {len(result.proposals)}件",
        title="[bold]研究提案[/]",
        border_style="blue"
    ))

    if compare:
        _print_proposals_comparison(result)
    else:
        for i, proposal in enumerate(result.proposals, 1):
            _print_proposal_card(proposal, i)


def _print_proposal_card(proposal, index: int) -> None:
    """提案をカード形式で表示"""
    console.print()
    console.print(Panel(
        f"[bold]{proposal.title}[/]",
        title=f"[bold cyan]提案 #{index}[/]",
        border_style="cyan"
    ))

    # 動機
    console.print(f"\n[bold green]📝 動機[/]")
    console.print(f"  {proposal.motivation[:200]}..." if len(proposal.motivation) > 200 else f"  {proposal.motivation}")

    # 手法
    console.print(f"\n[bold yellow]🔧 手法[/]")
    console.print(f"  {proposal.method[:200]}..." if len(proposal.method) > 200 else f"  {proposal.method}")

    # 実験計画
    console.print(f"\n[bold magenta]🧪 実験計画[/]")
    exp = proposal.experiment
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("項目", style="dim")
    table.add_column("内容")
    table.add_row("データセット", ", ".join(exp.datasets[:3]) + ("..." if len(exp.datasets) > 3 else ""))
    table.add_row("ベースライン", ", ".join(exp.baselines[:3]) + ("..." if len(exp.baselines) > 3 else ""))
    table.add_row("評価指標", ", ".join(exp.metrics[:3]) + ("..." if len(exp.metrics) > 3 else ""))
    console.print(table)

    # 差異
    console.print(f"\n[bold red]📌 既存研究との差異[/]")
    for diff in proposal.differences[:3]:
        console.print(f"  • {diff[:80]}..." if len(diff) > 80 else f"  • {diff}")


def _print_proposals_comparison(result: "ProposalResult") -> None:
    """提案を比較テーブルで表示"""
    console.print("\n[bold]提案比較[/]\n")

    # 比較テーブル
    table = Table(title="提案の比較", show_lines=True)
    table.add_column("項目", style="bold", width=15)

    for i, proposal in enumerate(result.proposals, 1):
        table.add_column(f"提案 #{i}", width=40)

    # タイトル行
    table.add_row(
        "タイトル",
        *[proposal.title[:38] + "..." if len(proposal.title) > 38 else proposal.title
          for proposal in result.proposals]
    )

    # 動機行
    table.add_row(
        "動機",
        *[proposal.motivation[:80] + "..." if len(proposal.motivation) > 80 else proposal.motivation
          for proposal in result.proposals]
    )

    # 手法行
    table.add_row(
        "手法",
        *[proposal.method[:80] + "..." if len(proposal.method) > 80 else proposal.method
          for proposal in result.proposals]
    )

    # データセット行
    table.add_row(
        "データセット",
        *[", ".join(proposal.experiment.datasets[:2]) + ("..." if len(proposal.experiment.datasets) > 2 else "")
          for proposal in result.proposals]
    )

    # ベースライン行
    table.add_row(
        "ベースライン",
        *[", ".join(proposal.experiment.baselines[:2]) + ("..." if len(proposal.experiment.baselines) > 2 else "")
          for proposal in result.proposals]
    )

    # 評価指標行
    table.add_row(
        "評価指標",
        *[", ".join(proposal.experiment.metrics[:2]) + ("..." if len(proposal.experiment.metrics) > 2 else "")
          for proposal in result.proposals]
    )

    # 差異行
    table.add_row(
        "既存研究との差異",
        *[proposal.differences[0][:60] + "..." if proposal.differences and len(proposal.differences[0]) > 60
          else (proposal.differences[0] if proposal.differences else "N/A")
          for proposal in result.proposals]
    )

    console.print(table)


def _format_proposals_markdown(result: "ProposalResult") -> str:
    """提案結果をMarkdown形式でフォーマット"""
    lines = [
        f"# Research Proposals for {result.target_paper_id}",
        "",
        f"Generated {len(result.proposals)} proposals.",
        "",
    ]

    if getattr(result, "prompt", None):
        lines.extend([
            "## Generation Prompt",
            "```text",
            result.prompt,
            "```",
            "",
        ])

    for i, proposal in enumerate(result.proposals, 1):
        lines.extend([
            f"## Proposal {i}: {proposal.title}",
            "",
            "### Rationale",
            proposal.rationale,
            "",
            "### Research Trends",
            proposal.research_trends,
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
    import queue
    import threading
    from dataclasses import dataclass

    from idea_graph.ingestion import (
        BufferedGraphWriter,
        CitationCrawler,
        DatasetLoaderService,
        DownloaderService,
        ExtractorService,
        GraphWriterService,
    )
    from idea_graph.ingestion.parallel import RateLimiters
    from idea_graph.ingestion.progress import ProgressManager

    @dataclass
    class ExtractionTask:
        paper: object
        file_path: Path
        file_type: object
        published_date: object

    @dataclass
    class PipelineResult:
        paper_id: str
        status: str
        error_message: str | None = None

    logging.info("Starting ingestion pipeline...")

    # 設定の確認
    settings.ensure_cache_dirs()

    # 並列数の決定
    workers = max(1, args.workers or settings.ingestion_max_workers)
    download_workers = 1 if args.skip_download else min(workers, 2)
    extract_workers = 0
    if not args.skip_extract:
        extract_workers = max(
            1,
            min(workers, max(1, settings.gemini_max_concurrent + 1)),
        )

    # レートリミッター・サービスの初期化
    rate_limiters = RateLimiters()
    loader = DatasetLoaderService()
    downloader = DownloaderService(rate_limiters=rate_limiters)
    extractor = ExtractorService(rate_limiters=rate_limiters)
    writer = GraphWriterService()
    progress = ProgressManager()
    buffered_writer: BufferedGraphWriter | None = None
    exit_code = 0

    logging.info(
        "Using workers: total=%s download=%s extract=%s write=%s",
        workers,
        download_workers,
        extract_workers,
        0 if args.skip_write else 1,
    )

    try:
        if not args.skip_write:
            logging.info("Ensuring Neo4j indexes...")
            try:
                writer.ensure_indexes()
            except Exception as e:
                logging.error(f"Failed to create indexes: {e}")
                logging.error("Make sure Neo4j is running (docker compose up -d)")
                return 1
            buffered_writer = BufferedGraphWriter(writer=writer)
        else:
            logging.info("Skipping all Neo4j writes (--skip-write)")

        # データセットの読み込み
        logging.info("Loading dataset...")
        papers = list(loader.load())
        logging.info(f"Found {len(papers)} papers")

        # 制限がある場合
        if args.limit:
            papers = papers[: args.limit]
            logging.info(f"Limited to {args.limit} papers")
        progress.set_total(len(papers))

        # 完了済みをスキップ
        completed_all = progress.get_completed_papers()
        completed_in_scope = {p.paper_id for p in papers if p.paper_id in completed_all}
        papers_to_process = [p for p in papers if p.paper_id not in completed_in_scope]
        logging.info(f"Skipping {len(completed_in_scope)} already processed papers")
        logging.info(f"Processing {len(papers_to_process)} papers")

        if not args.skip_write:
            logging.info("Writing Paper nodes...")
            writer.write_papers(papers)

        download_queue: queue.Queue[object | None] = queue.Queue()
        extract_queue: queue.Queue[ExtractionTask | None] = queue.Queue()
        result_queue: queue.Queue[PipelineResult] = queue.Queue()
        download_threads: list[threading.Thread] = []
        extract_threads: list[threading.Thread] = []
        download_shutdown_lock = threading.Lock()
        finished_download_workers = 0

        def publish_result(paper_id: str, status: str, error_message: str | None = None) -> None:
            result_queue.put(
                PipelineResult(
                    paper_id=paper_id,
                    status=status,
                    error_message=error_message,
                )
            )

        def complete_after_write(paper_id: str):
            def callback(error: Exception | None) -> None:
                if error is not None:
                    progress.update_status(paper_id, "failed", str(error))
                    publish_result(paper_id, "failed", str(error))
                    return
                progress.update_status(paper_id, "completed")
                publish_result(paper_id, "completed")

            return callback

        def fail_paper(paper_id: str, error_message: str) -> None:
            progress.update_status(paper_id, "failed", error_message)
            publish_result(paper_id, "failed", error_message)

        def download_worker() -> None:
            nonlocal finished_download_workers
            while True:
                paper = download_queue.get()
                if paper is None:
                    with download_shutdown_lock:
                        finished_download_workers += 1
                        if finished_download_workers == download_workers:
                            for _ in range(extract_workers):
                                extract_queue.put(None)
                    return

                progress.register_paper(paper.paper_id, paper.title)

                try:
                    if args.skip_download:
                        result = downloader.get_cached_download(paper.paper_id)
                        if result is None:
                            fail_paper(
                                paper.paper_id,
                                "Download skipped and no cached file found",
                            )
                            continue
                    else:
                        progress.update_status(paper.paper_id, "downloading")
                        result = downloader.download(paper.paper_id, paper.title)

                    if not result.success:
                        fail_paper(
                            paper.paper_id,
                            result.error_message or "Download failed",
                        )
                        continue

                    if args.skip_extract:
                        if args.skip_write or buffered_writer is None:
                            progress.update_status(paper.paper_id, "completed")
                            publish_result(paper.paper_id, "completed")
                            continue
                        progress.update_status(paper.paper_id, "writing")
                        buffered_writer.enqueue_published_date(
                            paper.paper_id,
                            result.published_date,
                            on_done=complete_after_write(paper.paper_id),
                        )
                        continue

                    if result.file_path is None or result.file_type is None:
                        fail_paper(
                            paper.paper_id,
                            "Download succeeded but file metadata is missing",
                        )
                        continue

                    extract_queue.put(
                        ExtractionTask(
                            paper=paper,
                            file_path=result.file_path,
                            file_type=result.file_type,
                            published_date=result.published_date,
                        )
                    )
                except Exception as exc:
                    fail_paper(paper.paper_id, str(exc))

        def extract_worker() -> None:
            while True:
                task = extract_queue.get()
                if task is None:
                    return

                progress.update_status(task.paper.paper_id, "extracting")
                try:
                    extracted = extractor.extract(
                        task.paper.paper_id,
                        task.file_path,
                        task.file_type,
                    )
                    if extracted is None:
                        fail_paper(task.paper.paper_id, "Extraction failed")
                        continue

                    if args.skip_write or buffered_writer is None:
                        progress.update_status(task.paper.paper_id, "completed")
                        publish_result(task.paper.paper_id, "completed")
                        continue

                    progress.update_status(task.paper.paper_id, "writing")
                    buffered_writer.enqueue_extracted(
                        extracted,
                        published_date=task.published_date,
                        on_done=complete_after_write(task.paper.paper_id),
                    )
                except Exception as exc:
                    fail_paper(task.paper.paper_id, str(exc))

        for _ in range(download_workers):
            thread = threading.Thread(target=download_worker, daemon=True)
            thread.start()
            download_threads.append(thread)

        for _ in range(extract_workers):
            thread = threading.Thread(target=extract_worker, daemon=True)
            thread.start()
            extract_threads.append(thread)

        for paper in papers_to_process:
            download_queue.put(paper)
        for _ in range(download_workers):
            download_queue.put(None)

        with logging_redirect_tqdm():
            with tqdm(
                total=len(papers),
                initial=len(completed_in_scope),
                desc="Processing papers",
                unit="paper",
                dynamic_ncols=True,
                leave=True,
            ) as pbar:
                completed_count = 0
                while completed_count < len(papers_to_process):
                    result = result_queue.get()
                    completed_count += 1
                    pbar.update(1)

                    if result.status == "failed":
                        logging.warning(
                            "Paper %s failed during dataset ingest: %s",
                            result.paper_id,
                            result.error_message,
                        )

        for thread in download_threads:
            thread.join()
        for thread in extract_threads:
            thread.join()
        if buffered_writer is not None:
            buffered_writer.flush()

        # 引用論文のクロール（max_depth > 0 の場合）
        if args.max_depth > 0 and not args.skip_download and not args.skip_write:
            logging.info(
                f"Starting citation crawl (max_depth={args.max_depth}, "
                f"top_n_citations={args.top_n_citations})..."
            )
            crawler = CitationCrawler(
                downloader=downloader,
                extractor=extractor,
                writer=writer,
                progress=progress,
                buffered_writer=buffered_writer,
                max_depth=args.max_depth,
                crawl_limit=args.crawl_limit,
                top_n_citations=args.top_n_citations,
                skip_write=args.skip_write,
            )
            crawler.add_seeds(papers)

            crawl_stats = {"completed": 0, "failed": 0, "not_found": 0, "skipped": 0}
            with logging_redirect_tqdm():
                planned_total = crawler.get_planned_total(seed_count=len(papers))
                limit = args.crawl_limit
                with tqdm(
                    total=(limit if limit is not None else planned_total),
                    desc="Crawling citations",
                    unit="paper",
                    dynamic_ncols=True,
                    leave=True,
                ) as pbar:
                    if workers > 1:
                        results = crawler.crawl_parallel(max_workers=workers)
                    else:
                        results = crawler.crawl()

                    for result in results:
                        crawl_stats[result.status] = crawl_stats.get(result.status, 0) + 1

                        if limit:
                            if result.status != "skipped":
                                pbar.update(1)
                        else:
                            pbar.update(1)

                        pbar.set_postfix(
                            completed=crawl_stats["completed"],
                            failed=crawl_stats["failed"],
                            not_found=crawl_stats["not_found"],
                            skipped=crawl_stats["skipped"],
                            queued=crawler.get_queue_size(),
                        )

                    if limit is None and pbar.total is not None and pbar.n < pbar.total:
                        pbar.total = pbar.n
                        pbar.refresh()

            if buffered_writer is not None:
                buffered_writer.flush()
            logging.info(f"Crawl completed: {crawl_stats}")
        elif args.max_depth > 0 and args.skip_write:
            logging.info("Skipping citation crawl because --skip-write disables graph updates")

        summary = progress.get_summary()
        logging.info(f"Completed: {summary['processed']}/{summary['total']}")
        logging.info(f"Failed: {summary['failed']}")
        logging.info(f"Pending: {summary['pending']}")
    except Exception as exc:
        logging.error(f"Ingestion pipeline failed: {exc}")
        exit_code = 1
    finally:
        if buffered_writer is not None:
            try:
                buffered_writer.close()
            except Exception as exc:
                logging.error(f"Failed to close graph writer: {exc}")
                exit_code = 1

        try:
            progress.close()
        except Exception as exc:
            logging.error(f"Failed to save progress: {exc}")
            exit_code = 1

    return exit_code


def cmd_rebuild(args: argparse.Namespace) -> int:
    """キャッシュ（cache/extractions）から Neo4j を再構築"""
    import json

    from idea_graph.ingestion import DatasetLoaderService, GraphWriterService
    from idea_graph.ingestion.extractor import ExtractedInfo

    logging.info("Starting rebuild from cache...")

    # --cache-dir が指定されていたら settings を上書き
    if args.cache_dir:
        custom_cache = Path(args.cache_dir)
        settings.cache_dir = custom_cache
        settings.papers_cache_dir = custom_cache / "papers"
        settings.extractions_cache_dir = custom_cache / "extractions"
        logging.info(f"Using custom cache directory: {custom_cache}")

    # 設定の確認
    settings.ensure_cache_dirs()

    writer = GraphWriterService()

    # インデックスの作成
    logging.info("Ensuring Neo4j indexes...")
    try:
        writer.ensure_indexes()
    except Exception as e:
        logging.error(f"Failed to create indexes: {e}")
        logging.error("Make sure Neo4j is running (docker compose up -d)")
        return 1

    # データセットの読み込み（Paperタイトルの復元）
    logging.info("Loading dataset (for Paper titles)...")
    loader = DatasetLoaderService()
    papers = list(loader.load())
    if args.limit:
        papers = papers[: args.limit]
        logging.info(f"Limited dataset papers to {args.limit}")

    logging.info("Writing Paper nodes...")
    writer.write_papers(papers)

    # cache/extractions から抽出結果を読み込み、グラフへ書き戻し
    cache_dir = settings.extractions_cache_dir
    cache_files = sorted(cache_dir.glob("*.json"))

    if args.limit:
        # datasetのlimitに合わせて「全体の作業量を抑えたい」用途を想定
        cache_files = cache_files[: args.limit]
        logging.info(f"Limited cached extractions to {args.limit}")

    if not cache_files:
        logging.warning(f"No cached extractions found in: {cache_dir}")
        logging.warning("Run: uv run idea-graph ingest  (to populate cache/extractions)")
        return 0

    logging.info(f"Replaying {len(cache_files)} cached extractions from: {cache_dir}")

    batch: list[ExtractedInfo] = []
    processed = 0
    failed = 0
    batch_size = args.batch_size or 200

    for path in tqdm(cache_files, desc="Rebuilding from cache/extractions"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            batch.append(ExtractedInfo(**data))
        except Exception as e:
            failed += 1
            logging.warning(f"Failed to load cached extraction: {path} ({e})")
            continue

        if len(batch) >= batch_size:
            writer.write_extracted(batch)
            processed += len(batch)
            batch.clear()

    if batch:
        writer.write_extracted(batch)
        processed += len(batch)
        batch.clear()

    logging.info(f"Rebuild done. processed={processed}, failed={failed}")
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
    if "known_total" in summary:
        print("\n=== Progress (including citations) ===")
        print(f"Known total: {summary['known_total']}")
        print(f"Completed: {summary['known_completed']}")
        print(f"Failed: {summary['known_failed']}")
        print(f"Not found: {summary['known_not_found']}")
        print(f"In progress: {summary['known_in_progress']}")
        print(f"Pending: {summary['known_pending']}")

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

    # 結果を保存
    if hasattr(args, 'save') and args.save:
        from idea_graph.services.storage import StorageService
        storage = StorageService()
        saved = storage.save_analysis(
            target_paper_id=args.paper_id,
            analysis_result=result.model_dump(),
        )
        console.print(f"[green]分析結果を保存しました: {saved.id}[/]")

    # 結果表示
    if args.format == "json":
        _print_analysis_json(result)
    elif args.format == "rich":
        _print_analysis_rich(result)
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
    if not settings.openai_api_key:
        logging.error("OPENAI_API_KEY is not set. Please set it in .env file.")
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
        prompt_options = _build_prompt_options(args)
    except ValueError as e:
        logging.error(str(e))
        return 1

    try:
        proposal_result = proposal_service.propose(
            target_paper_id=args.paper_id,
            analysis_result=analysis_result,
            num_proposals=args.num_proposals,
            prompt_options=prompt_options,
        )
    except ValueError as e:
        logging.error(str(e))
        return 1
    except Exception as e:
        logging.error(f"Proposal generation failed: {e}")
        return 1

    # 結果を保存
    if hasattr(args, 'save') and args.save:
        from idea_graph.services.storage import StorageService
        storage = StorageService()
        for proposal in proposal_result.proposals:
            saved = storage.save_proposal(
                target_paper_id=args.paper_id,
                proposal=proposal.model_dump(),
                prompt=proposal_result.prompt,
            )
            console.print(f"[green]提案を保存しました: {saved.id} - {proposal.title[:40]}[/]")

    # Step 3: 結果出力
    if args.format == "json":
        output = proposal_result.model_dump_json(indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            logging.info(f"Output written to: {args.output}")
        else:
            print(output)
    elif args.format == "rich":
        compare = hasattr(args, 'compare') and args.compare
        _print_proposals_rich(proposal_result, compare=compare)
    else:
        output = _format_proposals_markdown(proposal_result)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            logging.info(f"Output written to: {args.output}")
        else:
            print(output)

    return 0


def _print_evaluation_rich(result) -> None:
    """評価結果をリッチフォーマットで表示"""
    console.print()
    console.print(Panel(
        f"[bold]Evaluation Results[/bold]\n"
        f"Model: {result.model_name}\n"
        f"Proposals: {len(result.proposals)}\n"
        f"Evaluated at: {result.evaluated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        title="Idea Evaluation Report",
        border_style="green",
    ))

    # ランキングテーブル
    table = Table(title="Rankings", show_header=True, header_style="bold magenta")
    table.add_column("Rank", style="dim", width=6)
    table.add_column("Title", style="cyan")
    table.add_column("Type", style="yellow", width=10)
    table.add_column("Overall", justify="right")
    table.add_column("Novelty", justify="right")
    table.add_column("Significance", justify="right")
    table.add_column("Feasibility", justify="right")
    table.add_column("Clarity", justify="right")
    table.add_column("Effectiveness", justify="right")

    from idea_graph.models.evaluation import EvaluationMetric

    for entry in result.ranking:
        title = (entry.idea_title or entry.idea_id)[:40]
        # ターゲット論文の場合は特別な表示
        type_label = "[Target]" if getattr(entry, "is_target_paper", False) else ""
        table.add_row(
            str(entry.rank),
            title,
            type_label,
            f"{entry.overall_score:.1f}",
            f"{entry.scores_by_metric.get(EvaluationMetric.NOVELTY, 0):.1f}",
            f"{entry.scores_by_metric.get(EvaluationMetric.SIGNIFICANCE, 0):.1f}",
            f"{entry.scores_by_metric.get(EvaluationMetric.FEASIBILITY, 0):.1f}",
            f"{entry.scores_by_metric.get(EvaluationMetric.CLARITY, 0):.1f}",
            f"{entry.scores_by_metric.get(EvaluationMetric.EFFECTIVENESS, 0):.1f}",
        )

    console.print(table)
    console.print()


def _print_single_evaluation_rich(result) -> None:
    """単体評価結果をリッチフォーマットで表示"""
    console.print()
    console.print(Panel(
        f"[bold]Independent Evaluation Results[/bold]\n"
        f"Model: {result.model_name}\n"
        f"Proposals: {len(result.proposals)}\n"
        f"Evaluated at: {result.evaluated_at.strftime('%Y-%m-%d %H:%M:%S')}",
        title="Idea Independent Evaluation Report",
        border_style="green",
    ))

    table = Table(title="Rankings (Absolute Score)", show_header=True, header_style="bold magenta")
    table.add_column("Rank", style="dim", width=6)
    table.add_column("Title", style="cyan")
    table.add_column("Overall", justify="right")
    table.add_column("Novelty", justify="right")
    table.add_column("Significance", justify="right")
    table.add_column("Feasibility", justify="right")
    table.add_column("Clarity", justify="right")
    table.add_column("Effectiveness", justify="right")

    for rank, entry in enumerate(result.ranking, 1):
        title = (entry.idea_title or entry.idea_id)[:40]
        scores_dict = {s.metric.value: s.score for s in entry.scores}
        table.add_row(
            str(rank),
            title,
            f"{entry.overall_score:.1f}",
            str(scores_dict.get("novelty", "-")),
            str(scores_dict.get("significance", "-")),
            str(scores_dict.get("feasibility", "-")),
            str(scores_dict.get("clarity", "-")),
            str(scores_dict.get("effectiveness", "-")),
        )

    console.print(table)

    # 各アイデアの評価理由を表示
    console.print()
    for rank, entry in enumerate(result.ranking, 1):
        title = entry.idea_title or entry.idea_id
        console.print(f"[bold cyan]{rank}. {title}[/] (Overall: {entry.overall_score:.1f})")
        for s in entry.scores:
            console.print(f"  [dim]{s.metric.value.capitalize()}[/] ({s.score}/10): {s.reasoning}")
        console.print()


def _build_text_from_extraction_cache(data: dict) -> str:
    """抽出キャッシュから LLM 用の入力テキストを構築"""
    summary = data.get("paper_summary", "") or ""
    claims = data.get("claims", []) or []
    entities = data.get("entities", []) or []
    cited_papers = data.get("cited_papers", []) or []

    def _unique_sorted(values: list[str]) -> list[str]:
        return sorted({v.strip() for v in values if v and v.strip()})

    # エンティティをタイプ別に整理
    datasets = _unique_sorted(
        [e.get("name", "") for e in entities if e.get("type") in {"Dataset", "Benchmark"}]
    )
    metrics = _unique_sorted(
        [e.get("name", "") for e in entities if e.get("type") == "Metric"]
    )
    methods = _unique_sorted(
        [e.get("name", "") for e in entities if e.get("type") in {"Method", "Approach", "Framework"}]
    )

    # 比較対象は引用情報から抽出
    baselines = []
    for c in cited_papers:
        if c.get("citation_type") == "COMPARES":
            title = c.get("title", "").strip()
            if not title and c.get("reference_number") is not None:
                title = f"Reference #{c['reference_number']}"
            baselines.append(title)
    baselines = _unique_sorted(baselines)

    # エンティティ詳細（説明込み）
    entity_lines = []
    for e in entities:
        name = e.get("name", "").strip()
        e_type = e.get("type", "").strip()
        desc = (e.get("description") or "").strip()
        if not name or not e_type:
            continue
        if desc:
            entity_lines.append(f"- {name} ({e_type}): {desc}")
        else:
            entity_lines.append(f"- {name} ({e_type})")

    parts = [
        "Note: The following content is derived from a structured extraction cache, not full paper text.",
    ]
    if summary:
        parts.append("Paper summary:\n" + summary)
    if claims:
        parts.append("Claims:\n- " + "\n- ".join(claims))
    if methods:
        parts.append("Key methods/approaches:\n- " + "\n- ".join(methods))
    if datasets:
        parts.append("Datasets/benchmarks:\n- " + "\n- ".join(datasets))
    if metrics:
        parts.append("Metrics:\n- " + "\n- ".join(metrics))
    if baselines:
        parts.append("Comparison baselines (from citations):\n- " + "\n- ".join(baselines))
    if entity_lines:
        parts.append("Key entities:\n" + "\n".join(entity_lines))

    return "\n\n".join(parts).strip()


def _get_paper_full_text(paper_id: str) -> str | None:
    """キャッシュから論文の全文テキストを取得

    Args:
        paper_id: 論文ID

    Returns:
        論文の全文テキスト、取得できない場合はNone
    """
    import io
    import tarfile
    from idea_graph.ingestion.downloader import FileType
    from idea_graph.ingestion.extractor import ExtractorService

    # キャッシュディレクトリを確認
    paper_dir = settings.papers_cache_dir / paper_id
    if not paper_dir.exists():
        logging.warning(f"Paper directory not found: {paper_dir}")
        return None

    # ファイルを探す（source.tar.gz優先、次にpaper.pdf）
    tar_path = paper_dir / "source.tar.gz"
    pdf_path = paper_dir / "paper.pdf"

    if tar_path.exists():
        file_path = tar_path
        file_type = FileType.LATEX
    elif pdf_path.exists():
        file_path = pdf_path
        file_type = FileType.PDF
    else:
        logging.warning(f"No paper file found in: {paper_dir}")
        return None

    logging.info(f"Loading paper from: {file_path}")

    # LaTeXの場合は直接テキストを抽出
    if file_type == FileType.LATEX:
        try:
            content = file_path.read_bytes()
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
                tex_files = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".tex")]
                if not tex_files:
                    logging.warning(f"No .tex files found in {file_path}")
                    return None

                # main.tex または最大のファイルを優先
                main_file = None
                for tf in tex_files:
                    name_lower = tf.name.lower()
                    if "main" in name_lower or "paper" in name_lower:
                        main_file = tf
                        break
                if main_file is None:
                    main_file = max(tex_files, key=lambda x: x.size)

                f = tar.extractfile(main_file)
                if f is None:
                    return None

                text_content = f.read().decode("utf-8", errors="ignore")

                # .bbl ファイルも含める
                bbl_files = [m for m in tar.getmembers() if m.isfile() and m.name.endswith(".bbl")]
                if bbl_files:
                    bbl = max(bbl_files, key=lambda x: x.size)
                    bf = tar.extractfile(bbl)
                    if bf is not None:
                        bbl_content = bf.read().decode("utf-8", errors="ignore")
                        text_content = f"{text_content}\n\n{bbl_content}"

                return text_content
        except Exception as e:
            logging.error(f"Failed to extract text from LaTeX: {e}")
            return None
    else:
        # PDFの場合は抽出キャッシュを確認
        extraction_path = settings.extractions_cache_dir / f"{paper_id}.json"
        if extraction_path.exists():
            # 抽出キャッシュがあれば、そこからサマリーと主張を取得
            # （PDF全文の直接取得は難しいため、代替手段）
            import json

            try:
                data = json.loads(extraction_path.read_text())
                return _build_text_from_extraction_cache(data)
            except Exception as e:
                logging.error(f"Failed to load extraction cache: {e}")
                return None

        logging.warning(f"PDF full text extraction not directly supported, no extraction cache found")
        return None

def cmd_experiment(args: argparse.Namespace) -> int:
    """実験サブコマンド"""
    from idea_graph.services.experiment_runner import ExperimentRunner
    from idea_graph.services.experiment_cache import ExperimentCache
    from idea_graph.services.aggregator import ExperimentAggregator

    sub = args.experiment_command

    if sub == "run":
        runner = ExperimentRunner(no_cache=args.no_cache)
        summary = runner.run(
            config_path=args.config,
            limit=args.limit,
            no_cache=args.no_cache,
            clear_cache=args.clear_cache,
            parallel=args.parallel,
        )
        console.print(f"[green]Run ID: {summary.run_id}[/]")
        return 0

    if sub == "list":
        runner = ExperimentRunner()
        runs = runner.list_runs()
        if not runs:
            console.print("[yellow]No experiment runs found.[/]")
            return 0
        table = Table(title="Experiment Runs", show_header=True, header_style="bold magenta")
        table.add_column("Run ID", style="cyan")
        table.add_column("Experiment", style="green")
        table.add_column("Papers")
        table.add_column("Started")
        for run in runs:
            table.add_row(
                run.run_id,
                run.experiment_id,
                str(len(run.target_papers)),
                run.started_at[:19],
            )
        console.print(table)
        return 0

    if sub == "aggregate":
        agg = ExperimentAggregator()
        result = agg.aggregate(args.run_dir)
        console.print(f"[green]Aggregation complete. Saved to {args.run_dir}/summary/aggregate.json[/]")
        # 簡易表示
        for condition, metrics in result.get("single_summary", {}).items():
            overall = metrics.get("overall", {})
            if overall:
                console.print(f"  {condition}: mean={overall.get('mean', 0):.2f} std={overall.get('std', 0):.2f}")
        return 0

    if sub == "compare":
        agg = ExperimentAggregator()
        result = agg.compare(args.run_dirs)
        console.print(f"[green]Comparison baseline: {result['baseline']}[/]")
        for key, comp in result.get("comparisons", {}).items():
            console.print(f"  vs {key}:")
            for cond, delta in comp.get("overall_mean_delta_vs_baseline", {}).items():
                sign = "+" if delta >= 0 else ""
                console.print(f"    {cond}: {sign}{delta:.3f}")
        return 0

    if sub == "cache-status":
        cache = ExperimentCache()
        status = cache.status()
        if not status:
            console.print("[yellow]Cache is empty.[/]")
            return 0
        table = Table(title="Cache Status", show_header=True, header_style="bold magenta")
        table.add_column("Stage", style="cyan")
        table.add_column("Files", justify="right")
        for stage, count in sorted(status.items()):
            table.add_row(stage, str(count))
        console.print(table)
        return 0

    if sub == "clear-cache":
        cache = ExperimentCache()
        cleared = cache.clear(stage=args.stage)
        console.print(f"[green]Cleared {cleared} cache files.[/]")
        return 0

    if sub == "paper-figures":
        from idea_graph.services.visualizer import ExperimentVisualizer

        vis = ExperimentVisualizer()
        results = vis.generate_paper_figures(
            output_dir=args.output,
            runs_base=args.runs_base,
            formats=args.formats,
            paper_ids=args.paper_ids,
            exclude_ids=args.exclude_paper_ids,
        )
        if not results:
            console.print("[yellow]No figures or tables generated. Check that experiments/runs/ contains run data.[/]")
            return 0
        table = Table(title="Generated Paper Figures & Tables", show_header=True, header_style="bold magenta")
        table.add_column("Name", style="cyan")
        table.add_column("Files")
        for name, paths in sorted(results.items()):
            table.add_row(name, ", ".join(p.name for p in paths))
        console.print(table)
        console.print(f"[green]Output directory: {args.output}[/]")
        return 0

    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """評価コマンド"""
    import json
    from pathlib import Path
    from idea_graph.services.evaluation import EvaluationService
    from idea_graph.services.proposal import Proposal

    # APIキー確認
    if not settings.openai_api_key:
        logging.error("OPENAI_API_KEY is not set. Please set it in .env file.")
        return 1

    # 入力ファイルの読み込み
    proposals_path = Path(args.proposals_file)
    if not proposals_path.exists():
        logging.error(f"Proposals file not found: {proposals_path}")
        return 1

    logging.info(f"Loading proposals from: {proposals_path}")

    # ターゲット論文情報を追跡
    target_paper_content: str | None = None
    target_paper_title: str | None = None
    target_paper_id: str | None = None

    try:
        data = json.loads(proposals_path.read_text(encoding="utf-8"))

        # ProposalResult形式（proposalsフィールドあり）またはProposalリスト
        if "proposals" in data:
            proposals_data = data["proposals"]

            # ターゲット論文情報を取得（--include-targetが指定された場合）
            if getattr(args, "include_target", False):
                # target_paper（新形式）またはtarget_paper_id（旧形式）から取得
                target_info = data.get("target_paper")

                if target_info and isinstance(target_info, dict):
                    target_paper_id = target_info.get("id")
                    target_paper_title = target_info.get("title")
                if not target_paper_id and "target_paper_id" in data:
                    target_paper_id = data["target_paper_id"]

                if target_paper_id:
                    logging.info(f"Found target paper ID: {target_paper_id}")
                    target_paper_content = _get_paper_full_text(target_paper_id)
                    if target_paper_content:
                        logging.info(f"Loaded target paper content ({len(target_paper_content)} chars)")
                    else:
                        logging.warning(
                            f"Could not load target paper content from cache. "
                            f"Target paper comparison will be skipped."
                        )

        elif isinstance(data, list):
            proposals_data = data
        else:
            logging.error("Invalid proposals file format. Expected ProposalResult or list of Proposals.")
            return 1

        proposals = [Proposal(**p) for p in proposals_data]
        logging.info(f"Loaded {len(proposals)} proposals")
    except Exception as e:
        logging.error(f"Failed to load proposals: {e}")
        return 1

    # 評価サービスの初期化
    service = EvaluationService(model_name=args.model)
    eval_mode = getattr(args, "mode", "pairwise")

    if eval_mode == "single":
        # === 単体（絶対）評価モード ===
        if len(proposals) < 1:
            logging.error("At least 1 proposal is required for single evaluation.")
            return 1

        logging.info("Starting single (absolute) evaluation...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Evaluating proposals (single mode)...", total=None)
            result = service.evaluate_single(
                proposals=proposals,
                proposal_sources=None,
            )
            progress.update(task, completed=True)

        # 結果出力
        if args.format == "json":
            output = result.model_dump_json(indent=2)
            if args.output:
                Path(args.output).write_text(output, encoding="utf-8")
                logging.info(f"Output written to: {args.output}")
            else:
                print(output)
        elif args.format == "markdown":
            output = service.generate_single_markdown_report(result)
            if args.output:
                Path(args.output).write_text(output, encoding="utf-8")
                logging.info(f"Output written to: {args.output}")
            else:
                print(output)
        else:  # rich
            _print_single_evaluation_rich(result)

        # 結果を自動保存
        json_path = service.save_single_result(result)
        console.print("[green]Results saved to:[/]")
        console.print(f"  JSON: {json_path}")

    else:
        # === ペアワイズ比較評価モード（既存） ===
        # バリデーション: 提案数 + ターゲット論文(指定時は1) >= 2 で判断
        proposal_count = len(proposals)
        target_paper_count = 1 if target_paper_content else 0
        total_count = proposal_count + target_paper_count
        if total_count < 2:
            logging.error("At least 2 ideas are required for pairwise evaluation (proposals + target paper).")
            return 1

        logging.info("Starting pairwise evaluation...")
        if target_paper_content:
            logging.info("Including target paper in comparison")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Evaluating proposals...", total=None)
            result = service.evaluate(
                proposals=proposals,
                include_experiment=not args.no_experiment,
                target_paper_content=target_paper_content,
                target_paper_title=target_paper_title,
                target_paper_id=target_paper_id,
            )
            progress.update(task, completed=True)

        # 結果出力
        if args.format == "json":
            output = result.model_dump_json(indent=2)
            if args.output:
                Path(args.output).write_text(output, encoding="utf-8")
                logging.info(f"Output written to: {args.output}")
            else:
                print(output)
        elif args.format == "markdown":
            output = service.generate_markdown_report(result)
            if args.output:
                Path(args.output).write_text(output, encoding="utf-8")
                logging.info(f"Output written to: {args.output}")
            else:
                print(output)
        else:  # rich
            _print_evaluation_rich(result)

        # 結果を自動保存
        json_path = service.save_result(result)
        md_path = service.save_markdown_report(result)
        console.print("[green]Results saved to:[/]")
        console.print(f"  JSON: {json_path}")
        console.print(f"  Markdown: {md_path}")

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
    ingest_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列処理のワーカー数 (default: 設定値)",
    )

    # rebuild コマンド
    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="cache/extractions から Neo4j を再構築（DBを作り直したいとき用）",
    )
    rebuild_parser.add_argument(
        "--limit",
        type=int,
        help="処理する件数の制限（datasetのPaper作成とcache再生の両方に適用）",
    )
    rebuild_parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="キャッシュディレクトリのパス（デフォルト: settings の cache_dir）",
    )
    rebuild_parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="cache再生時の書き込みバッチサイズ (デフォルト: 200)",
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
        default=None,
        help="返すパス数 (デフォルト: 制限なし)",
    )
    analyze_parser.add_argument(
        "--format",
        choices=["table", "json", "rich"],
        default="table",
        help="出力形式 (デフォルト: table)",
    )
    analyze_parser.add_argument(
        "--save",
        action="store_true",
        help="分析結果を保存",
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
        default=None,
        help="分析時に使用するパス数 (デフォルト: 制限なし)",
    )
    propose_parser.add_argument(
        "--format",
        choices=["markdown", "json", "rich"],
        default="markdown",
        help="出力形式 (デフォルト: markdown)",
    )
    propose_parser.add_argument(
        "-o", "--output",
        type=str,
        help="出力ファイルパス（指定しない場合は標準出力）",
    )
    propose_parser.add_argument(
        "--compare",
        action="store_true",
        help="提案を比較テーブルで表示（--format richと組み合わせ）",
    )
    propose_parser.add_argument(
        "--save",
        action="store_true",
        help="提案を保存",
    )
    propose_parser.add_argument(
        "--prompt-graph-format",
        choices=["mermaid", "paths"],
        default="mermaid",
        help="プロンプトのグラフ出力形式 (デフォルト: mermaid)",
    )
    propose_parser.add_argument(
        "--prompt-scope",
        choices=["path", "k_hop", "path_plus_k_hop"],
        default="path",
        help="プロンプト展開のスコープ (デフォルト: path)",
    )
    propose_parser.add_argument(
        "--prompt-node-type-fields",
        default=None,
        help="ノード種別ごとの展開情報 (JSON)",
    )
    propose_parser.add_argument(
        "--prompt-edge-type-fields",
        default=None,
        help="エッジ種別ごとの展開情報 (JSON)",
    )
    propose_parser.add_argument(
        "--prompt-max-paths",
        type=int,
        default=None,
        help="展開するパス数上限 (デフォルト: 分析結果から自動算出)",
    )
    propose_parser.add_argument(
        "--prompt-max-nodes",
        type=int,
        default=None,
        help="展開するノード数上限 (デフォルト: 分析結果から自動算出)",
    )
    propose_parser.add_argument(
        "--prompt-max-edges",
        type=int,
        default=None,
        help="展開するエッジ数上限 (デフォルト: 分析結果から自動算出)",
    )
    propose_parser.add_argument(
        "--prompt-neighbor-k",
        type=int,
        default=None,
        help="k-hop 近傍の深さ (デフォルト: 分析結果から自動算出)",
    )
    propose_parser.add_argument(
        "--prompt-inline-edges",
        dest="prompt_inline_edges",
        action="store_true",
        default=True,
        help="A -(REL)-> B 形式でエッジを展開する",
    )
    propose_parser.add_argument(
        "--prompt-no-inline-edges",
        dest="prompt_inline_edges",
        action="store_false",
        help="エッジのインライン展開を無効化する",
    )
    propose_parser.add_argument(
        "--prompt-include-target-paper",
        dest="prompt_include_target_paper",
        action="store_true",
        default=False,
        help="ターゲット論文をプロンプトコンテキストに含める",
    )
    propose_parser.add_argument(
        "--prompt-no-include-target-paper",
        dest="prompt_include_target_paper",
        action="store_false",
        help="ターゲット論文をプロンプトコンテキストから除外する（デフォルト）",
    )
    propose_parser.add_argument(
        "--prompt-exclude-future-papers",
        dest="prompt_exclude_future_papers",
        action="store_true",
        default=True,
        help="未来の論文をプロンプトコンテキストから除外する（デフォルト）",
    )
    propose_parser.add_argument(
        "--prompt-no-exclude-future-papers",
        dest="prompt_exclude_future_papers",
        action="store_false",
        help="未来の論文もプロンプトコンテキストに含める",
    )

    # experiment コマンド
    experiment_parser = subparsers.add_parser("experiment", help="実験の実行・管理")
    experiment_sub = experiment_parser.add_subparsers(dest="experiment_command", help="実験サブコマンド")

    exp_run = experiment_sub.add_parser("run", help="実験を実行")
    exp_run.add_argument("config", type=str, help="YAML設定ファイルのパス")
    exp_run.add_argument("--limit", type=int, default=None, help="対象論文数の制限")
    exp_run.add_argument("--no-cache", action="store_true", help="キャッシュ読み込みを無効化")
    exp_run.add_argument("--clear-cache", action="store_true", help="実行前にキャッシュを削除")
    exp_run.add_argument("--parallel", type=int, default=1,
                         help="論文単位の並列実行数 (デフォルト: 1 = 逐次実行)")

    experiment_sub.add_parser("list", help="実行履歴の一覧")

    exp_agg = experiment_sub.add_parser("aggregate", help="結果の集計・統計解析")
    exp_agg.add_argument("run_dir", type=str, help="実行ディレクトリ")

    exp_cmp = experiment_sub.add_parser("compare", help="2つの実行結果を比較")
    exp_cmp.add_argument("run_dirs", nargs="+", type=str, help="比較する実行ディレクトリ（2つ以上）")

    experiment_sub.add_parser("cache-status", help="キャッシュ状況の確認")

    exp_clear = experiment_sub.add_parser("clear-cache", help="キャッシュの削除")
    exp_clear.add_argument("--stage", type=str, default=None,
                           help="削除対象ステージ (analysis|proposals|evaluations)")

    exp_paper = experiment_sub.add_parser("paper-figures", help="論文用クロス実験図表を生成")
    exp_paper.add_argument("--output", type=str, default="experiments/paper_figures",
                           help="出力ディレクトリ (デフォルト: experiments/paper_figures)")
    exp_paper.add_argument("--runs-base", type=str, default="experiments/runs",
                           help="実験結果ディレクトリ (デフォルト: experiments/runs)")
    exp_paper.add_argument("--formats", nargs="+", default=["png", "svg"],
                           help="出力形式 (デフォルト: png svg)")
    exp_paper.add_argument("--paper-ids", nargs="+", default=None,
                           help="描画対象の論文IDリスト")
    exp_paper.add_argument("--exclude-paper-ids", nargs="+", default=None,
                           help="除外する論文IDリスト")

    # evaluate コマンド
    evaluate_parser = subparsers.add_parser("evaluate", help="提案をペアワイズ比較評価")
    evaluate_parser.add_argument(
        "proposals_file",
        type=str,
        help="評価対象のProposalを含むJSONファイル",
    )
    evaluate_parser.add_argument(
        "--format",
        choices=["markdown", "json", "rich"],
        default="rich",
        help="出力形式 (デフォルト: rich)",
    )
    evaluate_parser.add_argument(
        "-o", "--output",
        type=str,
        help="出力ファイルパス（指定しない場合は標準出力）",
    )
    evaluate_parser.add_argument(
        "--no-experiment",
        action="store_true",
        help="実験計画の評価をスキップ",
    )
    evaluate_parser.add_argument(
        "--model",
        type=str,
        help="使用するLLMモデル（デフォルト: 設定ファイルのopenai_model）",
    )
    evaluate_parser.add_argument(
        "--include-target",
        action="store_true",
        help="ターゲット論文のアイデアを比較に含める（ProposalResult形式の入力時のみ）",
    )
    evaluate_parser.add_argument(
        "--mode",
        choices=["pairwise", "single"],
        default="pairwise",
        help="評価モード: pairwise (ペアワイズ比較) / single (独立評価) (デフォルト: pairwise)",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "ingest":
        return cmd_ingest(args)
    elif args.command == "rebuild":
        return cmd_rebuild(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "analyze":
        return cmd_analyze(args)
    elif args.command == "propose":
        return cmd_propose(args)
    elif args.command == "experiment":
        return cmd_experiment(args)
    elif args.command == "evaluate":
        return cmd_evaluate(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
