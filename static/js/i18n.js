/**
 * IdeaGraph - i18n (Internationalization)
 */

const I18N = {
    currentLang: localStorage.getItem('ideagraph-lang') || 'en',

    translations: {
        ja: {
            // Page title
            'page_title': 'IdeaGraph - AI論文ナレッジグラフ',

            // Tabs
            'tab.explore': '探索',
            'tab.analyze': '分析',
            'tab.propose': '提案',
            'tab.evaluate': '評価',
            'tab.history': '履歴',
            'tab.experiment': '実験',

            // Tab modes (status)
            'mode.explore': '探索モード',
            'mode.analyze': '分析モード',
            'mode.propose': '提案モード',
            'mode.evaluate': '評価モード',
            'mode.history': '履歴モード',
            'mode.experiment': '実験モード',

            // Panel headers
            'panel.analysis_results': '分析結果',
            'panel.research_proposals': '研究提案',
            'panel.proposal_evaluation': '提案評価',
            'panel.history': '履歴',
            'panel.experiment_management': '実験管理',
            'panel.independent_evaluation': '独立評価',
            'panel.close': 'パネルを閉じる',

            // Sidebar sections
            'sidebar.quick_filter': 'クイックフィルター',
            'sidebar.keyword_search': 'キーワード検索',
            'sidebar.cypher_query': 'Cypher クエリ',
            'sidebar.multihop_analysis': 'マルチホップ分析',
            'sidebar.model_settings': 'モデル設定',
            'sidebar.proposal_settings': '提案生成設定',
            'sidebar.selected_node': '選択ノード',
            'sidebar.edge_detail': '引用関係詳細',

            // Filter buttons
            'filter.all': '全て',
            'filter.citation': '引用関係',
            'filter.mention': '言及関係',

            // Search
            'search.placeholder': '論文タイトルやEntity名...',
            'search.button': '検索',
            'search.enter_keyword': 'キーワードを入力してください',
            'search.searching': '検索: "{keyword}"',

            // Cypher query
            'query.execute': 'クエリ実行',
            'query.executing': 'クエリを実行中...',
            'query.error': 'クエリ実行エラー: ',

            // Analysis
            'analysis.paper_id': '論文ID',
            'analysis.paper_id_placeholder': 'ノードをクリックで自動入力',
            'analysis.hop_count': 'ホップ数',
            'analysis.execute': '分析実行',
            'analysis.executing': '分析を実行中...',
            'analysis.complete': '分析完了: {count}のパス',
            'analysis.error': '分析エラー: ',
            'analysis.enter_paper_id': '論文IDを入力してください',
            'analysis.target_paper': '対象論文',
            'analysis.paths': 'パス',
            'analysis.hops': 'ホップ',
            'analysis.discovered_paths': '発見されたパス:',
            'analysis.generate_proposal': '💡 提案を生成',
            'analysis.items': '件',
            'analysis.display_items': '表示{count}件',
            'analysis.no_results': '分析結果がありません',
            'analysis.no_results_hint': '左のサイドバーから論文を選択して\n「分析実行」をクリックしてください',
            'analysis.computed_from_all': '（分析結果全体から算出）',
            'analysis.computed_from_display': '（表示中のパスから算出）',

            // Model settings
            'model.preset': 'プリセット',

            // Proposal settings
            'proposal.count': '生成数',
            'proposal.count_hint': '件（1-10）',

            // Prompt options
            'prompt.settings': 'プロンプト設定',
            'prompt.auto_note': '空欄は分析結果に合わせて自動設定されます。',
            'prompt.output_format': '出力形式',
            'prompt.output_format_help': 'グラフ情報のLLMへの出力形式を選択します。',
            'prompt.scope': 'スコープ',
            'prompt.scope_help': 'パスとk-hop近傍のどちらをプロンプトに含めるかを選択します。',
            'prompt.scope_path_only': 'パスのみ',
            'prompt.scope_k_hop': 'k-hop 近傍',
            'prompt.scope_path_plus_k_hop': 'パス + k-hop',
            'prompt.node_info': 'ノード情報',
            'prompt.node_info_help': 'ノード種別ごとに含めたい情報を選びます。',
            'prompt.edge_info': 'エッジ情報',
            'prompt.edge_info_help': 'エッジ種別ごとに出力する属性を選びます。',
            'prompt.max_paths': 'パス上限',
            'prompt.max_nodes': 'ノード上限',
            'prompt.max_edges': 'エッジ上限',
            'prompt.k_hop_depth': 'k-hop 深さ',
            'prompt.auto_defaults': '空欄時の自動値: パス {paths} / ノード {nodes} / エッジ {edges} / k-hop {khop} {source}',
            'prompt.filtering': 'フィルタリング',
            'prompt.include_target_paper': 'ターゲット論文を含める',
            'prompt.exclude_future_papers': '未来の論文を除外する',
            'prompt.create_prompt': 'プロンプトを作成',
            'prompt.generating': 'プロンプトを生成中...',
            'prompt.not_generated': 'プロンプトが生成されませんでした',
            'prompt.generated': 'プロンプトを生成しました',
            'prompt.generation_error': 'プロンプト生成エラー: ',
            'prompt.invalid_settings': 'プロンプト設定が不正です: ',
            'prompt.run_analysis_first': '先に分析を実行してください',
            'prompt.lines': '行',
            'prompt.chars': '文字',

            // Copy
            'copy.button': 'コピー',
            'copy.preparing': 'コピー準備中',
            'copy.copied': 'コピーしました',
            'copy.no_content': 'コピーするプロンプトがありません',
            'copy.success': 'プロンプトをコピーしました',
            'copy.failed': 'コピーに失敗しました',
            'copy.error': 'コピーに失敗しました: ',

            // Proposal generation
            'proposal.generating': '提案を生成中... (数分かかる場合があります)',
            'proposal.generating_llm': 'LLMで提案を生成中...',
            'proposal.generating_hint': '数分かかる場合があります',
            'proposal.complete': '提案生成完了: {count}件',
            'proposal.error': '提案生成エラー: ',
            'proposal.error_title': '提案生成エラー',
            'proposal.no_proposals': '提案がありません',
            'proposal.no_proposals_hint': '分析を実行してから「提案を生成」をクリックしてください',
            'proposal.generation_prompt': '生成プロンプト',
            'proposal.detail': '詳細',
            'proposal.motivation': '動機',
            'proposal.method': '手法',
            'proposal.rationale': '提案理由',
            'proposal.research_trends': '研究動向',
            'proposal.coi_original': 'CoI原文',
            'proposal.experiment_plan': '実験計画',
            'proposal.datasets': 'データセット',
            'proposal.baselines': 'ベースライン',
            'proposal.metrics': '評価指標',
            'proposal.ablations': 'アブレーション',
            'proposal.expected_results': '期待結果',
            'proposal.failure_interpretation': '失敗時の解釈',
            'proposal.differences': '既存研究との差異',
            'proposal.grounding': '根拠',
            'proposal.related_papers': '関連論文',
            'proposal.related_entities': '関連エンティティ',
            'proposal.knowledge_graph_path': '知識グラフパス',
            'proposal.close': '閉じる',
            'proposal.save': '保存',

            // Evaluation modes
            'eval.pairwise': 'ペアワイズ比較',
            'eval.single': '独立評価',
            'eval.run': '🏆 評価を実行',
            'eval.comparison_view': '比較ビュー',
            'eval.include_target': 'ターゲット論文（{paper}）を比較に含める',

            // Evaluation - pairwise
            'eval.pairwise_title': 'ペアワイズ比較評価',
            'eval.ranked_proposals': '{count}件の提案をランキング',
            'eval.comparisons_done': '{count}回の比較を実施',
            'eval.ranking': 'ランキング:',
            'eval.overall_score': '総合スコア',
            'eval.comparison_details': '比較詳細を表示 ({count}件)',
            'eval.json_export': '📋 JSONエクスポート',
            'eval.md_export': '📄 Markdownエクスポート',
            'eval.no_results': '評価結果がありません',
            'eval.no_results_hint': '提案タブで「評価を実行」をクリックしてください',
            'eval.need_two_or_more': '評価には2件以上のアイデアが必要です（提案 + ターゲット論文）',
            'eval.need_one_or_more': '評価には1件以上の提案が必要です',
            'eval.evaluating': '提案を評価中... (数分かかる場合があります)',
            'eval.evaluating_single': '提案を独立評価中... (数分かかる場合があります)',
            'eval.evaluating_info': '{info}を評価しています',
            'eval.evaluating_single_info': '{info}を独立評価しています',
            'eval.proposals_count': '{count}件の提案',
            'eval.proposals_plus_target': '{count}件の提案 + ターゲット論文',
            'eval.complete': '評価完了: {count}件をランキング',
            'eval.single_complete': '独立評価完了: {count}件をランキング',
            'eval.error': '評価エラー: ',
            'eval.error_title': '評価エラー',
            'eval.error_during': '評価中にエラーが発生しました',
            'eval.no_export_data': 'エクスポートする評価結果がありません',
            'eval.show_reasoning': '評価理由を表示',

            // Evaluation - single
            'eval.single_title': '独立評価',
            'eval.absolute_score': '各指標1-10の絶対スコアで評価',

            // Evaluation progress
            'eval.phase.initializing': '初期化中...',
            'eval.phase.evaluating': 'アイデアを評価中...',
            'eval.phase.extracting_target': 'ターゲット論文を分析中...',
            'eval.phase.comparing': 'ペアワイズ比較を実行中...',
            'eval.phase.calculating_elo': 'ELOレーティングを計算中...',
            'eval.phase.completed': '評価完了！',
            'eval.phase.processing': '処理中...',
            'eval.progress.evaluations': '{current}/{total}件の評価完了',
            'eval.progress.comparisons': '{current}/{total}件の比較完了',
            'eval.progress.extracting_target': 'ターゲット論文からアイデアを抽出中...',

            // Metric labels
            'metric.novelty': '独自性',
            'metric.significance': '重要性',
            'metric.feasibility': '実現可能性',
            'metric.clarity': '明確さ',
            'metric.effectiveness': '有効性',
            'metric.experiment_design': '実験設計',

            // Score breakdown
            'score.cite_importance': '引用重要度',
            'score.cite_type': '引用種別',
            'score.mentions': '言及',
            'score.entity_relation': 'Entity関係',
            'score.length_penalty': '距離ペナルティ',
            'score.breakdown': 'スコア内訳:',
            'score.importance': '重要度',

            // Comparison modal
            'comparison.title': '提案の比較',
            'comparison.need_two': '比較するには2つ以上の提案が必要です',
            'comparison.close': '閉じる',
            'comparison.export': 'エクスポート',
            'comparison.draw': '引分',

            // Source badges
            'source.target': '📄 ターゲット',
            'source.target_paper': '📄 ターゲット論文',

            // Export
            'export.no_proposals': 'エクスポートする提案がありません',
            'export.md.title': '研究提案',
            'export.md.target_paper': '対象論文',
            'export.md.generated_at': '生成日時',
            'export.md.prompt': '生成プロンプト',
            'export.md.proposal_n': '提案 {n}',
            'export.md.eval_title': '提案評価結果',
            'export.md.eval_date': '評価日時',
            'export.md.model': 'モデル',
            'export.md.ranking': 'ランキング',
            'export.md.rank': '順位',
            'export.md.type': 'タイプ',
            'export.md.proposal': '提案',
            'export.md.overall': '総合スコア',
            'export.md.score_detail': 'スコア詳細',
            'export.md.rank_n': '{n}位',
            'export.md.pairwise_results': 'ペアワイズ比較結果',
            'export.md.comparison_n': '比較 {n}',
            'export.md.metric': '指標',
            'export.md.winner': '勝者',
            'export.md.reason': '理由',
            'export.md.type_target': '📄 ターゲット',
            'export.md.type_proposal': '💡 提案',

            // History
            'history.no_history': '保存された履歴がありません',
            'history.no_history_hint': '分析や提案を保存すると\nここに表示されます',
            'history.refresh': '🔄 更新',
            'history.delete_all': '🗑️ 全削除',
            'history.analysis_history': '📊 分析履歴 ({count})',
            'history.proposal_history': '💡 提案履歴 ({count})',
            'history.untitled_proposal': '無題の提案',
            'history.unknown': '不明',
            'history.delete': '削除',
            'history.open_set': '提案セットを開く ({count}件)',
            'history.confirm_delete_analysis': 'この分析履歴を削除しますか？',
            'history.confirm_delete_proposal': 'この提案履歴を削除しますか？',
            'history.confirm_delete_all': '全ての履歴を削除しますか？\nこの操作は取り消せません。',
            'history.delete_failed': '削除に失敗しました',
            'history.analysis_deleted': '分析履歴を削除しました',
            'history.proposal_deleted': '提案履歴を削除しました',
            'history.all_deleted': '全ての履歴を削除しました',
            'history.delete_error': '削除エラー: ',
            'history.load_failed': '読み込みに失敗しました',
            'history.analysis_loaded': '分析を読み込みました: {id}',
            'history.proposal_loaded': '提案を読み込みました: {title}',
            'history.proposal_set_loaded': '提案セットを読み込みました: {id}',
            'history.load_error': '読み込みエラー: ',

            // Save
            'save.failed': '保存に失敗しました',
            'save.analysis_saved': '分析を保存しました (ID: {id})',
            'save.saving_proposals': '提案を保存中...',
            'save.no_proposals': '保存する提案がありません',
            'save.no_paper_id': '論文IDが未設定です',
            'save.proposal_saved': '提案を保存しました (ID: {id})',
            'save.proposals_saved': '提案を保存しました ({count}件)',
            'save.partial_save': '保存完了: {saved}件, 失敗: {failed}件',
            'save.error': '保存エラー: ',

            // Node/Edge info
            'node.label': 'ラベル',
            'node.no_properties': 'プロパティなし',
            'edge.relation_type': '関係タイプ',
            'edge.importance': '重要度',
            'edge.source': '引用元',
            'edge.target': '引用先',
            'edge.context': '引用コンテキスト',
            'edge.no_info': '情報なし',
            'edge.not_rated': '未評価',

            // Graph
            'graph.loading': 'グラフを読み込み中...',
            'graph.loaded': '読み込み完了',
            'graph.stats': 'ノード: {nodes}, エッジ: {edges}',
            'graph.init_failed': 'グラフの初期化に失敗しました: ',
            'graph.filter': 'フィルター: {type}',
            'graph.neo4j_password': 'Neo4jパスワードを入力してください:',
            'graph.ready': '準備完了',

            // Path detail
            'path.detail': 'パス #{n} 詳細',
            'path.score': 'スコア',
            'path.unknown': '不明',
            'path.nodes_not_found': 'パスのノードがグラフ上に見つかりません',
            'path.highlight': 'パス: {matched}/{total}ノードをハイライト',
            'path.reset_highlight': '🔄 ハイライト解除',
            'path.highlight_reset': 'ハイライトを解除しました',

            // CoI
            'coi.section_title': '🔗 CoI（Chain-of-Ideas）で比較',
            'coi.description': 'Chain-of-Ideasを実行してIdeaGraphと比較します。実行には数分〜十数分かかります。',
            'coi.date_filter': '出版日フィルタ（空なら自動取得）:',
            'coi.run': '🚀 CoIを実行',
            'coi.running': '実行中...',
            'coi.load_result': '📂 結果を読み込み',
            'coi.running_progress': 'Chain-of-Ideasを実行中...',
            'coi.initializing': '初期化中...',
            'coi.complete': 'CoI実行完了。変換中...',
            'coi.error': 'CoIエラー: ',
            'coi.exec_error': 'CoI実行エラー: ',
            'coi.no_result': '変換するCoI結果がありません',
            'coi.added': 'CoI提案を追加しました',
            'coi.added_simple': 'CoI提案を追加しました（簡易表示）',
            'coi.convert_error': '変換エラー（簡易表示に切り替え）: ',
            'coi.converting': 'CoI結果を変換中...',
            'coi.select_paper': 'CoIを実行するには、まず分析対象の論文を選択してください',
            'coi.load_title': 'CoI結果の読み込み',
            'coi.load_description': '既存のCoI実行結果（result.json）を読み込んでProposal形式に変換します。',
            'coi.load_path_label': 'result.jsonのパス:',
            'coi.enter_path': 'パスを入力してください',
            'coi.cancel': 'キャンセル',
            'coi.load': '読み込み',

            // Experiment tab
            'experiment.run': '実験実行',
            'experiment.run_history': '実行履歴',
            'experiment.paper_figures': '論文図表',
            'experiment.cache': 'キャッシュ',
            'experiment.loading': '読み込み中...',
            'experiment.no_configs': '設定ファイルがありません',
            'experiment.no_runs': '実行履歴がありません',
            'experiment.no_cache': 'キャッシュは空です',
            'experiment.timestamp': 'タイムスタンプ',
            'experiment.summary': 'サマリー',
            'experiment.figures': '図',
            'experiment.actions': '操作',
            'experiment.detail': '詳細',
            'experiment.back_to_list': '← 一覧に戻る',
            'experiment.score_summary': 'スコアサマリー',
            'experiment.condition': '条件',
            'experiment.metric': '指標',
            'experiment.n': 'N',
            'experiment.mean': '平均',
            'experiment.std': '標準偏差',
            'experiment.stat_test': '統計検定結果',
            'experiment.comparison': '比較',
            'experiment.p_value': 'p値',
            'experiment.significant': '有意',
            'experiment.not_significant': 'n.s.',
            'experiment.charts': 'チャート',
            'experiment.report': 'レポート',
            'experiment.num_papers': '論文数',
            'experiment.num_conditions': '条件数',
            'experiment.evaluation': '評価',
            'experiment.execute': '実行',
            'experiment.executing': '実行中...',
            'experiment.running': '実験実行中...',
            'experiment.complete': '実験完了: ',
            'experiment.error': '実験エラー: ',
            'experiment.stage': 'ステージ',
            'experiment.count': '件数',
            'experiment.total': '合計',
            'experiment.cache_clear': 'キャッシュクリア',
            'experiment.confirm_cache_clear': '実験キャッシュを全て削除しますか？',
            'experiment.cache_cleared': 'キャッシュクリア: {count}件削除',
            'experiment.cache_clear_error': 'キャッシュクリアエラー: ',
            'experiment.generate_figures': '論文図表を生成',
            'experiment.generating_figures': '生成中...',
            'experiment.figures_generated': '論文図表を{count}件生成しました',
            'experiment.figures_error': '論文図表生成エラー: ',
            'experiment.no_figures': '論文図表がありません。「論文図表を生成」ボタンで生成してください。',
            'experiment.latex_tables': 'LaTeX テーブル',
            'experiment.copied': 'コピー済み',

            // Categories
            'category.system_effectiveness': 'システム有効性',
            'category.ablation': 'アブレーション',
            'category.comparison': '比較',
            'category.evaluation_validity': '評価妥当性',
            'category.other': 'その他',

            // Field labels
            'field.paper_title': '論文タイトル',
            'field.paper_summary': '論文要約',
            'field.paper_claims': '論文の主張',
            'field.entity_type': 'Entity種別',
            'field.entity_description': 'Entity説明',
            'field.relation_type': '関係タイプ',
            'field.citation_type': '引用種別',
            'field.importance': '重要度',
            'field.context': '文脈',

            // Generic
            'generic.none': 'なし',
            'generic.error': 'エラー: ',
            'generic.loading': '読み込み中...',
        },

        en: {
            // Page title
            'page_title': 'IdeaGraph - AI Paper Knowledge Graph',

            // Tabs
            'tab.explore': 'Explore',
            'tab.analyze': 'Analyze',
            'tab.propose': 'Propose',
            'tab.evaluate': 'Evaluate',
            'tab.history': 'History',
            'tab.experiment': 'Experiment',

            // Tab modes (status)
            'mode.explore': 'Explore Mode',
            'mode.analyze': 'Analyze Mode',
            'mode.propose': 'Propose Mode',
            'mode.evaluate': 'Evaluate Mode',
            'mode.history': 'History Mode',
            'mode.experiment': 'Experiment Mode',

            // Panel headers
            'panel.analysis_results': 'Analysis Results',
            'panel.research_proposals': 'Research Proposals',
            'panel.proposal_evaluation': 'Proposal Evaluation',
            'panel.history': 'History',
            'panel.experiment_management': 'Experiment Management',
            'panel.independent_evaluation': 'Independent Evaluation',
            'panel.close': 'Close panel',

            // Sidebar sections
            'sidebar.quick_filter': 'Quick Filter',
            'sidebar.keyword_search': 'Keyword Search',
            'sidebar.cypher_query': 'Cypher Query',
            'sidebar.multihop_analysis': 'Multi-hop Analysis',
            'sidebar.model_settings': 'Model Settings',
            'sidebar.proposal_settings': 'Proposal Settings',
            'sidebar.selected_node': 'Selected Node',
            'sidebar.edge_detail': 'Edge Detail',

            // Filter buttons
            'filter.all': 'All',
            'filter.citation': 'Citations',
            'filter.mention': 'Mentions',

            // Search
            'search.placeholder': 'Paper title or Entity name...',
            'search.button': 'Search',
            'search.enter_keyword': 'Please enter a keyword',
            'search.searching': 'Search: "{keyword}"',

            // Cypher query
            'query.execute': 'Run Query',
            'query.executing': 'Executing query...',
            'query.error': 'Query error: ',

            // Analysis
            'analysis.paper_id': 'Paper ID',
            'analysis.paper_id_placeholder': 'Click a node to auto-fill',
            'analysis.hop_count': 'Hop Count',
            'analysis.execute': 'Run Analysis',
            'analysis.executing': 'Running analysis...',
            'analysis.complete': 'Analysis complete: {count} paths',
            'analysis.error': 'Analysis error: ',
            'analysis.enter_paper_id': 'Please enter a paper ID',
            'analysis.target_paper': 'Target Paper',
            'analysis.paths': 'paths',
            'analysis.hops': 'hops',
            'analysis.discovered_paths': 'Discovered paths:',
            'analysis.generate_proposal': '💡 Generate Proposals',
            'analysis.items': ' items',
            'analysis.display_items': 'showing {count}',
            'analysis.no_results': 'No analysis results',
            'analysis.no_results_hint': 'Select a paper from the sidebar\nand click "Run Analysis"',
            'analysis.computed_from_all': '(computed from all results)',
            'analysis.computed_from_display': '(computed from displayed paths)',

            // Model settings
            'model.preset': 'Preset',

            // Proposal settings
            'proposal.count': 'Count',
            'proposal.count_hint': ' (1-10)',

            // Prompt options
            'prompt.settings': 'Prompt Settings',
            'prompt.auto_note': 'Empty fields are automatically set based on analysis results.',
            'prompt.output_format': 'Output Format',
            'prompt.output_format_help': 'Select the output format for graph information to the LLM.',
            'prompt.scope': 'Scope',
            'prompt.scope_help': 'Select whether to include paths or k-hop neighbors in the prompt.',
            'prompt.scope_path_only': 'Paths only',
            'prompt.scope_k_hop': 'k-hop neighbors',
            'prompt.scope_path_plus_k_hop': 'Paths + k-hop',
            'prompt.node_info': 'Node Info',
            'prompt.node_info_help': 'Select info to include for each node type.',
            'prompt.edge_info': 'Edge Info',
            'prompt.edge_info_help': 'Select attributes to output for each edge type.',
            'prompt.max_paths': 'Max Paths',
            'prompt.max_nodes': 'Max Nodes',
            'prompt.max_edges': 'Max Edges',
            'prompt.k_hop_depth': 'k-hop Depth',
            'prompt.auto_defaults': 'Auto defaults: Paths {paths} / Nodes {nodes} / Edges {edges} / k-hop {khop} {source}',
            'prompt.filtering': 'Filtering',
            'prompt.include_target_paper': 'Include target paper',
            'prompt.exclude_future_papers': 'Exclude future papers',
            'prompt.create_prompt': 'Create Prompt',
            'prompt.generating': 'Generating prompt...',
            'prompt.not_generated': 'Prompt was not generated',
            'prompt.generated': 'Prompt generated',
            'prompt.generation_error': 'Prompt generation error: ',
            'prompt.invalid_settings': 'Invalid prompt settings: ',
            'prompt.run_analysis_first': 'Please run analysis first',
            'prompt.lines': 'lines',
            'prompt.chars': 'chars',

            // Copy
            'copy.button': 'Copy',
            'copy.preparing': 'Preparing...',
            'copy.copied': 'Copied!',
            'copy.no_content': 'No prompt to copy',
            'copy.success': 'Prompt copied',
            'copy.failed': 'Copy failed',
            'copy.error': 'Copy failed: ',

            // Proposal generation
            'proposal.generating': 'Generating proposals... (may take a few minutes)',
            'proposal.generating_llm': 'Generating proposals with LLM...',
            'proposal.generating_hint': 'This may take a few minutes',
            'proposal.complete': 'Proposal generation complete: {count} items',
            'proposal.error': 'Proposal generation error: ',
            'proposal.error_title': 'Proposal Generation Error',
            'proposal.no_proposals': 'No proposals',
            'proposal.no_proposals_hint': 'Run analysis first, then click "Generate Proposals"',
            'proposal.generation_prompt': 'Generation Prompt',
            'proposal.detail': 'Details',
            'proposal.motivation': 'Motivation',
            'proposal.method': 'Method',
            'proposal.rationale': 'Rationale',
            'proposal.research_trends': 'Research Trends',
            'proposal.coi_original': 'CoI Original',
            'proposal.experiment_plan': 'Experiment Plan',
            'proposal.datasets': 'Datasets',
            'proposal.baselines': 'Baselines',
            'proposal.metrics': 'Metrics',
            'proposal.ablations': 'Ablations',
            'proposal.expected_results': 'Expected Results',
            'proposal.failure_interpretation': 'Failure Interpretation',
            'proposal.differences': 'Differences from Existing Work',
            'proposal.grounding': 'Grounding',
            'proposal.related_papers': 'Related Papers',
            'proposal.related_entities': 'Related Entities',
            'proposal.knowledge_graph_path': 'Knowledge Graph Path',
            'proposal.close': 'Close',
            'proposal.save': 'Save',

            // Evaluation modes
            'eval.pairwise': 'Pairwise Comparison',
            'eval.single': 'Independent Evaluation',
            'eval.run': '🏆 Run Evaluation',
            'eval.comparison_view': 'Compare',
            'eval.include_target': 'Include target paper ({paper}) in comparison',

            // Evaluation - pairwise
            'eval.pairwise_title': 'Pairwise Comparison',
            'eval.ranked_proposals': '{count} proposals ranked',
            'eval.comparisons_done': '{count} comparisons performed',
            'eval.ranking': 'Ranking:',
            'eval.overall_score': 'Overall Score',
            'eval.comparison_details': 'Show comparison details ({count})',
            'eval.json_export': '📋 JSON Export',
            'eval.md_export': '📄 Markdown Export',
            'eval.no_results': 'No evaluation results',
            'eval.no_results_hint': 'Click "Run Evaluation" in the Propose tab',
            'eval.need_two_or_more': 'At least 2 ideas required (proposals + target paper)',
            'eval.need_one_or_more': 'At least 1 proposal required',
            'eval.evaluating': 'Evaluating proposals... (may take a few minutes)',
            'eval.evaluating_single': 'Running independent evaluation... (may take a few minutes)',
            'eval.evaluating_info': 'Evaluating {info}',
            'eval.evaluating_single_info': 'Running independent evaluation on {info}',
            'eval.proposals_count': '{count} proposals',
            'eval.proposals_plus_target': '{count} proposals + target paper',
            'eval.complete': 'Evaluation complete: {count} ranked',
            'eval.single_complete': 'Independent evaluation complete: {count} ranked',
            'eval.error': 'Evaluation error: ',
            'eval.error_title': 'Evaluation Error',
            'eval.error_during': 'An error occurred during evaluation',
            'eval.no_export_data': 'No evaluation results to export',
            'eval.show_reasoning': 'Show reasoning',

            // Evaluation - single
            'eval.single_title': 'Independent Evaluation',
            'eval.absolute_score': 'Absolute scores (1-10) per metric',

            // Evaluation progress
            'eval.phase.initializing': 'Initializing...',
            'eval.phase.evaluating': 'Evaluating ideas...',
            'eval.phase.extracting_target': 'Analyzing target paper...',
            'eval.phase.comparing': 'Running pairwise comparisons...',
            'eval.phase.calculating_elo': 'Calculating ELO ratings...',
            'eval.phase.completed': 'Evaluation complete!',
            'eval.phase.processing': 'Processing...',
            'eval.progress.evaluations': '{current}/{total} evaluations completed',
            'eval.progress.comparisons': '{current}/{total} comparisons completed',
            'eval.progress.extracting_target': 'Extracting ideas from target paper...',

            // Metric labels
            'metric.novelty': 'Novelty',
            'metric.significance': 'Significance',
            'metric.feasibility': 'Feasibility',
            'metric.clarity': 'Clarity',
            'metric.effectiveness': 'Effectiveness',
            'metric.experiment_design': 'Experiment Design',

            // Score breakdown
            'score.cite_importance': 'Citation Importance',
            'score.cite_type': 'Citation Type',
            'score.mentions': 'Mentions',
            'score.entity_relation': 'Entity Relation',
            'score.length_penalty': 'Length Penalty',
            'score.breakdown': 'Score Breakdown:',
            'score.importance': 'Importance',

            // Comparison modal
            'comparison.title': 'Compare Proposals',
            'comparison.need_two': 'Need 2 or more proposals to compare',
            'comparison.close': 'Close',
            'comparison.export': 'Export',
            'comparison.draw': 'Draw',

            // Source badges
            'source.target': '📄 Target',
            'source.target_paper': '📄 Target Paper',

            // Export
            'export.no_proposals': 'No proposals to export',
            'export.md.title': 'Research Proposals',
            'export.md.target_paper': 'Target Paper',
            'export.md.generated_at': 'Generated at',
            'export.md.prompt': 'Generation Prompt',
            'export.md.proposal_n': 'Proposal {n}',
            'export.md.eval_title': 'Proposal Evaluation Results',
            'export.md.eval_date': 'Evaluated at',
            'export.md.model': 'Model',
            'export.md.ranking': 'Ranking',
            'export.md.rank': 'Rank',
            'export.md.type': 'Type',
            'export.md.proposal': 'Proposal',
            'export.md.overall': 'Overall Score',
            'export.md.score_detail': 'Score Details',
            'export.md.rank_n': '#{n}',
            'export.md.pairwise_results': 'Pairwise Comparison Results',
            'export.md.comparison_n': 'Comparison {n}',
            'export.md.metric': 'Metric',
            'export.md.winner': 'Winner',
            'export.md.reason': 'Reason',
            'export.md.type_target': '📄 Target',
            'export.md.type_proposal': '💡 Proposal',

            // History
            'history.no_history': 'No saved history',
            'history.no_history_hint': 'Saved analyses and proposals\nwill appear here',
            'history.refresh': '🔄 Refresh',
            'history.delete_all': '🗑️ Delete All',
            'history.analysis_history': '📊 Analysis History ({count})',
            'history.proposal_history': '💡 Proposal History ({count})',
            'history.untitled_proposal': 'Untitled Proposal',
            'history.unknown': 'Unknown',
            'history.delete': 'Delete',
            'history.open_set': 'Open proposal set ({count})',
            'history.confirm_delete_analysis': 'Delete this analysis?',
            'history.confirm_delete_proposal': 'Delete this proposal?',
            'history.confirm_delete_all': 'Delete all history?\nThis action cannot be undone.',
            'history.delete_failed': 'Delete failed',
            'history.analysis_deleted': 'Analysis deleted',
            'history.proposal_deleted': 'Proposal deleted',
            'history.all_deleted': 'All history deleted',
            'history.delete_error': 'Delete error: ',
            'history.load_failed': 'Load failed',
            'history.analysis_loaded': 'Analysis loaded: {id}',
            'history.proposal_loaded': 'Proposal loaded: {title}',
            'history.proposal_set_loaded': 'Proposal set loaded: {id}',
            'history.load_error': 'Load error: ',

            // Save
            'save.failed': 'Save failed',
            'save.analysis_saved': 'Analysis saved (ID: {id})',
            'save.saving_proposals': 'Saving proposals...',
            'save.no_proposals': 'No proposals to save',
            'save.no_paper_id': 'Paper ID not set',
            'save.proposal_saved': 'Proposal saved (ID: {id})',
            'save.proposals_saved': 'Proposals saved ({count})',
            'save.partial_save': 'Save complete: {saved} saved, {failed} failed',
            'save.error': 'Save error: ',

            // Node/Edge info
            'node.label': 'Label',
            'node.no_properties': 'No properties',
            'edge.relation_type': 'Relation Type',
            'edge.importance': 'Importance',
            'edge.source': 'Source',
            'edge.target': 'Target',
            'edge.context': 'Citation Context',
            'edge.no_info': 'No info',
            'edge.not_rated': 'Not rated',

            // Graph
            'graph.loading': 'Loading graph...',
            'graph.loaded': 'Loaded',
            'graph.stats': 'Nodes: {nodes}, Edges: {edges}',
            'graph.init_failed': 'Graph initialization failed: ',
            'graph.filter': 'Filter: {type}',
            'graph.neo4j_password': 'Enter Neo4j password:',
            'graph.ready': 'Ready',

            // Path detail
            'path.detail': 'Path #{n} Detail',
            'path.score': 'Score',
            'path.unknown': 'Unknown',
            'path.nodes_not_found': 'Path nodes not found on graph',
            'path.highlight': 'Path: {matched}/{total} nodes highlighted',
            'path.reset_highlight': '🔄 Reset Highlight',
            'path.highlight_reset': 'Highlight reset',

            // CoI
            'coi.section_title': '🔗 Compare with CoI (Chain-of-Ideas)',
            'coi.description': 'Run Chain-of-Ideas and compare with IdeaGraph. This may take several minutes.',
            'coi.date_filter': 'Publication date filter (empty for auto):',
            'coi.run': '🚀 Run CoI',
            'coi.running': 'Running...',
            'coi.load_result': '📂 Load Result',
            'coi.running_progress': 'Running Chain-of-Ideas...',
            'coi.initializing': 'Initializing...',
            'coi.complete': 'CoI complete. Converting...',
            'coi.error': 'CoI error: ',
            'coi.exec_error': 'CoI execution error: ',
            'coi.no_result': 'No CoI result to convert',
            'coi.added': 'CoI proposal added',
            'coi.added_simple': 'CoI proposal added (simplified)',
            'coi.convert_error': 'Conversion error (using simplified view): ',
            'coi.converting': 'Converting CoI result...',
            'coi.select_paper': 'Please select a target paper first to run CoI',
            'coi.load_title': 'Load CoI Result',
            'coi.load_description': 'Load an existing CoI result (result.json) and convert it to Proposal format.',
            'coi.load_path_label': 'Path to result.json:',
            'coi.enter_path': 'Please enter a path',
            'coi.cancel': 'Cancel',
            'coi.load': 'Load',

            // Experiment tab
            'experiment.run': 'Run Experiment',
            'experiment.run_history': 'Run History',
            'experiment.paper_figures': 'Paper Figures',
            'experiment.cache': 'Cache',
            'experiment.loading': 'Loading...',
            'experiment.no_configs': 'No config files',
            'experiment.no_runs': 'No run history',
            'experiment.no_cache': 'Cache is empty',
            'experiment.timestamp': 'Timestamp',
            'experiment.summary': 'Summary',
            'experiment.figures': 'Figures',
            'experiment.actions': 'Actions',
            'experiment.detail': 'Detail',
            'experiment.back_to_list': '← Back to list',
            'experiment.score_summary': 'Score Summary',
            'experiment.condition': 'Condition',
            'experiment.metric': 'Metric',
            'experiment.n': 'N',
            'experiment.mean': 'Mean',
            'experiment.std': 'Std Dev',
            'experiment.stat_test': 'Statistical Tests',
            'experiment.comparison': 'Comparison',
            'experiment.p_value': 'p-value',
            'experiment.significant': 'Significant',
            'experiment.not_significant': 'n.s.',
            'experiment.charts': 'Charts',
            'experiment.report': 'Report',
            'experiment.num_papers': 'Papers',
            'experiment.num_conditions': 'Conditions',
            'experiment.evaluation': 'Eval',
            'experiment.execute': 'Run',
            'experiment.executing': 'Running...',
            'experiment.running': 'Running experiment...',
            'experiment.complete': 'Experiment complete: ',
            'experiment.error': 'Experiment error: ',
            'experiment.stage': 'Stage',
            'experiment.count': 'Count',
            'experiment.total': 'Total',
            'experiment.cache_clear': 'Clear Cache',
            'experiment.confirm_cache_clear': 'Delete all experiment cache?',
            'experiment.cache_cleared': 'Cache cleared: {count} items deleted',
            'experiment.cache_clear_error': 'Cache clear error: ',
            'experiment.generate_figures': 'Generate Paper Figures',
            'experiment.generating_figures': 'Generating...',
            'experiment.figures_generated': '{count} paper figures generated',
            'experiment.figures_error': 'Figure generation error: ',
            'experiment.no_figures': 'No paper figures. Click "Generate Paper Figures" to create them.',
            'experiment.latex_tables': 'LaTeX Tables',
            'experiment.copied': 'Copied!',

            // Categories
            'category.system_effectiveness': 'System Effectiveness',
            'category.ablation': 'Ablation',
            'category.comparison': 'Comparison',
            'category.evaluation_validity': 'Evaluation Validity',
            'category.other': 'Other',

            // Field labels
            'field.paper_title': 'Paper Title',
            'field.paper_summary': 'Paper Summary',
            'field.paper_claims': 'Paper Claims',
            'field.entity_type': 'Entity Type',
            'field.entity_description': 'Entity Description',
            'field.relation_type': 'Relation Type',
            'field.citation_type': 'Citation Type',
            'field.importance': 'Importance',
            'field.context': 'Context',

            // Generic
            'generic.none': 'None',
            'generic.error': 'Error: ',
            'generic.loading': 'Loading...',
        },
    },

    /**
     * Get translated string with optional interpolation.
     * Usage: t('key') or t('key', {count: 5})
     */
    t(key, params) {
        const lang = this.translations[this.currentLang] || this.translations.ja;
        let text = lang[key];
        if (text === undefined) {
            // Fallback to Japanese
            text = this.translations.ja[key];
        }
        if (text === undefined) {
            return key;
        }
        if (params) {
            for (const [k, v] of Object.entries(params)) {
                text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
            }
        }
        return text;
    },

    /**
     * Get metric label
     */
    metricLabel(metric) {
        return this.t(`metric.${metric}`) || metric;
    },

    /**
     * Set language and persist
     */
    setLang(lang) {
        if (!this.translations[lang]) return;
        this.currentLang = lang;
        localStorage.setItem('ideagraph-lang', lang);
        document.documentElement.lang = lang;
        this.updateStaticElements();
    },

    /**
     * Update static HTML elements with data-i18n attributes
     */
    updateStaticElements() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = this.t(key);
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            el.placeholder = this.t(key);
        });
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.title = this.t(key);
        });
        // Update page title
        document.title = this.t('page_title');
        // Update language switcher active state
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === this.currentLang);
        });
    },
};

// Global shortcut
function t(key, params) {
    return I18N.t(key, params);
}
