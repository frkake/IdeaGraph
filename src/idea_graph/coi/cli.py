"""CoI-Agent CLI ラッパー

Chain of Ideas Agent を uv 経由で実行するためのCLIエントリポイント。
.env ファイルから設定を読み込み、CoI-Agent形式の環境変数に変換して実行する。
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


def setup_environment() -> Path:
    """環境変数をCoI-Agent形式で設定し、作業ディレクトリを変更する

    Returns:
        CoI-Agentディレクトリのパス
    """
    from idea_graph.coi.config import COI_AGENT_DIR, coi_settings

    # CoI-Agentのパスをsys.pathに追加（インポート用）
    sys.path.insert(0, str(COI_AGENT_DIR))
    coi_settings.is_azure = False
    # 環境変数設定（CoI-Agentが期待する形式）
    os.environ["SEMENTIC_SEARCH_API_KEY"] = coi_settings.semantic_search_api_key
    # CoI-Agent側は `if is_azure:` のように判定しており、文字列 "false" でも truthy になってしまうため
    # falseの場合は空文字列を渡して falsy として扱われるようにする
    os.environ["is_azure"] = "true" if coi_settings.is_azure else ""
    os.environ["OPENAI_API_KEY"] = coi_settings.openai_api_key
    # OPENAI_BASE_URLが空の場合は環境変数を設定しない（OpenAIクライアントがデフォルトURLを使用する）
    # 空文字列を設定するとクライアントが無効なURLとして解釈してしまう
    if coi_settings.openai_base_url:
        os.environ["OPENAI_BASE_URL"] = coi_settings.openai_base_url
    elif "OPENAI_BASE_URL" in os.environ:
        del os.environ["OPENAI_BASE_URL"]
    os.environ["MAIN_LLM_MODEL"] = coi_settings.main_llm_model
    os.environ["CHEAP_LLM_MODEL"] = coi_settings.cheap_llm_model

    # Azure設定（is_azure=Trueの場合）
    if coi_settings.is_azure:
        os.environ["AZURE_OPENAI_ENDPOINT"] = coi_settings.azure_endpoint
        os.environ["AZURE_OPENAI_KEY"] = coi_settings.azure_key
        os.environ["AZURE_OPENAI_API_VERSION"] = coi_settings.azure_api_version

    # Embedding設定（オプション）
    if coi_settings.embedding_api_key:
        os.environ["EMBEDDING_API_KEY"] = coi_settings.embedding_api_key
    if coi_settings.embedding_api_endpoint:
        os.environ["EMBEDDING_API_ENDPOINT"] = coi_settings.embedding_api_endpoint
    if coi_settings.embedding_model:
        os.environ["EMBEDDING_MODEL"] = coi_settings.embedding_model

    # 作業ディレクトリをCoI-Agentに変更（相対パス参照のため）
    os.chdir(COI_AGENT_DIR)

    return COI_AGENT_DIR


def main() -> int:
    """CoI-Agent CLIエントリポイント"""
    parser = argparse.ArgumentParser(
        description="CoI-Agent: Chain of Ideas Agent - LLMを使った研究アイデア生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run --group coi coi --topic "Using diffusion to generate urban road layout map"
  uv run --group coi coi --topic "Graph neural networks for drug discovery" --max-chain-length 7

前提条件:
  - Grobid (Java) が起動している必要があります（PDF解析用）
  - spaCy英語モデル: uv run --group coi python -m spacy download en_core_web_sm
  - .env に OPENAI_API_KEY が設定されている必要があります
""",
    )
    parser.add_argument(
        "--topic",
        type=str,
        required=True,
        help="研究トピック（必須）",
    )
    parser.add_argument(
        "--anchor-paper-path",
        type=str,
        default=None,
        help="アンカー論文のPDFパス（オプション）",
    )
    parser.add_argument(
        "--save-file",
        type=str,
        default="saves/",
        help="保存先ディレクトリ（デフォルト: saves/）",
    )
    parser.add_argument(
        "--improve-cnt",
        type=int,
        default=1,
        help="実験改善の反復回数（デフォルト: 1）",
    )
    parser.add_argument(
        "--max-chain-length",
        type=int,
        default=5,
        help="アイデアチェーンの最大長（デフォルト: 5）",
    )
    parser.add_argument(
        "--min-chain-length",
        type=int,
        default=3,
        help="アイデアチェーンの最小長（デフォルト: 3）",
    )
    parser.add_argument(
        "--max-chain-numbers",
        type=int,
        default=1,
        help="処理するチェーンの最大数（デフォルト: 1）",
    )
    parser.add_argument(
        "--exclude-anchor-content",
        action="store_true",
        default=False,
        help="アンカー論文の内容をプロンプトから除外する（デフォルト: False）",
    )

    args = parser.parse_args()

    # 環境設定
    coi_dir = setup_environment()
    print(f"CoI-Agent ディレクトリ: {coi_dir}")

    # CoI-Agentのモジュールをインポート（環境設定後）
    import nest_asyncio
    from agents import DeepResearchAgent, ReviewAgent, get_llms

    from prompts.deep_research_agent_prompts import get_deep_final_idea_prompt

    nest_asyncio.apply()

    # LLMの初期化
    print(f"LLMモデル: メイン={os.environ.get('MAIN_LLM_MODEL')}, サブ={os.environ.get('CHEAP_LLM_MODEL')}")
    main_llm, cheap_llm = get_llms()

    # アンカー論文のフィルタリング処理（エージェント初期化前に実行）
    topic = args.topic
    anchor_paper_path = args.anchor_paper_path
    ban_paper: list[str] = []

    if args.exclude_anchor_content and anchor_paper_path:
        from idea_graph.coi.anchor_filter import AnchorFilter, AnchorFilterError

        print(f"\nアンカー論文の内容除外モードで実行します")
        anchor_filter = AnchorFilter()
        try:
            filter_result = anchor_filter.filter_anchor(
                topic=topic,
                anchor_paper_path=anchor_paper_path,
                exclude_anchor_content=True,
            )
            topic = filter_result.topic
            anchor_paper_path = filter_result.anchor_paper_path
            # ban_paper にアンカー論文タイトルを追加
            if filter_result.anchor_title:
                ban_paper = [filter_result.anchor_title]
            print(f"抽出されたタイトル: {filter_result.anchor_title}")
            print(f"処理後のトピック: {topic}")
            print(f"除外対象論文: {ban_paper}")
        except AnchorFilterError as e:
            print(f"エラー: アンカー論文のフィルタリングに失敗しました: {e}")
            return 1

    # エージェント初期化（ban_paperを渡す）
    review_agent = ReviewAgent(
        save_file=args.save_file,
        llm=main_llm,
        cheap_llm=cheap_llm,
    )
    deep_research_agent = DeepResearchAgent(
        llm=main_llm,
        cheap_llm=cheap_llm,
        save_file=args.save_file,
        ban_paper=ban_paper,
        max_chain_length=args.max_chain_length,
        min_chain_length=args.min_chain_length,
        max_chain_numbers=args.max_chain_numbers,
    )

    # アイデア生成
    print(f"\nトピック '{topic}' のアイデアと実験を生成中...")
    print("=" * 60)

    idea, related_experiments, entities, idea_chain, ideas, trend, future, human, year = asyncio.run(
        deep_research_agent.generate_idea_with_chain(topic, anchor_paper_path)
    )
    # 返り値からプロンプトを再構築
    final_prompt = get_deep_final_idea_prompt(
        idea_chains=idea_chain,
        trend=trend,
        idea=None,
        topic=topic,
    )

    print("\nアイデア生成完了。実験計画を生成中...")
    experiment = asyncio.run(
        deep_research_agent.generate_experiment(idea, related_experiments, entities)
    )

    # 実験の改善
    for i in range(args.improve_cnt):
        print(f"\n実験改善 {i + 1}/{args.improve_cnt}...")
        experiment = asyncio.run(
            deep_research_agent.improve_experiment(review_agent, idea, experiment, entities)
        )

    # 結果の保存
    result = {
        "idea": idea,
        "experiment": experiment,
        "related_experiments": related_experiments,
        "entities": entities,
        "idea_chain": idea_chain,
        "ideas": ideas,
        "trend": trend,
        "future": future,
        "year": year,
        "human": human,
        "prompt": final_prompt,
    }

    output_dir = Path(args.save_file)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "result.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("=" * 60)
    print(f"\n完了！結果を保存しました: {output_path}")
    print(f"\nアイデア概要:\n{idea[:500]}..." if len(str(idea)) > 500 else f"\nアイデア概要:\n{idea}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
