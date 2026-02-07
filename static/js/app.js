/**
 * IdeaGraph - メインアプリケーション
 */

// ========== プロンプト設定の定義 ==========
const PAPER_FIELD_OPTIONS = [
    { value: 'paper_title', label: '論文タイトル' },
    { value: 'paper_summary', label: '論文要約' },
    { value: 'paper_claims', label: '論文の主張' },
];

const ENTITY_FIELD_OPTIONS = [
    { value: 'entity_type', label: 'Entity種別' },
    { value: 'entity_description', label: 'Entity説明' },
];

const EDGE_FIELD_OPTIONS = {
    CITES: [
        { value: 'type', label: '関係タイプ' },
        { value: 'citation_type', label: '引用種別' },
        { value: 'importance_score', label: '重要度' },
        { value: 'context', label: '文脈' },
    ],
    MENTIONS: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
    USES: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
    EXTENDS: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
    COMPARES: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
    ENABLES: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
    IMPROVES: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
    ADDRESSES: [
        { value: 'type', label: '関係タイプ' },
        { value: 'context', label: '文脈' },
    ],
};

function buildDefaultNodeTypeFields() {
    return {
        Paper: PAPER_FIELD_OPTIONS.map(option => option.value),
        Entity: ENTITY_FIELD_OPTIONS.map(option => option.value),
    };
}

function buildDefaultEdgeTypeFields() {
    return Object.fromEntries(
        Object.entries(EDGE_FIELD_OPTIONS).map(([edgeType, options]) => [
            edgeType,
            options.map(option => option.value),
        ])
    );
}

// ========== モデルプリセット ==========
const MODEL_PRESETS = {
    gpt4o: {
        label: 'GPT-4o',
        coi_main: 'gpt-4o-2024-11-20',
        coi_cheap: 'gpt-4o-mini-2024-07-18',
        ideagraph: 'gpt-4o-2024-11-20',
    },
    gpt5: {
        label: 'GPT-5',
        coi_main: 'gpt-5-2025-08-07',
        coi_cheap: 'gpt-5-mini-2025-08-07',
        ideagraph: 'gpt-5-2025-08-07',
    },
};

function getSelectedModels() {
    const el = document.getElementById('modelPreset');
    const key = el ? el.value : 'gpt5';
    return MODEL_PRESETS[key] || MODEL_PRESETS.gpt5;
}

function onModelPresetChange() {
    const models = getSelectedModels();
    const detailsEl = document.getElementById('modelPresetDetails');
    if (detailsEl) {
        detailsEl.textContent = `CoI: ${models.coi_main} / ${models.coi_cheap}  |  IdeaGraph: ${models.ideagraph}`;
    }
}

// ========== グローバル状態 ==========
const AppState = {
    viz: null,
    neo4jPassword: null,
    currentTab: 'explore',
    selectedPaperId: null,
    selectedPaperTitle: null,
    analysisId: null,
    analysisResult: null,
    proposals: [],
    proposalPrompt: '',
    promptOptions: {
        graph_format: 'mermaid',
        scope: 'path_plus_k_hop',
        node_type_fields: buildDefaultNodeTypeFields(),
        edge_type_fields: buildDefaultEdgeTypeFields(),
        max_paths: null,
        max_nodes: null,
        max_edges: null,
        neighbor_k: null,
        include_inline_edges: true,
    },
    evaluationResult: null,
    singleEvaluationResult: null,
    evaluationMode: 'pairwise',  // 'pairwise' or 'single'
    savedAnalyses: [],
    savedProposals: [],
    savedProposalGroups: [],
    savedProposalGroupIndexByKey: {},
    // CoI関連
    proposalSources: {},     // proposal_index -> 'ideagraph' | 'coi' | 'target_paper'
    coiRunning: false,       // CoI実行中フラグ
    coiResult: null,         // CoI実行結果
};

// ========== 定数 ==========
const ENTITY_COLORS = {
    'Method': '#FF9800',
    'Approach': '#FFC107',
    'Framework': '#8BC34A',
    'Finding': '#03A9F4',
    'Dataset': '#9C27B0',
    'Benchmark': '#00BCD4',
    'Task': '#E91E63',
    'Challenge': '#F44336',
    'Metric': '#795548',
    'Representation': '#3F51B5',
    'Feature': '#009688',
};
const DEFAULT_ENTITY_COLOR = '#7CB342';

const CITATION_TYPE_COLORS = {
    'EXTENDS': '#FF5722',
    'COMPARES': '#2196F3',
    'USES': '#4CAF50',
    'BACKGROUND': '#9E9E9E',
    'MENTIONS': '#607D8B',
};
const DEFAULT_CITATION_COLOR = '#607D8B';
const ANALYSIS_DISPLAY_LIMIT = 20;

const FILTER_QUERIES = {
    'all': 'MATCH (p:Paper)-[r]->(n) RETURN p, r, n LIMIT 100',
    'papers': 'MATCH (p:Paper)-[r:CITES]->(q:Paper) RETURN p, r, q LIMIT 100',
    'method': 'MATCH (p:Paper)-[r:MENTIONS]->(e:Entity {type: "Method"}) RETURN p, r, e LIMIT 100',
    'dataset': 'MATCH (p:Paper)-[r:MENTIONS]->(e:Entity {type: "Dataset"}) RETURN p, r, e LIMIT 100',
    'benchmark': 'MATCH (p:Paper)-[r:MENTIONS]->(e:Entity {type: "Benchmark"}) RETURN p, r, e LIMIT 100',
    'task': 'MATCH (p:Paper)-[r:MENTIONS]->(e:Entity {type: "Task"}) RETURN p, r, e LIMIT 100',
    'cites': 'MATCH (p:Paper)-[r:CITES]->(q:Paper) RETURN p, r, q LIMIT 100',
    'mentions': 'MATCH (p:Paper)-[r:MENTIONS]->(e:Entity) RETURN p, r, e LIMIT 100',
};

// ========== ユーティリティ ==========
function getNumProposals() {
    const el = document.getElementById('numProposals');
    if (!el) return 1;
    const value = parseInt(el.value, 10);
    if (Number.isNaN(value) || value < 1) return 1;
    if (value > 10) return 10;
    return value;
}

function getEntityColor(type) {
    return ENTITY_COLORS[type] || DEFAULT_ENTITY_COLOR;
}

function getCitationColor(citationType) {
    return CITATION_TYPE_COLORS[citationType] || DEFAULT_CITATION_COLOR;
}

function truncateText(text, maxLength) {
    if (!text) return '';
    return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
}

function escapeHtml(text) {
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatInlineList(items) {
    if (!Array.isArray(items) || items.length === 0) return 'なし';
    return items.map(item => escapeHtml(item)).join(', ');
}

function renderList(items, emptyLabel) {
    if (!Array.isArray(items) || items.length === 0) {
        return `<div class="detail-empty">${escapeHtml(emptyLabel || 'なし')}</div>`;
    }
    return `
        <ul class="detail-list">
            ${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}
        </ul>
    `;
}

function renderTextBlock(text, emptyLabel) {
    if (!text) {
        return `<div class="detail-empty">${escapeHtml(emptyLabel || 'なし')}</div>`;
    }
    return `<p class="proposal-detail-text">${escapeHtml(text)}</p>`;
}

function getProposalSourceFromType(proposalType) {
    switch (proposalType) {
        case 'coi':
        case 'chain-of-ideas':
            return 'coi';
        case 'target':
            return 'target_paper';
        case 'idea-graph':
            return 'ideagraph';
        default:
            return 'ideagraph';
    }
}

function getProposalTypeFromSource(source) {
    switch (source) {
        case 'coi':
            return 'coi';
        case 'target_paper':
            return 'target';
        default:
            return 'idea-graph';
    }
}

function buildCoIMetadata(coiResult) {
    if (!coiResult) return null;
    return {
        idea: coiResult.idea || '',
        idea_chain: coiResult.idea_chain || '',
        experiment: coiResult.experiment || '',
        related_experiments: Array.isArray(coiResult.related_experiments) ? coiResult.related_experiments : [],
        entities: coiResult.entities || '',
        trend: coiResult.trend || '',
        future: coiResult.future || '',
        year: Array.isArray(coiResult.year) ? coiResult.year : [],
        prompt: coiResult.prompt || '',
    };
}

function getProposalPromptForSave(proposal, source) {
    if (source === 'coi') {
        return proposal?.coi?.prompt || null;
    }
    return AppState.proposalPrompt || null;
}

function getTargetPaperIdForSave() {
    return AppState.selectedPaperId || AppState.selectedPaperTitle || '';
}

function extractTitleFromIdea(ideaText) {
    if (!ideaText) return '';
    const lines = String(ideaText).split('\n');
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        if (trimmed.toLowerCase().startsWith('title:')) {
            return trimmed.slice(6).trim();
        }
        if (trimmed.startsWith('#')) {
            return trimmed.replace(/^#+\s*/, '').trim();
        }
    }
    for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed) return trimmed.slice(0, 80);
    }
    return '';
}

function buildCoIFallbackProposal(coiResult) {
    const idea = coiResult?.idea || '';
    const experimentText = coiResult?.experiment || '';
    const title = extractTitleFromIdea(idea) || 'CoI Research Idea';
    return {
        title: title,
        rationale: 'Generated by CoI-Agent.',
        research_trends: coiResult?.trend || '',
        motivation: idea || 'CoI idea not provided.',
        method: experimentText || idea || 'See CoI idea.',
        experiment: {
            datasets: [],
            baselines: [],
            metrics: [],
            ablations: [],
            expected_results: experimentText || 'Not provided.',
            failure_interpretation: 'Not provided.',
        },
        grounding: {
            papers: [],
            entities: [],
            path_mermaid: '',
        },
        differences: [],
        coi: buildCoIMetadata(coiResult),
    };
}

async function appendCoIProposal(proposal, statusMessage) {
    if (!Array.isArray(AppState.proposals)) {
        AppState.proposals = [];
    }
    const newIndex = AppState.proposals.length;
    AppState.proposals.push(proposal);
    AppState.proposalSources[newIndex] = 'coi';
    updateStatus(statusMessage || 'CoI提案を追加しました');
    renderProposals();
    await saveProposal(newIndex);
    return newIndex;
}

function collectTypeFieldSelections(selector, typeAttr) {
    const selections = {};
    document.querySelectorAll(selector).forEach((el) => {
        const type = el.dataset[typeAttr];
        if (!type) return;
        if (!selections[type]) selections[type] = [];
        if (el.checked) selections[type].push(el.value);
    });
    return selections;
}

function stripEmptyPromptLimits(options) {
    const cleaned = { ...options };
    ['max_paths', 'max_nodes', 'max_edges', 'neighbor_k'].forEach((key) => {
        if (cleaned[key] === null || cleaned[key] === undefined || cleaned[key] === '' || Number.isNaN(cleaned[key])) {
            delete cleaned[key];
        }
    });
    return cleaned;
}

function formatPromptLimitValue(value) {
    return Number.isFinite(value) ? value : '';
}

function computePromptDefaults(result) {
    const paths = getAnalysisPaths(result);
    const totalPaths = Number.isFinite(result?.total_paths) ? result.total_paths : paths.length;
    let totalNodes = Number.isFinite(result?.total_nodes) ? result.total_nodes : null;
    let totalEdges = Number.isFinite(result?.total_edges) ? result.total_edges : null;

    if (totalNodes === null || totalEdges === null) {
        const nodeIds = new Set();
        let edgeCount = 0;
        paths.forEach((path) => {
            (path.nodes || []).forEach((node) => {
                const key = node.id || `${node.label || 'node'}:${node.name || ''}`;
                nodeIds.add(key);
            });
            edgeCount += (path.edges || []).length;
        });
        if (totalNodes === null) totalNodes = nodeIds.size;
        if (totalEdges === null) totalEdges = edgeCount;
    }

    const neighborK = Number.isFinite(result?.multihop_k) ? result.multihop_k : 1;

    return {
        max_paths: Math.max(1, totalPaths || 1),
        max_nodes: Math.max(1, totalNodes || 1),
        max_edges: Math.max(1, totalEdges || 1),
        neighbor_k: Math.max(1, neighborK || 1),
    };
}

function getPromptOptionsFromUI() {
    const scopeEl = document.getElementById('promptScope');
    if (!scopeEl) return stripEmptyPromptLimits(AppState.promptOptions);
    const graphFormatEl = document.getElementById('promptGraphFormat');

    const maxPathsEl = document.getElementById('promptMaxPaths');
    const maxNodesEl = document.getElementById('promptMaxNodes');
    const maxEdgesEl = document.getElementById('promptMaxEdges');
    const neighborEl = document.getElementById('promptNeighborK');

    const maxPathsRaw = maxPathsEl?.value?.trim();
    const maxNodesRaw = maxNodesEl?.value?.trim();
    const maxEdgesRaw = maxEdgesEl?.value?.trim();
    const neighborRaw = neighborEl?.value?.trim();

    const maxPaths = maxPathsRaw ? parseInt(maxPathsRaw, 10) : null;
    const maxNodes = maxNodesRaw ? parseInt(maxNodesRaw, 10) : null;
    const maxEdges = maxEdgesRaw ? parseInt(maxEdgesRaw, 10) : null;
    const neighborK = neighborRaw ? parseInt(neighborRaw, 10) : null;

    const graphFormat = graphFormatEl?.value || AppState.promptOptions.graph_format || 'mermaid';
    const options = {
        graph_format: graphFormat,
        scope: scopeEl.value,
        node_type_fields: collectTypeFieldSelections('.prompt-node-field', 'nodeType'),
        edge_type_fields: collectTypeFieldSelections('.prompt-edge-field', 'edgeType'),
        max_paths: maxPaths,
        max_nodes: maxNodes,
        max_edges: maxEdges,
        neighbor_k: neighborK,
        include_inline_edges: true,
    };

    const invalid = [];
    if (!options.graph_format) invalid.push('graph_format');
    if (!options.scope) invalid.push('scope');
    if (maxPathsRaw && (Number.isNaN(maxPaths) || maxPaths < 1)) invalid.push('max_paths');
    if (maxNodesRaw && (Number.isNaN(maxNodes) || maxNodes < 1)) invalid.push('max_nodes');
    if (maxEdgesRaw && (Number.isNaN(maxEdges) || maxEdges < 1)) invalid.push('max_edges');
    if (neighborRaw && (Number.isNaN(neighborK) || neighborK < 1)) invalid.push('neighbor_k');
    if (invalid.length) {
        throw new Error(`プロンプト設定が不正です: ${invalid.join(', ')}`);
    }

    AppState.promptOptions = options;
    return stripEmptyPromptLimits(options);
}

function getAnalysisPaths(result) {
    const candidates = result?.candidates || [];
    const paperPaths = result?.paper_paths || [];
    const entityPaths = result?.entity_paths || [];
    return candidates.length > 0 ? candidates : [...paperPaths, ...entityPaths];
}

function collectPromptTypes(paths) {
    const nodeTypes = new Set();
    const edgeTypes = new Set();

    paths.forEach((path) => {
        (path.nodes || []).forEach((node) => {
            if (node.label === 'Paper') {
                nodeTypes.add('Paper');
            } else {
                nodeTypes.add(node.entity_type || 'Entity');
            }
        });
        (path.edges || []).forEach((edge) => {
            if (edge.type) edgeTypes.add(edge.type);
        });
    });

    return {
        nodeTypes: Array.from(nodeTypes),
        edgeTypes: Array.from(edgeTypes),
    };
}

function sortNodeTypes(types) {
    return [...types].sort((a, b) => {
        if (a === 'Paper') return -1;
        if (b === 'Paper') return 1;
        return a.localeCompare(b);
    });
}

function sortEdgeTypes(types) {
    const order = Object.keys(EDGE_FIELD_OPTIONS);
    return [...types].sort((a, b) => {
        const indexA = order.indexOf(a);
        const indexB = order.indexOf(b);
        if (indexA === -1 && indexB === -1) return a.localeCompare(b);
        if (indexA === -1) return 1;
        if (indexB === -1) return -1;
        return indexA - indexB;
    });
}

function ensurePromptOptionsForTypes(promptOptions, nodeTypes, edgeTypes) {
    const updated = {
        ...promptOptions,
        node_type_fields: { ...promptOptions.node_type_fields },
        edge_type_fields: { ...promptOptions.edge_type_fields },
    };

    nodeTypes.forEach((nodeType) => {
        if (!updated.node_type_fields[nodeType]) {
            const defaults = nodeType === 'Paper' ? PAPER_FIELD_OPTIONS : ENTITY_FIELD_OPTIONS;
            updated.node_type_fields[nodeType] = defaults.map(option => option.value);
        }
    });

    edgeTypes.forEach((edgeType) => {
        if (!EDGE_FIELD_OPTIONS[edgeType]) return;
        if (!updated.edge_type_fields[edgeType]) {
            updated.edge_type_fields[edgeType] = EDGE_FIELD_OPTIONS[edgeType].map(option => option.value);
        }
    });

    return updated;
}

function renderFieldChecklist(type, options, selected, inputClass, dataAttr) {
    return options.map((option) => `
        <label class="prompt-options-checkbox">
            <input type="checkbox" class="${inputClass}" data-${dataAttr}="${escapeHtml(type)}" value="${option.value}" ${
        selected.includes(option.value) ? 'checked' : ''
    }>
            ${option.label}
        </label>
    `).join('');
}

function getSavedProposalPrompt(proposal) {
    return proposal.prompt || (proposal.data && proposal.data.prompt) || '';
}

function getProposalGroupKey(proposal) {
    const analysisId = proposal.analysis_id || '';
    const paperId = proposal.target_paper_id || '';
    const prompt = getSavedProposalPrompt(proposal);
    if (analysisId) return `analysis:${analysisId}`;
    if (prompt) return `prompt:${paperId}:${prompt}`;
    return `proposal:${proposal.id || ''}`;
}

function buildProposalGroups(proposals) {
    const groups = [];
    const indexByKey = {};

    proposals.forEach((proposal) => {
        const key = getProposalGroupKey(proposal);
        if (indexByKey[key] === undefined) {
            indexByKey[key] = groups.length;
            groups.push({
                key: key,
                target_paper_id: proposal.target_paper_id || '',
                target_paper_title: proposal.target_paper_title || '',
                analysis_id: proposal.analysis_id || null,
                prompt: getSavedProposalPrompt(proposal),
                saved_at: proposal.saved_at || '',
                proposals: [],
            });
        }
        const group = groups[indexByKey[key]];
        group.proposals.push(proposal);
        if (proposal.saved_at && proposal.saved_at > group.saved_at) {
            group.saved_at = proposal.saved_at;
        }
    });

    return { groups, indexByKey };
}

function formatScore(score) {
    return (score * 100).toFixed(1);
}

function getScoreClass(score) {
    if (score >= 0.7) return 'high';
    if (score >= 0.4) return 'medium';
    return 'low';
}

function updateStatus(message) {
    const statusEl = document.getElementById('status');
    if (statusEl) statusEl.textContent = message;
}

function updateStats(message) {
    const statsEl = document.getElementById('stats');
    if (statsEl) statsEl.textContent = message;
}

// ========== タブナビゲーション ==========
function switchTab(tabName) {
    AppState.currentTab = tabName;

    // タブボタンの状態更新
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // 右パネルの表示切替
    const rightPanel = document.getElementById('rightPanel');
    if (rightPanel) {
        if (tabName === 'explore') {
            rightPanel.style.display = 'none';
        } else {
            rightPanel.style.display = 'flex';
            updateRightPanelContent(tabName);
        }
    }

    // ステータス更新
    const tabNames = {
        'explore': '探索モード',
        'analyze': '分析モード',
        'propose': '提案モード',
        'evaluate': '評価モード',
        'history': '履歴モード'
    };
    updateStatus(tabNames[tabName] || tabName);
}

function updateRightPanelContent(tabName) {
    const headerTitle = document.querySelector('.right-panel-header h3');
    const content = document.getElementById('rightPanelContent');

    if (!content) return;

    if (tabName === 'analyze') {
        if (headerTitle) headerTitle.textContent = '分析結果';
        renderAnalysisResults();
    } else if (tabName === 'propose') {
        if (headerTitle) headerTitle.textContent = '研究提案';
        renderProposals();
    } else if (tabName === 'evaluate') {
        if (headerTitle) headerTitle.textContent = '提案評価';
        renderEvaluation();
    } else if (tabName === 'history') {
        if (headerTitle) headerTitle.textContent = '履歴';
        renderHistory();
    }
}

// 右パネルを開く
function openRightPanel() {
    const rightPanel = document.getElementById('rightPanel');
    if (rightPanel) {
        rightPanel.style.display = 'flex';
    }
}

// ========== グラフ初期化 ==========
async function initGraph() {
    try {
        const response = await fetch('/api/visualization/config');
        const config = await response.json();

        AppState.neo4jPassword = prompt('Neo4jパスワードを入力してください:', 'password') || 'password';

        const neovisConfig = {
            containerId: "graph",
            neo4j: {
                serverUrl: config.neo4j_uri.replace('bolt://', 'neo4j://'),
                serverUser: config.user,
                serverPassword: AppState.neo4jPassword,
            },
            visConfig: {
                nodes: {
                    font: {
                        size: 12,
                        color: '#333333',
                        strokeWidth: 3,
                        strokeColor: '#ffffff',
                    },
                },
                edges: {
                    font: { size: 10, color: '#aaaaaa' },
                    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
                },
                physics: {
                    solver: 'forceAtlas2Based',
                    forceAtlas2Based: {
                        gravitationalConstant: -50,
                        centralGravity: 0.01,
                        springLength: 100,
                        springConstant: 0.08,
                    },
                },
            },
            labels: {
                Paper: {
                    label: "title",
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        static: {
                            color: "#4A90D9",
                            shape: "dot",
                            size: 20,
                        },
                    },
                },
                Entity: {
                    label: "name",
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        function: {
                            color: (node) => getEntityColor(node.properties.type),
                        },
                        static: {
                            shape: "diamond",
                            size: 15,
                        },
                    },
                },
            },
            relationships: {
                CITES: {
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        function: {
                            color: (edge) => getCitationColor(edge.properties?.citation_type),
                            width: (edge) => Math.max(1, Math.min(5, edge.properties?.importance_score || 1)),
                            label: (edge) => edge.properties?.citation_type || 'CITES',
                        },
                    },
                },
                MENTIONS: {
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        static: {
                            label: "MENTIONS",
                            color: "#7CB342",
                        },
                    },
                },
                EXTENDS: {
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        static: {
                            label: "EXTENDS",
                            color: "#FF9800",
                            dashes: true,
                        },
                    },
                },
                COMPONENT_OF: {
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        static: {
                            label: "COMPONENT",
                            color: "#9C27B0",
                            dashes: true,
                        },
                    },
                },
                ALIAS_OF: {
                    [NeoVis.NEOVIS_ADVANCED_CONFIG]: {
                        static: {
                            label: "ALIAS",
                            color: "#00BCD4",
                            dashes: true,
                        },
                    },
                },
            },
            initialCypher: config.initial_cypher,
        };

        AppState.viz = new NeoVis.default(neovisConfig);
        AppState.viz.render();
        updateStatus('グラフを読み込み中...');

        AppState.viz.registerOnEvent("completed", () => {
            const nodeCount = AppState.viz.nodes ? AppState.viz.nodes.length : 0;
            const edgeCount = AppState.viz.edges ? AppState.viz.edges.length : 0;
            updateStatus('読み込み完了');
            updateStats(`ノード: ${nodeCount}, エッジ: ${edgeCount}`);
        });

        AppState.viz.registerOnEvent("clickNode", (event) => {
            showNodeInfo(event.node);
        });

        AppState.viz.registerOnEvent("clickEdge", (event) => {
            showEdgeInfo(event.edge);
        });

    } catch (error) {
        console.error('Graph initialization failed:', error);
        updateStatus('グラフの初期化に失敗しました: ' + error.message);
    }
}

// ========== フィルター・検索 ==========
function filterBy(type) {
    const query = FILTER_QUERIES[type];
    if (query && AppState.viz) {
        document.getElementById('query').value = query;
        updateStatus(`フィルター: ${type}`);
        AppState.viz.renderWithCypher(query);
    }
}

function searchKeyword() {
    const keyword = document.getElementById('keyword').value.trim();
    if (!keyword) {
        alert('キーワードを入力してください');
        return;
    }

    const query = `
        MATCH (n)
        WHERE (n:Paper AND toLower(n.title) CONTAINS toLower("${keyword}"))
           OR (n:Entity AND toLower(n.name) CONTAINS toLower("${keyword}"))
        OPTIONAL MATCH (n)-[r]-(m)
        RETURN n, r, m LIMIT 50
    `;
    document.getElementById('query').value = query;
    updateStatus(`検索: "${keyword}"`);
    if (AppState.viz) {
        AppState.viz.renderWithCypher(query);
    }
}

function runQuery() {
    const query = document.getElementById('query').value;
    updateStatus('クエリを実行中...');

    try {
        if (AppState.viz) {
            AppState.viz.renderWithCypher(query);
        }
    } catch (error) {
        updateStatus('クエリ実行エラー: ' + error.message);
    }
}

// ========== 分析 ==========
async function runAnalysis() {
    const paperId = document.getElementById('paperId').value;
    const hopK = parseInt(document.getElementById('hopK').value);

    if (!paperId) {
        alert('論文IDを入力してください');
        return;
    }

    updateStatus('分析を実行中...');

    // 右パネルにローディング表示
    openRightPanel();
    const content = document.getElementById('rightPanelContent');
    const headerTitle = document.querySelector('.right-panel-header h3');
    if (headerTitle) headerTitle.textContent = '分析結果';
    if (content) {
        content.innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
            </div>
            <div style="text-align: center; color: #888; margin-top: 1rem;">
                分析を実行中...
            </div>
        `;
    }

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: paperId,
                multihop_k: hopK,
                top_n: ANALYSIS_DISPLAY_LIMIT,
                response_limit: ANALYSIS_DISPLAY_LIMIT,
                save: true,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        AppState.analysisResult = result;
        AppState.selectedPaperId = paperId;
        AppState.analysisId = result.analysis_id || null;

        const totalCount = Number.isFinite(result.total_paths)
            ? result.total_paths
            : (result.candidates ? result.candidates.length : 0);
        const displayLimit = Math.min(ANALYSIS_DISPLAY_LIMIT, totalCount);
        const countLabel = totalCount > displayLimit
            ? `${totalCount}件 (表示${displayLimit}件)`
            : `${totalCount}件`;
        updateStatus(`分析完了: ${countLabel}のパス`);

        // 結果をグラフに表示
        const cypher = `
            MATCH path = (p:Paper {id: "${paperId}"})-[*1..${hopK}]-(n)
            RETURN path LIMIT 50
        `;
        document.getElementById('query').value = cypher;
        if (AppState.viz) {
            AppState.viz.renderWithCypher(cypher);
        }

        // 分析タブに切り替えて結果表示
        switchTab('analyze');

        // 提案生成設定セクションを表示
        const proposalSettingsSection = document.getElementById('proposalSettingsSection');
        if (proposalSettingsSection) {
            proposalSettingsSection.style.display = 'block';
        }

        if (AppState.analysisId) {
            await loadSavedHistory();
        }

    } catch (error) {
        updateStatus('分析エラー: ' + error.message);
        if (content) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">分析エラー<br>${error.message}</div>
                </div>
            `;
        }
    }
}

// ========== 分析結果レンダリング ==========
function renderAnalysisResults() {
    const content = document.getElementById('rightPanelContent');
    if (!content) return;

    // candidatesまたはpaper_paths/entity_pathsをチェック
    const result = AppState.analysisResult;
    const allPaths = getAnalysisPaths(result);
    const totalPaths = Number.isFinite(result?.total_paths) ? result.total_paths : allPaths.length;
    const displayPaths = allPaths.slice(0, ANALYSIS_DISPLAY_LIMIT);
    const pathCountLabel = totalPaths !== null
        ? `${displayPaths.length} / ${totalPaths} パス`
        : `${displayPaths.length} パス`;

    if (!result || allPaths.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <div class="empty-state-text">分析結果がありません<br>左のサイドバーから論文を選択して<br>「分析実行」をクリックしてください</div>
            </div>
        `;
        return;
    }

    const maxScore = displayPaths.length > 0
        ? Math.max(...displayPaths.map(c => c.score || 0), 1)
        : 1;
    const { nodeTypes, edgeTypes } = collectPromptTypes(allPaths);
    const promptOptions = ensurePromptOptionsForTypes(AppState.promptOptions, nodeTypes, edgeTypes);
    const promptDefaults = computePromptDefaults(result);
    const defaultsSourceNote = Number.isFinite(result?.total_nodes) && Number.isFinite(result?.total_edges)
        ? '（分析結果全体から算出）'
        : '（表示中のパスから算出）';
    AppState.promptOptions = promptOptions;

    const sortedNodeTypes = sortNodeTypes(nodeTypes);
    const sortedEdgeTypes = sortEdgeTypes(edgeTypes).filter((type) => EDGE_FIELD_OPTIONS[type]);

    const nodeTypeOptionsHtml = sortedNodeTypes.map((nodeType) => {
        const selected = promptOptions.node_type_fields[nodeType] || [];
        const fieldOptions = nodeType === 'Paper' ? PAPER_FIELD_OPTIONS : ENTITY_FIELD_OPTIONS;
        return `
            <div class="prompt-options-type">
                <div class="prompt-options-type-title">${escapeHtml(nodeType)}</div>
                <div class="prompt-options-checklist">
                    ${renderFieldChecklist(nodeType, fieldOptions, selected, 'prompt-node-field', 'node-type')}
                </div>
            </div>
        `;
    }).join('');

    const edgeTypeOptionsHtml = sortedEdgeTypes.map((edgeType) => {
        const selected = promptOptions.edge_type_fields[edgeType] || [];
        const fieldOptions = EDGE_FIELD_OPTIONS[edgeType] || [];
        return `
            <div class="prompt-options-type">
                <div class="prompt-options-type-title">${escapeHtml(edgeType)}</div>
                <div class="prompt-options-checklist">
                    ${renderFieldChecklist(edgeType, fieldOptions, selected, 'prompt-edge-field', 'edge-type')}
                </div>
            </div>
        `;
    }).join('');

    const maxPathsValue = formatPromptLimitValue(promptOptions.max_paths);
    const maxNodesValue = formatPromptLimitValue(promptOptions.max_nodes);
    const maxEdgesValue = formatPromptLimitValue(promptOptions.max_edges);
    const neighborValue = formatPromptLimitValue(promptOptions.neighbor_k);

    const promptOptionsHtml = `
        <details class="prompt-options-panel">
            <summary class="prompt-options-summary">プロンプト設定</summary>
            <div class="prompt-options-body">
                <div class="prompt-options-note">空欄は分析結果に合わせて自動設定されます。</div>
                <div class="prompt-options-group">
                    <label class="prompt-options-label" for="promptGraphFormat">出力形式</label>
                    <div class="prompt-options-help">分岐構造をMermaidで出力するか、従来のパス形式で出力するかを選択します。</div>
                    <select id="promptGraphFormat" class="prompt-options-select">
                        <option value="mermaid" ${promptOptions.graph_format === 'mermaid' ? 'selected' : ''}>Mermaid</option>
                        <option value="paths" ${promptOptions.graph_format === 'paths' ? 'selected' : ''}>Paths</option>
                    </select>
                </div>
                <div class="prompt-options-group">
                    <label class="prompt-options-label" for="promptScope">スコープ</label>
                    <div class="prompt-options-help">パスとk-hop近傍のどちらをプロンプトに含めるかを選択します。</div>
                    <select id="promptScope" class="prompt-options-select">
                        <option value="path" ${promptOptions.scope === 'path' ? 'selected' : ''}>パスのみ</option>
                        <option value="k_hop" ${promptOptions.scope === 'k_hop' ? 'selected' : ''}>k-hop 近傍</option>
                        <option value="path_plus_k_hop" ${promptOptions.scope === 'path_plus_k_hop' ? 'selected' : ''}>パス + k-hop</option>
                    </select>
                </div>
                <div class="prompt-options-group">
                    <div class="prompt-options-label">ノード情報</div>
                    <div class="prompt-options-help">ノード種別ごとに含めたい情報を選びます。</div>
                    <div class="prompt-options-type-list">
                        ${nodeTypeOptionsHtml}
                    </div>
                </div>
                <div class="prompt-options-group">
                    <div class="prompt-options-label">エッジ情報</div>
                    <div class="prompt-options-help">エッジ種別ごとに出力する属性を選びます。</div>
                    <div class="prompt-options-type-list">
                        ${edgeTypeOptionsHtml}
                    </div>
                </div>
                <div class="prompt-options-grid">
                    <label class="prompt-options-field">
                        <span>パス上限</span>
                        <input type="number" id="promptMaxPaths" min="1" step="1" value="${maxPathsValue}" placeholder="${promptDefaults.max_paths}">
                    </label>
                    <label class="prompt-options-field">
                        <span>ノード上限</span>
                        <input type="number" id="promptMaxNodes" min="1" step="1" value="${maxNodesValue}" placeholder="${promptDefaults.max_nodes}">
                    </label>
                    <label class="prompt-options-field">
                        <span>エッジ上限</span>
                        <input type="number" id="promptMaxEdges" min="1" step="1" value="${maxEdgesValue}" placeholder="${promptDefaults.max_edges}">
                    </label>
                    <label class="prompt-options-field">
                        <span>k-hop 深さ</span>
                        <input type="number" id="promptNeighborK" min="1" step="1" value="${neighborValue}" placeholder="${promptDefaults.neighbor_k}">
                    </label>
                </div>
                <div class="prompt-options-help">
                    空欄時の自動値: パス ${promptDefaults.max_paths} / ノード ${promptDefaults.max_nodes} / エッジ ${promptDefaults.max_edges} / k-hop ${promptDefaults.neighbor_k} ${defaultsSourceNote}
                </div>
                <div class="prompt-preview-actions" style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border-color);">
                    <button class="btn-secondary" onclick="previewPrompt()" style="width: 100%; padding: 0.5rem;">
                        プロンプトを作成
                    </button>
                </div>
                <div id="promptPreviewContainer" style="display: none; margin-top: 0.5rem;">
                    <div style="display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.25rem;">
                        <div id="promptStats" style="font-size: 0.7rem; color: #888; display: flex; gap: 1rem;"></div>
                        <button id="promptPreviewCopy" class="btn-secondary" type="button" onclick="copyPromptPreview()" style="padding: 0.3rem 0.5rem; font-size: 0.65rem;" disabled>コピー</button>
                    </div>
                    <pre class="prompt-preview-content" style="max-height: 300px; overflow: auto; padding: 0.5rem; background: var(--bg-primary); border-radius: 4px; font-size: 0.7rem; white-space: pre-wrap; word-break: break-word;"></pre>
                </div>
            </div>
        </details>
    `;

    let html = `
        <div class="analysis-header" style="margin-bottom: 0.75rem; padding: 0.75rem; background: var(--bg-tertiary); border-radius: 6px;">
            <div style="font-size: 0.75rem; color: #888;">対象論文</div>
            <div style="font-size: 0.9rem; color: #fff; font-weight: bold;">${truncateText(AppState.selectedPaperId, 35)}</div>
            <div style="font-size: 0.75rem; color: #666; margin-top: 0.25rem;">
                ${pathCountLabel} (${result.multihop_k || 3} ホップ)
            </div>
        </div>
        ${promptOptionsHtml}
        <div class="analysis-actions" style="margin-bottom: 0.75rem; display: flex; gap: 0.5rem;">
            <button class="btn-primary" onclick="generateProposals()" style="flex: 1; padding: 0.6rem;">
                💡 提案を生成
            </button>
        </div>
        <div style="font-size: 0.8rem; color: #888; margin-bottom: 0.5rem;">発見されたパス:</div>
        <div class="analysis-results">
    `;

    displayPaths.forEach((path, index) => {
        const scorePercent = maxScore > 0 ? (path.score / maxScore) * 100 : 0;
        const scoreClass = getScoreClass(path.score / maxScore);
        const nodes = path.nodes || [];

        html += `
            <div class="path-card" onclick="selectPath(${index})" data-index="${index}">
                <div class="path-card-header">
                    <span class="path-rank">#${index + 1}</span>
                    <span class="path-score ${scoreClass}">${path.score?.toFixed(1) || '0'}</span>
                </div>
                <div class="path-nodes">
                    ${nodes.map((node, i) => `
                        <span class="path-node">${truncateText(node.name || node.id || '?', 12)}</span>
                        ${i < nodes.length - 1 ? '<span class="path-arrow">→</span>' : ''}
                    `).join('')}
                </div>
                <div class="score-bar">
                    <div class="score-bar-fill" style="width: ${scorePercent}%"></div>
                </div>
            </div>
        `;
    });

    html += '</div>';
    content.innerHTML = html;
}

function selectPath(index) {
    // 既存の選択を解除
    document.querySelectorAll('.path-card').forEach(card => {
        card.classList.remove('selected');
    });

    // 新しい選択を設定
    const card = document.querySelector(`.path-card[data-index="${index}"]`);
    if (card) card.classList.add('selected');

    // パスデータを取得
    const result = AppState.analysisResult;
    const candidates = result?.candidates || [];
    const paperPaths = result?.paper_paths || [];
    const entityPaths = result?.entity_paths || [];
    const allPaths = candidates.length > 0 ? candidates : [...paperPaths, ...entityPaths];
    const path = allPaths[index];

    if (!path) return;

    // パス詳細を表示
    showPathDetail(path, index);

    // グラフ上でハイライト
    highlightPathOnGraph(path);
}

function showPathDetail(path, index) {
    const nodes = path.nodes || [];
    const edges = path.edges || [];

    let detailHtml = `
        <div id="pathDetailPanel" style="
            position: fixed;
            bottom: 60px;
            right: 370px;
            width: 400px;
            max-height: 300px;
            background: var(--bg-secondary);
            border: 1px solid var(--bg-tertiary);
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            z-index: 1000;
            overflow: hidden;
        ">
            <div style="
                padding: 0.75rem;
                background: var(--bg-tertiary);
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <span style="font-weight: bold; color: var(--accent-blue);">パス #${index + 1} 詳細</span>
                <button onclick="closePathDetail()" style="
                    background: none;
                    border: none;
                    color: #888;
                    cursor: pointer;
                    font-size: 1.2rem;
                ">✕</button>
            </div>
            <div style="padding: 0.75rem; overflow-y: auto; max-height: 240px;">
                <div style="font-size: 0.75rem; color: #888; margin-bottom: 0.5rem;">
                    スコア: <span style="color: var(--score-high);">${path.score?.toFixed(2) || 'N/A'}</span>
                </div>
    `;

    // パスの各ノードとエッジを表示
    nodes.forEach((node, i) => {
        const isFirst = i === 0;
        const isLast = i === nodes.length - 1;
        const nodeType = node.label || 'Node';
        const nodeColor = nodeType === 'Paper' ? 'var(--accent-blue)' : 'var(--entity-method)';
        const icon = nodeType === 'Paper' ? '📄' : '🔧';

        detailHtml += `
            <div style="
                padding: 0.5rem;
                margin: 0.25rem 0;
                background: ${isFirst || isLast ? 'rgba(74, 144, 217, 0.15)' : 'var(--bg-primary)'};
                border-radius: 4px;
                border-left: 3px solid ${nodeColor};
            ">
                <div style="font-size: 0.7rem; color: #888;">${icon} ${nodeType}${node.entity_type ? ` (${node.entity_type})` : ''}</div>
                <div style="font-size: 0.85rem; color: #fff;">${node.name || node.id || '不明'}</div>
                ${node.description ? `<div style="font-size: 0.7rem; color: #aaa; margin-top: 0.25rem;">${truncateText(node.description, 80)}</div>` : ''}
            </div>
        `;

        // エッジ情報
        if (i < edges.length) {
            const edge = edges[i];
            const edgeColor = {
                'CITES': 'var(--citation-extends)',
                'MENTIONS': 'var(--accent-green)',
                'EXTENDS': 'var(--entity-method)',
                'USES': 'var(--citation-uses)',
            }[edge.type] || '#888';

            detailHtml += `
                <div style="
                    text-align: center;
                    padding: 0.25rem;
                    color: ${edgeColor};
                    font-size: 0.75rem;
                ">
                    ↓ <strong>${edge.type}</strong>
                    ${edge.importance_score ? ` (重要度: ${'★'.repeat(edge.importance_score)})` : ''}
                </div>
            `;

            if (edge.context) {
                detailHtml += `
                    <div style="
                        font-size: 0.7rem;
                        color: #888;
                        font-style: italic;
                        padding: 0.25rem 0.5rem;
                        background: rgba(0,0,0,0.2);
                        border-radius: 3px;
                        margin-bottom: 0.25rem;
                    ">"${truncateText(edge.context, 100)}"</div>
                `;
            }
        }
    });

    // スコア内訳
    if (path.score_breakdown) {
        const bd = path.score_breakdown;
        detailHtml += `
            <div style="margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px solid var(--bg-tertiary);">
                <div style="font-size: 0.75rem; color: #888; margin-bottom: 0.25rem;">スコア内訳:</div>
                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.7rem;">
        `;
        if (bd.cite_importance_score) detailHtml += `<span style="color: var(--citation-extends);">引用重要度: ${bd.cite_importance_score.toFixed(1)}</span>`;
        if (bd.cite_type_score) detailHtml += `<span style="color: var(--citation-compares);">引用種別: ${bd.cite_type_score.toFixed(1)}</span>`;
        if (bd.mentions_score) detailHtml += `<span style="color: var(--accent-green);">言及: ${bd.mentions_score.toFixed(1)}</span>`;
        if (bd.entity_relation_score) detailHtml += `<span style="color: var(--entity-dataset);">Entity関係: ${bd.entity_relation_score.toFixed(1)}</span>`;
        if (bd.length_penalty) detailHtml += `<span style="color: var(--score-low);">距離ペナルティ: ${bd.length_penalty.toFixed(1)}</span>`;
        detailHtml += `</div></div>`;
    }

    detailHtml += `</div></div>`;

    // 既存のパネルを削除
    closePathDetail();

    // 新しいパネルを追加
    document.body.insertAdjacentHTML('beforeend', detailHtml);
}

function closePathDetail() {
    const existing = document.getElementById('pathDetailPanel');
    if (existing) existing.remove();
}

function highlightPathOnGraph(path) {
    if (!AppState.viz) return;

    const nodes = path.nodes || [];
    const pathNodeIds = nodes.map(n => n.id).filter(id => id);
    const pathNodeNames = nodes.map(n => n.name?.toLowerCase()).filter(n => n);

    // vis.jsのノードとエッジを取得
    const visNodes = AppState.viz.nodes;
    const visEdges = AppState.viz.edges;
    const network = AppState.viz.network;

    if (!visNodes || !network) return;

    // 全ノードを取得
    const allNodeIds = visNodes.getIds();
    const matchedNodeIds = [];

    // パスに含まれるノードを探す
    allNodeIds.forEach(nodeId => {
        const node = visNodes.get(nodeId);
        if (!node || !node.raw) return;

        const props = node.raw.properties || {};
        const nodeDbId = props.id;
        const nodeName = (props.title || props.name || '').toLowerCase();

        // IDまたは名前でマッチ
        if (pathNodeIds.includes(nodeDbId) || pathNodeNames.some(pn => nodeName.includes(pn) || pn.includes(nodeName))) {
            matchedNodeIds.push(nodeId);
        }
    });

    if (matchedNodeIds.length === 0) {
        updateStatus('パスのノードがグラフ上に見つかりません');
        return;
    }

    // ハイライト前の状態を保存（初回のみ）
    if (!AppState.originalNodeStyles) {
        AppState.originalNodeStyles = {};
        allNodeIds.forEach(nodeId => {
            const node = visNodes.get(nodeId);
            if (node) {
                AppState.originalNodeStyles[nodeId] = {
                    color: node.color,
                    size: node.size,
                    borderWidth: node.borderWidth,
                    opacity: node.opacity
                };
            }
        });
    }

    // 全ノードを暗くする
    const updates = [];
    allNodeIds.forEach(nodeId => {
        const isHighlighted = matchedNodeIds.includes(nodeId);
        updates.push({
            id: nodeId,
            opacity: isHighlighted ? 1 : 0.2,
            borderWidth: isHighlighted ? 3 : 1,
            color: isHighlighted ? {
                border: '#FFD700',
                background: visNodes.get(nodeId)?.color?.background || '#4A90D9',
                highlight: { border: '#FFD700', background: '#FFD700' }
            } : visNodes.get(nodeId)?.color
        });
    });

    visNodes.update(updates);

    // マッチしたノードを選択状態にしてフォーカス
    network.selectNodes(matchedNodeIds);

    // 最初のノードにフォーカス（ズームはしない）
    if (matchedNodeIds.length > 0) {
        network.focus(matchedNodeIds[0], {
            scale: network.getScale(),
            animation: { duration: 500, easingFunction: 'easeInOutQuad' }
        });
    }

    updateStatus(`パス: ${matchedNodeIds.length}/${nodes.length}ノードをハイライト`);

    // 一定時間後にハイライトを解除するボタンを表示
    showResetHighlightButton();
}

function showResetHighlightButton() {
    // 既存のボタンを削除
    const existing = document.getElementById('resetHighlightBtn');
    if (existing) existing.remove();

    const btn = document.createElement('button');
    btn.id = 'resetHighlightBtn';
    btn.innerHTML = '🔄 ハイライト解除';
    btn.style.cssText = `
        position: fixed;
        bottom: 70px;
        left: 50%;
        transform: translateX(-50%);
        padding: 0.5rem 1rem;
        background: var(--bg-tertiary);
        color: #fff;
        border: 1px solid var(--accent-blue);
        border-radius: 20px;
        cursor: pointer;
        font-size: 0.8rem;
        z-index: 1000;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
    `;
    btn.onclick = resetHighlight;
    document.body.appendChild(btn);
}

function resetHighlight() {
    if (!AppState.viz || !AppState.viz.nodes || !AppState.originalNodeStyles) return;

    const visNodes = AppState.viz.nodes;
    const network = AppState.viz.network;

    // 元のスタイルに戻す
    const updates = [];
    Object.keys(AppState.originalNodeStyles).forEach(nodeId => {
        updates.push({
            id: nodeId,
            opacity: 1,
            borderWidth: 1,
        });
    });

    visNodes.update(updates);

    // 選択解除
    if (network) {
        network.unselectAll();
    }

    // 保存したスタイルをクリア
    AppState.originalNodeStyles = null;

    // ボタンを削除
    const btn = document.getElementById('resetHighlightBtn');
    if (btn) btn.remove();

    updateStatus('ハイライトを解除しました');
}

// ========== 提案生成 ==========
async function previewPrompt() {
    if (!AppState.analysisResult) {
        alert('先に分析を実行してください');
        return;
    }

    const container = document.getElementById('promptPreviewContainer');
    const previewContent = container?.querySelector('.prompt-preview-content');
    const statsEl = document.getElementById('promptStats');
    if (!container || !previewContent) return;

    // トグル動作: 表示中なら閉じる
    if (container.style.display !== 'none') {
        container.style.display = 'none';
        return;
    }

    // ローディング表示
    container.style.display = 'block';
    previewContent.textContent = 'プロンプトを生成中...';
    if (statsEl) statsEl.textContent = '';
    updatePromptPreviewCopyButton('loading');

    try {
        const promptOptions = getPromptOptionsFromUI();

        const response = await fetch('/api/propose/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: AppState.selectedPaperId,
                analysis_id: AppState.analysisId || null,
                analysis_result: AppState.analysisId ? null : AppState.analysisResult,
                num_proposals: getNumProposals(),
                prompt_options: promptOptions,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        const promptText = result.prompt || '';
        previewContent.textContent = promptText || 'プロンプトが生成されませんでした';
        updatePromptPreviewCopyButton(promptText ? 'ready' : 'disabled');

        // 行数・文字数を表示
        if (statsEl && promptText) {
            const lineCount = promptText.split('\n').length;
            const charCount = promptText.length;
            statsEl.innerHTML = `<span>📝 ${lineCount.toLocaleString()} 行</span><span>📏 ${charCount.toLocaleString()} 文字</span>`;
        }

        updateStatus('プロンプトを生成しました');
    } catch (error) {
        previewContent.textContent = 'エラー: ' + error.message;
        updatePromptPreviewCopyButton('disabled');
        updateStatus('プロンプト生成エラー: ' + error.message);
    }
}

function updatePromptPreviewCopyButton(state) {
    const button = document.getElementById('promptPreviewCopy');
    if (!button) return;

    if (state === 'ready') {
        button.disabled = false;
        button.textContent = 'コピー';
        return;
    }
    if (state === 'loading') {
        button.disabled = true;
        button.textContent = 'コピー準備中';
        return;
    }
    if (state === 'copied') {
        button.disabled = false;
        button.textContent = 'コピーしました';
        return;
    }

    button.disabled = true;
    button.textContent = 'コピー';
}

async function copyPromptPreview() {
    const container = document.getElementById('promptPreviewContainer');
    const previewContent = container?.querySelector('.prompt-preview-content');
    if (!previewContent) return;

    const promptText = previewContent.textContent || '';
    const trimmed = promptText.trim();
    if (!trimmed || trimmed === 'プロンプトを生成中...' || trimmed === 'プロンプトが生成されませんでした' || trimmed.startsWith('エラー:')) {
        updateStatus('コピーするプロンプトがありません');
        return;
    }

    try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(promptText);
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = promptText;
            textarea.setAttribute('readonly', '');
            textarea.style.position = 'fixed';
            textarea.style.top = '-1000px';
            textarea.style.left = '-1000px';
            document.body.appendChild(textarea);
            textarea.select();
            textarea.setSelectionRange(0, textarea.value.length);
            const success = document.execCommand('copy');
            document.body.removeChild(textarea);
            if (!success) {
                throw new Error('コピーに失敗しました');
            }
        }

        updatePromptPreviewCopyButton('copied');
        updateStatus('プロンプトをコピーしました');
        setTimeout(() => updatePromptPreviewCopyButton('ready'), 1200);
    } catch (error) {
        updateStatus('コピーに失敗しました: ' + (error?.message || String(error)));
    }
}

async function generateProposals() {
    if (!AppState.analysisResult) {
        alert('先に分析を実行してください');
        return;
    }

    updateStatus('提案を生成中... (数分かかる場合があります)');

    // 右パネルにローディング表示
    openRightPanel();
    const content = document.getElementById('rightPanelContent');
    const headerTitle = document.querySelector('.right-panel-header h3');
    if (headerTitle) headerTitle.textContent = '研究提案';
    if (content) {
        content.innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
            </div>
            <div style="text-align: center; color: #888; margin-top: 1rem;">
                LLMで提案を生成中...<br>
                <span style="font-size: 0.75rem;">数分かかる場合があります</span>
            </div>
        `;
    }

    try {
        let promptOptions = AppState.promptOptions;
        try {
            promptOptions = getPromptOptionsFromUI();
        } catch (error) {
            alert(error.message);
            updateStatus('提案生成エラー: ' + error.message);
            return;
        }

        const models = getSelectedModels();
        const response = await fetch('/api/propose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: AppState.selectedPaperId,
                analysis_id: AppState.analysisId || null,
                analysis_result: AppState.analysisId ? null : AppState.analysisResult,
                num_proposals: getNumProposals(),
                prompt_options: promptOptions,
                model_name: models.ideagraph,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        AppState.proposals = result.proposals || [];
        AppState.proposalPrompt = result.prompt || '';
        AppState.proposalSources = {};

        updateStatus(`提案生成完了: ${AppState.proposals.length}件`);

        // 提案タブに切り替え
        switchTab('propose');

        // 自動保存
        await saveAllProposals();

    } catch (error) {
        updateStatus('提案生成エラー: ' + error.message);
        if (content) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">提案生成エラー<br>${error.message}</div>
                </div>
            `;
        }
    }
}

// ========== 提案レンダリング ==========
function renderProposals() {
    const content = document.getElementById('rightPanelContent');
    if (!content) return;

    // CoI実行中の場合は進捗を表示
    if (AppState.coiRunning) {
        content.innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
            </div>
            <div style="text-align: center; color: #888; margin-top: 1rem;">
                CoI-Agentを実行中...<br>
                <span style="font-size: 0.75rem;" id="coiProgressText">初期化中...</span>
            </div>
            <div id="coiProgressLog" style="margin-top: 1rem; max-height: 200px; overflow-y: auto; padding: 0.5rem; background: var(--bg-primary); border-radius: 4px; font-size: 0.7rem; font-family: monospace;"></div>
        `;
        return;
    }

    if (!AppState.proposals || !AppState.proposals.length) {
        content.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">💡</div>
                <div class="empty-state-text">提案がありません<br>分析を実行してから「提案を生成」をクリックしてください</div>
            </div>
            ${renderCoISection()}
        `;
        return;
    }

    const promptHtml = AppState.proposalPrompt ? `
        <details class="prompt-panel">
            <summary class="prompt-summary">生成プロンプト</summary>
            <pre class="prompt-content">${escapeHtml(AppState.proposalPrompt)}</pre>
        </details>
    ` : '';

    let html = `
        <div class="proposal-actions" style="margin-bottom: 0.75rem; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center;">
            <div class="eval-mode-selector" style="display: flex; gap: 0.25rem; align-items: center;">
                <select id="evaluationMode" onchange="AppState.evaluationMode = this.value" style="padding: 0.35rem 0.5rem; border-radius: 4px; border: 1px solid var(--border-secondary); background: var(--bg-secondary); color: var(--text-primary); font-size: 0.8rem; cursor: pointer;">
                    <option value="pairwise" ${AppState.evaluationMode === 'pairwise' ? 'selected' : ''}>ペアワイズ比較</option>
                    <option value="single" ${AppState.evaluationMode === 'single' ? 'selected' : ''}>単体評価</option>
                </select>
                <button class="btn-evaluate" onclick="runEvaluationByMode()" title="提案を評価・ランキング">
                    🏆 評価を実行
                </button>
            </div>
            <button class="btn-secondary" onclick="openComparisonModal()">
                比較ビュー
            </button>
            <button class="btn-secondary" onclick="exportProposals('markdown')" title="Markdownでエクスポート">
                📄
            </button>
            <button class="btn-secondary" onclick="exportProposals('json')" title="JSONでエクスポート">
                📋
            </button>
        </div>
        ${AppState.selectedPaperId ? `
        <div class="target-paper-option" style="margin-bottom: 0.75rem; padding: 0.5rem; background: var(--bg-tertiary); border-radius: 6px; display: flex; align-items: center; gap: 0.5rem;">
            <input type="checkbox" id="includeTargetPaper" checked>
            <label for="includeTargetPaper" style="font-size: 0.8rem; color: #ccc; cursor: pointer;">
                📄 ターゲット論文（${escapeHtml(AppState.selectedPaperTitle || AppState.selectedPaperId)}）を比較に含める
            </label>
        </div>
        ` : ''}
        ${promptHtml}
        <div class="proposal-cards">
    `;

    AppState.proposals.forEach((proposal, index) => {
        html += renderProposalCard(proposal, index);
    });

    html += '</div>';

    // CoIセクションを追加
    html += renderCoISection();

    content.innerHTML = html;
}

function renderProposalCard(proposal, index) {
    const source = AppState.proposalSources[index] || 'ideagraph';
    const sourceBadge = getSourceBadge(source);

    return `
        <div class="proposal-card" data-source="${source}">
            <div class="proposal-card-header">
                <span class="proposal-title">${truncateText(proposal.title, 30)}</span>
                <div class="proposal-actions">
                    ${sourceBadge}
                    <button class="btn-icon" onclick="toggleProposalDetails(${index})" title="詳細">
                        📖
                    </button>
                </div>
            </div>
            <div class="proposal-card-body">
                <div class="proposal-section">
                    <div class="proposal-section-title">動機</div>
                    <div class="proposal-section-content">${truncateText(proposal.motivation, 100)}</div>
                </div>
                <div class="proposal-section">
                    <div class="proposal-section-title">手法</div>
                    <div class="proposal-section-content">${truncateText(proposal.method, 100)}</div>
                </div>
                <div class="rating" data-proposal="${index}">
                    ${[1, 2, 3, 4, 5].map(star => `
                        <span class="rating-star" onclick="rateProposal(${index}, ${star})">☆</span>
                    `).join('')}
                </div>
            </div>
        </div>
    `;
}

function getSourceBadge(source) {
    switch (source) {
        case 'coi':
            return '<span class="source-badge source-coi">🟢 CoI</span>';
        case 'target_paper':
            return '<span class="source-badge source-target">📄 ターゲット</span>';
        case 'ideagraph':
        default:
            return '<span class="source-badge source-ideagraph">🔵 IdeaGraph</span>';
    }
}

function renderCoISection() {
    return `
        <div class="coi-section" style="margin-top: 1.5rem; padding: 1rem; background: var(--bg-tertiary); border-radius: 8px; border: 1px solid rgba(76, 175, 80, 0.3);">
            <h4 style="font-size: 0.9rem; color: #4CAF50; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.5rem;">
                🔗 CoI（Chain-of-Ideas）で比較
            </h4>
            <p style="font-size: 0.75rem; color: #aaa; margin-bottom: 0.75rem;">
                CoI-Agentを実行してIdeaGraphと比較します。実行には数分〜十数分かかります。
            </p>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <button class="btn-coi" onclick="runCoI()" ${AppState.coiRunning ? 'disabled' : ''}>
                    ${AppState.coiRunning ? '実行中...' : '🚀 CoIを実行'}
                </button>
                <button class="btn-secondary" onclick="openCoILoadModal()" title="既存のCoI結果を読み込み">
                    📂 結果を読み込み
                </button>
            </div>
            <div id="coiStatus" style="margin-top: 0.5rem; font-size: 0.75rem; color: #888;"></div>
        </div>
    `;
}

function toggleProposalDetails(index) {
    const existing = document.getElementById('proposalDetailsModal');
    if (existing) {
        const sameTarget = existing.dataset.index === String(index);
        existing.remove();
        if (sameTarget) return;
    }
    openProposalDetailsModal(index);
}

function openProposalDetailsModal(index) {
    const proposal = AppState.proposals[index];
    if (!proposal) return;

    const exp = proposal.experiment || {};
    const grounding = proposal.grounding || {};
    const rationaleHtml = proposal.rationale
        ? `
            <section class="proposal-detail-section">
                <div class="proposal-detail-title">提案理由</div>
                ${renderTextBlock(proposal.rationale)}
            </section>
        `
        : '';
    const researchTrendsHtml = proposal.research_trends
        ? `
            <section class="proposal-detail-section">
                <div class="proposal-detail-title">研究動向</div>
                ${renderTextBlock(proposal.research_trends)}
            </section>
        `
        : '';
    const coiIdeaHtml = proposal.coi && proposal.coi.idea
        ? `
            <section class="proposal-detail-section">
                <div class="proposal-detail-title">CoI原文</div>
                ${renderTextBlock(proposal.coi.idea)}
            </section>
        `
        : '';

    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'proposalDetailsModal';
    modal.dataset.index = String(index);
    modal.innerHTML = `
        <div class="modal proposal-modal">
            <div class="modal-header">
                <h2 class="modal-title">提案 #${index + 1}: ${escapeHtml(proposal.title || 'Untitled')}</h2>
                <button class="modal-close" onclick="closeProposalDetailsModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="proposal-detail">
                    ${rationaleHtml}
                    ${researchTrendsHtml}
                    ${coiIdeaHtml}
                    <section class="proposal-detail-section">
                        <div class="proposal-detail-title">動機</div>
                        ${renderTextBlock(proposal.motivation)}
                    </section>
                    <section class="proposal-detail-section">
                        <div class="proposal-detail-title">手法</div>
                        ${renderTextBlock(proposal.method)}
                    </section>
                    <section class="proposal-detail-section">
                        <div class="proposal-detail-title">実験計画</div>
                        <div class="detail-grid">
                            <div class="detail-item">
                                <div class="detail-label">データセット</div>
                                ${renderList(exp.datasets)}
                            </div>
                            <div class="detail-item">
                                <div class="detail-label">ベースライン</div>
                                ${renderList(exp.baselines)}
                            </div>
                            <div class="detail-item">
                                <div class="detail-label">評価指標</div>
                                ${renderList(exp.metrics)}
                            </div>
                            <div class="detail-item">
                                <div class="detail-label">アブレーション</div>
                                ${renderList(exp.ablations)}
                            </div>
                        </div>
                        <div class="detail-item detail-wide">
                            <div class="detail-label">期待結果</div>
                            ${renderTextBlock(exp.expected_results)}
                        </div>
                        <div class="detail-item detail-wide">
                            <div class="detail-label">失敗時の解釈</div>
                            ${renderTextBlock(exp.failure_interpretation)}
                        </div>
                    </section>
                    <section class="proposal-detail-section">
                        <div class="proposal-detail-title">既存研究との差異</div>
                        ${renderList(proposal.differences)}
                    </section>
                    <section class="proposal-detail-section">
                        <div class="proposal-detail-title">根拠</div>
                        <div class="detail-grid">
                            <div class="detail-item">
                                <div class="detail-label">関連論文</div>
                                ${renderList(grounding.papers)}
                            </div>
                            <div class="detail-item">
                                <div class="detail-label">関連エンティティ</div>
                                ${renderList(grounding.entities)}
                            </div>
                        </div>
                        ${grounding.path_mermaid ? `
                            <div class="detail-item detail-wide">
                                <div class="detail-label">知識グラフパス</div>
                                <pre class="detail-code">${escapeHtml(grounding.path_mermaid)}</pre>
                            </div>
                        ` : ''}
                    </section>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeProposalDetailsModal()">閉じる</button>
                <button class="btn-primary" onclick="saveProposal(${index})">保存</button>
            </div>
        </div>
    `;

    modal.addEventListener('click', (event) => {
        if (event.target === modal) {
            closeProposalDetailsModal();
        }
    });

    document.body.appendChild(modal);
}

function closeProposalDetailsModal() {
    const modal = document.getElementById('proposalDetailsModal');
    if (modal) modal.remove();
}

function rateProposal(index, rating) {
    const ratingEl = document.querySelector(`.rating[data-proposal="${index}"]`);
    if (!ratingEl) return;

    const stars = ratingEl.querySelectorAll('.rating-star');
    stars.forEach((star, i) => {
        star.textContent = i < rating ? '★' : '☆';
        star.classList.toggle('filled', i < rating);
    });

    // 評価を保存（AppStateに格納）
    if (!AppState.proposals[index].rating) {
        AppState.proposals[index].rating = rating;
    }
}

// ========== 比較モーダル ==========
function openComparisonModal() {
    if (!AppState.proposals || AppState.proposals.length < 2) {
        alert('比較するには2つ以上の提案が必要です');
        return;
    }

    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'comparisonModal';
    modal.innerHTML = `
        <div class="modal" style="width: 90vw; max-width: 1200px;">
            <div class="modal-header">
                <h2 class="modal-title">提案の比較</h2>
                <button class="modal-close" onclick="closeComparisonModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="comparison-view">
                    ${AppState.proposals.map((proposal, i) => {
                        const exp = proposal.experiment || {};
                        return `
                            <article class="comparison-card">
                                <div class="comparison-card-header">
                                    <span class="comparison-index">#${i + 1}</span>
                                    <span class="comparison-title">${escapeHtml(proposal.title || 'Untitled')}</span>
                                </div>
                                <div class="comparison-card-body">
                                    <div class="comparison-section">
                                        <div class="comparison-section-title">動機</div>
                                        <div class="comparison-section-content">${escapeHtml(proposal.motivation || '')}</div>
                                    </div>
                                    <div class="comparison-section">
                                        <div class="comparison-section-title">手法</div>
                                        <div class="comparison-section-content">${escapeHtml(proposal.method || '')}</div>
                                    </div>
                                    <div class="comparison-section">
                                        <div class="comparison-section-title">実験計画</div>
                                        <div class="comparison-section-content">
                                            <div><strong>データセット:</strong> ${formatInlineList(exp.datasets)}</div>
                                            <div><strong>ベースライン:</strong> ${formatInlineList(exp.baselines)}</div>
                                            <div><strong>評価指標:</strong> ${formatInlineList(exp.metrics)}</div>
                                        </div>
                                    </div>
                                    <div class="comparison-section">
                                        <div class="comparison-section-title">既存研究との差異</div>
                                        <div class="comparison-section-content">
                                            ${renderList(proposal.differences, 'なし')}
                                        </div>
                                    </div>
                                </div>
                            </article>
                        `;
                    }).join('')}
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeComparisonModal()">閉じる</button>
                <button class="btn-primary" onclick="exportProposals('markdown')">エクスポート</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
}

function closeComparisonModal() {
    const modal = document.getElementById('comparisonModal');
    if (modal) modal.remove();
}

// ========== 提案評価 ==========
function runEvaluationByMode() {
    if (AppState.evaluationMode === 'single') {
        runSingleEvaluation();
    } else {
        runEvaluation();
    }
}

async function runSingleEvaluation() {
    if (!AppState.proposals || AppState.proposals.length < 1) {
        alert('評価には1件以上の提案が必要です');
        return;
    }

    updateStatus('提案を単体評価中... (数分かかる場合があります)');

    // 右パネルにローディング表示
    openRightPanel();
    const content = document.getElementById('rightPanelContent');
    const headerTitle = document.querySelector('.right-panel-header h3');
    if (headerTitle) headerTitle.textContent = '単体評価';
    const evaluationInfo = `${AppState.proposals.length}件の提案`;
    if (content) {
        content.innerHTML = `
            <div class="evaluation-progress">
                <div class="loading">
                    <div class="loading-spinner"></div>
                </div>
                <div style="text-align: center; color: #888; margin-top: 1rem;">
                    <div id="singleEvalPhase">初期化中...</div>
                    <div id="singleEvalProgressText" style="font-size: 0.85rem; margin-top: 0.5rem;"></div>
                    <div style="margin-top: 0.75rem; padding: 0 1rem;">
                        <div style="background: var(--bg-primary); border-radius: 4px; height: 8px; overflow: hidden;">
                            <div id="singleEvalProgressBar" style="background: var(--primary); height: 100%; width: 0%; transition: width 0.3s ease;"></div>
                        </div>
                    </div>
                    <div style="font-size: 0.75rem; margin-top: 0.5rem; color: #666;">${evaluationInfo}を単体評価しています</div>
                </div>
            </div>
        `;
    }

    // リクエストボディを構築
    const evalModels = getSelectedModels();
    const proposalSources = AppState.proposals.map((_, index) => {
        return AppState.proposalSources[index] || 'ideagraph';
    });
    const requestBody = {
        proposals: AppState.proposals,
        proposal_sources: proposalSources,
        model_name: evalModels.ideagraph,
    };

    try {
        const response = await fetch('/api/evaluate/single/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        updateSingleEvaluationProgress(event);

                        if (event.event_type === 'completed' && event.result) {
                            AppState.singleEvaluationResult = event.result;
                            AppState.evaluationResult = null;  // ペアワイズ結果をクリア
                            updateStatus(`単体評価完了: ${event.result.ranking?.length || 0}件をランキング`);
                            switchTab('evaluate');
                        } else if (event.event_type === 'error') {
                            throw new Error(event.error || '評価中にエラーが発生しました');
                        }
                    } catch (e) {
                        if (e.message && !e.message.includes('JSON')) {
                            throw e;
                        }
                    }
                }
            }
        }

    } catch (error) {
        updateStatus('評価エラー: ' + error.message);
        if (content) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">評価エラー<br>${escapeHtml(error.message)}</div>
                </div>
            `;
        }
    }
}

function updateSingleEvaluationProgress(event) {
    const phaseEl = document.getElementById('singleEvalPhase');
    const progressTextEl = document.getElementById('singleEvalProgressText');
    const progressBarEl = document.getElementById('singleEvalProgressBar');

    if (!phaseEl || !progressTextEl || !progressBarEl) return;

    const phaseMessages = {
        'evaluating': 'アイデアを評価中...',
        'completed': '評価完了！',
    };

    phaseEl.textContent = phaseMessages[event.phase] || event.message || '処理中...';

    if (event.total_evaluations > 0) {
        const percent = Math.round((event.current_evaluation / event.total_evaluations) * 100);
        progressBarEl.style.width = `${percent}%`;
        progressTextEl.textContent = `${event.current_evaluation}/${event.total_evaluations}件の評価完了`;
    }
}

async function runEvaluation() {
    // ターゲット論文を含めるかどうかチェック
    const includeTargetCheckbox = document.getElementById('includeTargetPaper');
    const includeTarget = includeTargetCheckbox?.checked && AppState.selectedPaperId;

    // 提案数 + ターゲット論文(選択時は1) >= 2 で判断
    const proposalCount = AppState.proposals ? AppState.proposals.length : 0;
    const targetPaperCount = includeTarget ? 1 : 0;
    const totalCount = proposalCount + targetPaperCount;
    if (totalCount < 2) {
        alert('評価には2件以上のアイデアが必要です（提案 + ターゲット論文）');
        return;
    }

    updateStatus('提案を評価中... (数分かかる場合があります)');

    // 右パネルにローディング表示
    openRightPanel();
    const content = document.getElementById('rightPanelContent');
    const headerTitle = document.querySelector('.right-panel-header h3');
    if (headerTitle) headerTitle.textContent = '提案評価';
    const evaluationInfo = includeTarget
        ? `${AppState.proposals.length}件の提案 + ターゲット論文`
        : `${AppState.proposals.length}件の提案`;
    if (content) {
        content.innerHTML = `
            <div class="evaluation-progress">
                <div class="loading">
                    <div class="loading-spinner"></div>
                </div>
                <div style="text-align: center; color: #888; margin-top: 1rem;">
                    <div id="evaluationPhase">初期化中...</div>
                    <div id="evaluationProgressText" style="font-size: 0.85rem; margin-top: 0.5rem;"></div>
                    <div style="margin-top: 0.75rem; padding: 0 1rem;">
                        <div style="background: var(--bg-primary); border-radius: 4px; height: 8px; overflow: hidden;">
                            <div id="evaluationProgressBar" style="background: var(--primary); height: 100%; width: 0%; transition: width 0.3s ease;"></div>
                        </div>
                    </div>
                    <div style="font-size: 0.75rem; margin-top: 0.5rem; color: #666;">${evaluationInfo}を評価しています</div>
                </div>
            </div>
        `;
    }

    // リクエストボディを構築
    const evalModels = getSelectedModels();
    const proposalSources = AppState.proposals.map((_, index) => {
        return AppState.proposalSources[index] || 'ideagraph';
    });
    const requestBody = {
        proposals: AppState.proposals,
        proposal_sources: proposalSources,
        include_experiment: true,
        model_name: evalModels.ideagraph,
    };
    if (includeTarget) {
        requestBody.target_paper_id = AppState.selectedPaperId;
        requestBody.target_paper_title = AppState.selectedPaperTitle;
    }

    try {
        const response = await fetch('/api/evaluate/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        updateEvaluationProgress(event);

                        if (event.event_type === 'completed' && event.result) {
                            AppState.evaluationResult = event.result;
                            AppState.singleEvaluationResult = null;  // 単体評価結果をクリア
                            updateStatus(`評価完了: ${event.result.ranking?.length || 0}件をランキング`);
                            switchTab('evaluate');
                        } else if (event.event_type === 'error') {
                            throw new Error(event.error || '評価中にエラーが発生しました');
                        }
                    } catch (e) {
                        if (e.message && !e.message.includes('JSON')) {
                            throw e;
                        }
                    }
                }
            }
        }

    } catch (error) {
        updateStatus('評価エラー: ' + error.message);
        if (content) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <div class="empty-state-text">評価エラー<br>${escapeHtml(error.message)}</div>
                </div>
            `;
        }
    }
}

function updateEvaluationProgress(event) {
    const phaseEl = document.getElementById('evaluationPhase');
    const progressTextEl = document.getElementById('evaluationProgressText');
    const progressBarEl = document.getElementById('evaluationProgressBar');

    if (!phaseEl || !progressTextEl || !progressBarEl) return;

    const phaseMessages = {
        'extracting_target': 'ターゲット論文を分析中...',
        'comparing': 'ペアワイズ比較を実行中...',
        'calculating_elo': 'ELOレーティングを計算中...',
        'completed': '評価完了！',
    };

    phaseEl.textContent = phaseMessages[event.phase] || event.message || '処理中...';

    if (event.total_comparisons > 0) {
        const percent = Math.round((event.current_comparison / event.total_comparisons) * 100);
        progressBarEl.style.width = `${percent}%`;
        progressTextEl.textContent = `${event.current_comparison}/${event.total_comparisons}件の比較完了`;
    } else if (event.phase === 'extracting_target') {
        progressBarEl.style.width = '10%';
        progressTextEl.textContent = 'ターゲット論文からアイデアを抽出中...';
    }
}

function renderEvaluation() {
    const content = document.getElementById('rightPanelContent');
    if (!content) return;

    // 単体評価結果がある場合はそちらを表示
    if (AppState.singleEvaluationResult && AppState.singleEvaluationResult.ranking && AppState.singleEvaluationResult.ranking.length > 0) {
        renderSingleEvaluation();
        return;
    }

    const result = AppState.evaluationResult;

    if (!result || !result.ranking || result.ranking.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🏆</div>
                <div class="empty-state-text">評価結果がありません<br>提案タブで「評価を実行」をクリックしてください</div>
            </div>
        `;
        return;
    }

    const ranking = result.ranking;
    const pairwiseResults = result.pairwise_results || [];

    // 指標名の日本語マッピング
    const metricLabels = {
        'novelty': '独自性',
        'significance': '重要性',
        'feasibility': '実現可能性',
        'clarity': '明確さ',
        'effectiveness': '有効性',
        'experiment_design': '実験設計',
    };

    let html = `
        <div class="evaluation-header" style="margin-bottom: 0.75rem; padding: 0.75rem; background: var(--bg-tertiary); border-radius: 6px;">
            <div style="font-size: 0.75rem; color: #888;">ペアワイズ比較評価</div>
            <div style="font-size: 0.9rem; color: #fff; font-weight: bold;">
                ${ranking.length}件の提案をランキング
            </div>
            <div style="font-size: 0.75rem; color: #666; margin-top: 0.25rem;">
                ${pairwiseResults.length}回の比較を実施
            </div>
        </div>

        <div style="font-size: 0.8rem; color: #888; margin-bottom: 0.5rem;">ランキング:</div>
        <div class="evaluation-ranking">
    `;

    ranking.forEach((item, index) => {
        const rank = item.rank || (index + 1);
        const medalClass = rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : '';
        const overallScore = item.overall_score?.toFixed(1) || 'N/A';
        const isTargetPaper = item.is_target_paper === true;
        const source = item.source || 'ideagraph';
        const sourceBadge = isTargetPaper ? '<span class="target-paper-badge">📄 ターゲット論文</span>' : getSourceBadge(source);
        const targetClass = isTargetPaper ? 'target-paper' : '';
        const sourceClass = source === 'coi' ? 'coi-source' : '';

        html += `
            <div class="evaluation-rank-card ${medalClass} ${targetClass} ${sourceClass}" data-index="${index}" data-source="${source}">
                <div class="rank-header">
                    <span class="rank-badge ${medalClass}">#${rank}</span>
                    <span class="rank-title">${truncateText(item.idea_title || '提案' + rank, 25)}</span>
                    ${sourceBadge}
                </div>
                <div class="rank-scores">
                    <div class="rank-score-item">
                        <span class="score-label">総合スコア</span>
                        <span class="score-value">${overallScore}</span>
                    </div>
                </div>
        `;

        // スコア内訳
        if (item.scores_by_metric) {
            html += `<div class="rank-score-breakdown">`;
            for (const [metric, score] of Object.entries(item.scores_by_metric)) {
                const label = metricLabels[metric] || metric;
                html += renderScoreBar(label, score);
            }
            html += `</div>`;
        }

        html += `</div>`;
    });

    html += `</div>`;

    // 比較詳細セクション
    if (pairwiseResults.length > 0) {
        html += `
            <details class="comparison-details" style="margin-top: 1rem;">
                <summary style="cursor: pointer; font-size: 0.8rem; color: var(--accent-blue); padding: 0.5rem 0;">
                    比較詳細を表示 (${pairwiseResults.length}件)
                </summary>
                <div class="comparison-list" style="margin-top: 0.5rem;">
        `;

        pairwiseResults.forEach((comp, i) => {
            // 提案タイトルをIDから取得（ターゲット論文のIDも考慮）
            const isTargetA = comp.idea_a_id === 'target_paper';
            const isTargetB = comp.idea_b_id === 'target_paper';
            const proposalA = isTargetA ? null : AppState.proposals.find((p, idx) => `proposal_${idx}` === comp.idea_a_id || idx === parseInt(comp.idea_a_id.replace('proposal_', '')));
            const proposalB = isTargetB ? null : AppState.proposals.find((p, idx) => `proposal_${idx}` === comp.idea_b_id || idx === parseInt(comp.idea_b_id.replace('proposal_', '')));
            const titleA = isTargetA ? '📄 ターゲット論文' : (proposalA?.title || comp.idea_a_id);
            const titleB = isTargetB ? '📄 ターゲット論文' : (proposalB?.title || comp.idea_b_id);

            html += `
                <div class="comparison-item">
                    <div class="comparison-matchup">
                        <span>${truncateText(titleA, 15)}</span>
                        <span class="vs">vs</span>
                        <span>${truncateText(titleB, 15)}</span>
                    </div>
            `;

            // 各指標の勝敗を表示
            if (comp.scores && comp.scores.length > 0) {
                html += `<div class="comparison-scores" style="margin-top: 0.25rem;">`;
                comp.scores.forEach(score => {
                    const label = metricLabels[score.metric] || score.metric;
                    const winnerText = score.winner === 1 ? 'A' : score.winner === 2 ? 'B' : '引分';
                    html += `
                        <div class="comparison-score-row" style="font-size: 0.7rem; color: #888; margin: 0.1rem 0;">
                            ${label}: <span style="color: var(--accent-blue);">${winnerText}</span>
                        </div>
                    `;
                });
                html += `</div>`;
            }

            html += `</div>`;
        });

        html += `</div></details>`;
    }

    // エクスポートボタン
    html += `
        <div class="evaluation-actions" style="margin-top: 1rem; display: flex; gap: 0.5rem;">
            <button class="btn-secondary" onclick="exportEvaluation('json')" style="flex: 1;">
                📋 JSONエクスポート
            </button>
            <button class="btn-secondary" onclick="exportEvaluation('markdown')" style="flex: 1;">
                📄 Markdownエクスポート
            </button>
        </div>
    `;

    content.innerHTML = html;
}

function renderSingleEvaluation() {
    const content = document.getElementById('rightPanelContent');
    if (!content) return;

    const result = AppState.singleEvaluationResult;
    if (!result || !result.ranking || result.ranking.length === 0) return;

    const ranking = result.ranking;

    const metricLabels = {
        'novelty': '独自性',
        'significance': '重要性',
        'feasibility': '実現可能性',
        'clarity': '明確さ',
        'effectiveness': '有効性',
    };

    let html = `
        <div class="evaluation-header" style="margin-bottom: 0.75rem; padding: 0.75rem; background: var(--bg-tertiary); border-radius: 6px;">
            <div style="font-size: 0.75rem; color: #888;">単体評価</div>
            <div style="font-size: 0.9rem; color: #fff; font-weight: bold;">
                ${ranking.length}件の提案をランキング
            </div>
            <div style="font-size: 0.75rem; color: #666; margin-top: 0.25rem;">
                各指標1-10の絶対スコアで評価
            </div>
        </div>

        <div style="font-size: 0.8rem; color: #888; margin-bottom: 0.5rem;">ランキング:</div>
        <div class="evaluation-ranking">
    `;

    ranking.forEach((item, index) => {
        const rank = index + 1;
        const medalClass = rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? 'bronze' : '';
        const overallScore = item.overall_score?.toFixed(1) || 'N/A';
        const source = item.source || 'ideagraph';
        const sourceBadge = getSourceBadge(source);
        const sourceClass = source === 'coi' ? 'coi-source' : '';

        html += `
            <div class="evaluation-rank-card ${medalClass} ${sourceClass}" data-index="${index}" data-source="${source}">
                <div class="rank-header">
                    <span class="rank-badge ${medalClass}">#${rank}</span>
                    <span class="rank-title">${truncateText(item.idea_title || '提案' + rank, 25)}</span>
                    ${sourceBadge}
                </div>
                <div class="rank-scores">
                    <div class="rank-score-item">
                        <span class="score-label">総合スコア</span>
                        <span class="score-value">${overallScore}</span>
                    </div>
                </div>
        `;

        // スコア内訳（1-10スケール）
        if (item.scores && item.scores.length > 0) {
            html += `<div class="rank-score-breakdown">`;
            item.scores.forEach(s => {
                const label = metricLabels[s.metric] || s.metric;
                html += renderScoreBar(label, s.score);
            });
            html += `</div>`;

            // 評価理由（折り畳み）
            html += `
                <details class="single-eval-reasoning" style="margin-top: 0.5rem;">
                    <summary style="cursor: pointer; font-size: 0.75rem; color: var(--accent-blue); padding: 0.25rem 0;">
                        評価理由を表示
                    </summary>
                    <div style="margin-top: 0.25rem; font-size: 0.75rem; color: #999;">
            `;
            item.scores.forEach(s => {
                const label = metricLabels[s.metric] || s.metric;
                html += `<div style="margin: 0.25rem 0;"><strong>${label}</strong> (${s.score}/10): ${escapeHtml(s.reasoning)}</div>`;
            });
            html += `</div></details>`;
        }

        html += `</div>`;
    });

    html += `</div>`;

    // エクスポートボタン
    html += `
        <div class="evaluation-actions" style="margin-top: 1rem; display: flex; gap: 0.5rem;">
            <button class="btn-secondary" onclick="exportSingleEvaluation('json')" style="flex: 1;">
                📋 JSONエクスポート
            </button>
            <button class="btn-secondary" onclick="exportSingleEvaluation('markdown')" style="flex: 1;">
                📄 Markdownエクスポート
            </button>
        </div>
    `;

    content.innerHTML = html;
}

function exportSingleEvaluation(format) {
    const result = AppState.singleEvaluationResult;
    if (!result) return;

    if (format === 'json') {
        const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `single_evaluation_${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
    } else {
        // Markdown生成
        const ranking = result.ranking || [];
        const metricLabels = {
            'novelty': 'Novelty',
            'significance': 'Significance',
            'feasibility': 'Feasibility',
            'clarity': 'Clarity',
            'effectiveness': 'Effectiveness',
        };

        let md = `# Idea Single Evaluation Report\n\n`;
        md += `**Evaluated at**: ${result.evaluated_at}\n`;
        md += `**Model**: ${result.model_name}\n`;
        md += `**Proposals**: ${ranking.length}\n\n`;
        md += `## Rankings\n\n`;
        md += `| Rank | Title | Overall | Novelty | Significance | Feasibility | Clarity | Effectiveness |\n`;
        md += `|------|-------|---------|---------|--------------|-------------|---------|---------------|\n`;

        ranking.forEach((item, index) => {
            const scores = {};
            (item.scores || []).forEach(s => { scores[s.metric] = s.score; });
            md += `| ${index + 1} | ${item.idea_title || item.idea_id} | ${item.overall_score?.toFixed(1)} | ${scores.novelty || '-'} | ${scores.significance || '-'} | ${scores.feasibility || '-'} | ${scores.clarity || '-'} | ${scores.effectiveness || '-'} |\n`;
        });

        md += `\n## Detailed Evaluations\n\n`;
        ranking.forEach((item, index) => {
            md += `### ${index + 1}. ${item.idea_title || item.idea_id} (Overall: ${item.overall_score?.toFixed(1)})\n\n`;
            (item.scores || []).forEach(s => {
                const label = metricLabels[s.metric] || s.metric;
                md += `- **${label}** (${s.score}/10): ${s.reasoning}\n`;
            });
            md += `\n`;
        });

        const blob = new Blob([md], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `single_evaluation_${new Date().toISOString().slice(0, 10)}.md`;
        a.click();
        URL.revokeObjectURL(url);
    }
}

function renderScoreBar(label, score) {
    if (score === undefined || score === null) return '';
    const percent = Math.min(100, Math.max(0, score * 10));
    const colorClass = score >= 7 ? 'high' : score >= 4 ? 'medium' : 'low';
    return `
        <div class="score-bar-row">
            <span class="score-bar-label">${label}</span>
            <div class="score-bar-container">
                <div class="score-bar-fill ${colorClass}" style="width: ${percent}%"></div>
            </div>
            <span class="score-bar-value">${score.toFixed(1)}</span>
        </div>
    `;
}

function exportEvaluation(format) {
    if (!AppState.evaluationResult) {
        alert('エクスポートする評価結果がありません');
        return;
    }

    let content, filename, mimeType;

    if (format === 'json') {
        content = JSON.stringify({
            evaluated_at: new Date().toISOString(),
            ...AppState.evaluationResult,
        }, null, 2);
        filename = `evaluation_${Date.now()}.json`;
        mimeType = 'application/json';
    } else {
        content = generateEvaluationMarkdown();
        filename = `evaluation_${Date.now()}.md`;
        mimeType = 'text/markdown';
    }

    downloadFile(content, filename, mimeType);
}

function generateEvaluationMarkdown() {
    const result = AppState.evaluationResult;
    const metricLabels = {
        'novelty': '独自性',
        'significance': '重要性',
        'feasibility': '実現可能性',
        'clarity': '明確さ',
        'effectiveness': '有効性',
        'experiment_design': '実験設計',
    };

    let md = `# 提案評価結果\n\n`;
    md += `評価日時: ${result.evaluated_at || new Date().toISOString()}\n`;
    md += `モデル: ${result.model_name || 'N/A'}\n\n`;
    md += `---\n\n`;

    md += `## ランキング\n\n`;
    md += `| 順位 | タイプ | 提案 | 総合スコア |\n`;
    md += `|------|--------|------|------------|\n`;

    result.ranking.forEach((item) => {
        const title = item.idea_title || `提案${item.rank}`;
        const score = item.overall_score?.toFixed(1) || 'N/A';
        const type = item.is_target_paper ? '📄 ターゲット' : '💡 提案';
        md += `| ${item.rank} | ${type} | ${title} | ${score} |\n`;
    });

    md += `\n### スコア詳細\n\n`;
    result.ranking.forEach((item) => {
        const title = item.idea_title || `提案${item.rank}`;
        const targetMark = item.is_target_paper ? ' (📄 ターゲット論文)' : '';
        md += `#### ${item.rank}位: ${title}${targetMark}\n\n`;
        if (item.scores_by_metric) {
            for (const [metric, score] of Object.entries(item.scores_by_metric)) {
                const label = metricLabels[metric] || metric;
                md += `- ${label}: ${score.toFixed(1)}\n`;
            }
        }
        md += `\n`;
    });

    if (result.pairwise_results && result.pairwise_results.length > 0) {
        md += `## ペアワイズ比較結果\n\n`;
        result.pairwise_results.forEach((comp, i) => {
            md += `### 比較 ${i + 1}: ${comp.idea_a_id} vs ${comp.idea_b_id}\n\n`;
            if (comp.scores && comp.scores.length > 0) {
                md += `| 指標 | 勝者 | 理由 |\n`;
                md += `|------|------|------|\n`;
                comp.scores.forEach(score => {
                    const label = metricLabels[score.metric] || score.metric;
                    const winnerText = score.winner === 1 ? 'A' : score.winner === 2 ? 'B' : '引分';
                    const reasoning = score.reasoning ? score.reasoning.replace(/\|/g, '\\|').substring(0, 50) + '...' : '';
                    md += `| ${label} | ${winnerText} | ${reasoning} |\n`;
                });
            }
            md += `\n`;
        });
    }

    return md;
}

// ========== エクスポート ==========
function exportProposals(format) {
    if (!AppState.proposals || !AppState.proposals.length) {
        alert('エクスポートする提案がありません');
        return;
    }

    let content, filename, mimeType;

    if (format === 'json') {
        content = JSON.stringify({
            target_paper_id: AppState.selectedPaperId,
            prompt: AppState.proposalPrompt || null,
            proposals: AppState.proposals,
            exported_at: new Date().toISOString(),
        }, null, 2);
        filename = `proposals_${AppState.selectedPaperId || 'unknown'}.json`;
        mimeType = 'application/json';
    } else {
        content = generateMarkdown();
        filename = `proposals_${AppState.selectedPaperId || 'unknown'}.md`;
        mimeType = 'text/markdown';
    }

    downloadFile(content, filename, mimeType);
}

function generateMarkdown() {
    let md = `# 研究提案\n\n`;
    md += `対象論文: ${AppState.selectedPaperId}\n`;
    md += `生成日時: ${new Date().toLocaleString('ja-JP')}\n\n`;
    md += `---\n\n`;

    if (AppState.proposalPrompt) {
        md += `## 生成プロンプト\n`;
        md += "```text\n";
        md += `${AppState.proposalPrompt}\n`;
        md += "```\n\n";
        md += `---\n\n`;
    }

    AppState.proposals.forEach((proposal, i) => {
        md += `## 提案 ${i + 1}: ${proposal.title}\n\n`;
        md += `### 動機\n${proposal.motivation}\n\n`;
        md += `### 手法\n${proposal.method}\n\n`;
        md += `### 実験計画\n`;
        md += `- **データセット**: ${proposal.experiment.datasets.join(', ')}\n`;
        md += `- **ベースライン**: ${proposal.experiment.baselines.join(', ')}\n`;
        md += `- **評価指標**: ${proposal.experiment.metrics.join(', ')}\n`;
        md += `- **アブレーション**: ${proposal.experiment.ablations.join(', ')}\n`;
        md += `- **期待結果**: ${proposal.experiment.expected_results}\n`;
        md += `- **失敗時の解釈**: ${proposal.experiment.failure_interpretation}\n\n`;
        md += `### 既存研究との差異\n`;
        proposal.differences.forEach(d => {
            md += `- ${d}\n`;
        });
        md += `\n### 根拠\n`;
        md += `- **関連論文**: ${proposal.grounding.papers.join(', ')}\n`;
        md += `- **関連エンティティ**: ${proposal.grounding.entities.join(', ')}\n\n`;
        md += `---\n\n`;
    });

    return md;
}

function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ========== 履歴 ==========
function renderHistory() {
    const content = document.getElementById('rightPanelContent');
    if (!content) return;

    const hasHistory = AppState.savedAnalyses.length > 0 || AppState.savedProposals.length > 0;

    if (!hasHistory) {
        content.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📚</div>
                <div class="empty-state-text">保存された履歴がありません<br><span style="font-size: 0.75rem;">分析や提案を保存すると<br>ここに表示されます</span></div>
            </div>
        `;
        return;
    }

    let html = '<div style="margin-bottom: 0.5rem; display: flex; gap: 0.5rem;">';
    html += '<button class="btn-secondary" onclick="loadSavedHistory()" style="flex: 1; padding: 0.4rem;">🔄 更新</button>';
    html += '<button class="btn-secondary" onclick="clearAllHistory()" style="padding: 0.4rem; color: #f44336;">🗑️ 全削除</button>';
    html += '</div>';

    if (AppState.savedAnalyses.length > 0) {
        html += `<h4 style="font-size: 0.85rem; color: var(--accent-green); margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.3rem;">📊 分析履歴 (${AppState.savedAnalyses.length})</h4>`;
        html += `<div class="history-list">`;
        AppState.savedAnalyses.forEach((analysis, i) => {
            const title = analysis.target_paper_title || analysis.target_paper_id || '不明';
            const date = analysis.saved_at ? new Date(analysis.saved_at).toLocaleString('ja-JP', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '';
            const totalPaths = Number.isFinite(analysis.total_paths) ? analysis.total_paths : null;
            const candidatesCount = Number.isFinite(analysis.candidates_count) ? analysis.candidates_count : null;
            const countLabel = totalPaths !== null && candidatesCount !== null
                ? `${candidatesCount}/${totalPaths}パス`
                : `${candidatesCount ?? '?'}パス`;
            html += `
                <div class="history-item">
                    <div class="history-item-info" onclick="loadAnalysis(${i})" style="flex: 1; cursor: pointer;">
                        <div class="history-item-title">${truncateText(title, 24)}</div>
                        <div class="history-item-date">${date} · ${countLabel}</div>
                    </div>
                    <button class="btn-icon" onclick="event.stopPropagation(); deleteAnalysis('${analysis.id}')" title="削除" style="color: #888;">✕</button>
                </div>
            `;
        });
        html += `</div>`;
    }

    if (AppState.savedProposals.length > 0) {
        const grouping = buildProposalGroups(AppState.savedProposals);
        AppState.savedProposalGroups = grouping.groups;
        AppState.savedProposalGroupIndexByKey = grouping.indexByKey;

        html += `<h4 style="font-size: 0.85rem; color: var(--accent-blue); margin: 1rem 0 0.5rem; display: flex; align-items: center; gap: 0.3rem;">💡 提案履歴 (${AppState.savedProposals.length})</h4>`;
        html += `<div class="history-list">`;
        AppState.savedProposals.forEach((proposal, i) => {
            const title = proposal.title || '無題の提案';
            const date = proposal.saved_at ? new Date(proposal.saved_at).toLocaleString('ja-JP', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '';
            const rating = proposal.rating ? '★'.repeat(proposal.rating) : '';
            const groupKey = getProposalGroupKey(proposal);
            const groupIndex = AppState.savedProposalGroupIndexByKey[groupKey];
            const group = AppState.savedProposalGroups[groupIndex];
            const groupCount = group ? group.proposals.length : 1;
            const groupBadge = groupCount > 1 ? ` · ${groupCount}件` : '';
            const groupAction = groupCount > 1
                ? `<button class="btn-icon" onclick="event.stopPropagation(); loadProposalGroup(${groupIndex})" title="提案セットを開く (${groupCount}件)" style="color: #88b;">📦</button>`
                : '';
            html += `
                <div class="history-item">
                    <div class="history-item-info" onclick="loadProposal(${i})" style="flex: 1; cursor: pointer;">
                        <div class="history-item-title">${truncateText(title, 24)}</div>
                        <div class="history-item-date">${date} ${rating}${groupBadge}</div>
                    </div>
                    ${groupAction}
                    <button class="btn-icon" onclick="event.stopPropagation(); deleteProposal('${proposal.id}')" title="削除" style="color: #888;">✕</button>
                </div>
            `;
        });
        html += `</div>`;
    } else {
        AppState.savedProposalGroups = [];
        AppState.savedProposalGroupIndexByKey = {};
    }

    content.innerHTML = html;
}

async function deleteAnalysis(analysisId) {
    if (!confirm('この分析履歴を削除しますか？')) return;

    try {
        const response = await fetch(`/api/storage/analyses/${analysisId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error('削除に失敗しました');
        updateStatus('分析履歴を削除しました');
        await loadSavedHistory();
    } catch (error) {
        updateStatus('削除エラー: ' + error.message);
    }
}

async function deleteProposal(proposalId) {
    if (!confirm('この提案履歴を削除しますか？')) return;

    try {
        const response = await fetch(`/api/storage/proposals/${proposalId}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error('削除に失敗しました');
        updateStatus('提案履歴を削除しました');
        await loadSavedHistory();
    } catch (error) {
        updateStatus('削除エラー: ' + error.message);
    }
}

async function clearAllHistory() {
    if (!confirm('全ての履歴を削除しますか？\nこの操作は取り消せません。')) return;

    try {
        // 全分析を削除
        for (const analysis of AppState.savedAnalyses) {
            await fetch(`/api/storage/analyses/${analysis.id}`, { method: 'DELETE' });
        }
        // 全提案を削除
        for (const proposal of AppState.savedProposals) {
            await fetch(`/api/storage/proposals/${proposal.id}`, { method: 'DELETE' });
        }
        updateStatus('全ての履歴を削除しました');
        await loadSavedHistory();
    } catch (error) {
        updateStatus('削除エラー: ' + error.message);
    }
}

async function saveAnalysis() {
    if (!AppState.analysisResult) return;

    try {
        const response = await fetch('/api/storage/analyses', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: AppState.selectedPaperId,
                target_paper_title: AppState.selectedPaperTitle,
                analysis_result: AppState.analysisResult,
            }),
        });

        if (!response.ok) throw new Error('保存に失敗しました');

        const saved = await response.json();
        updateStatus(`分析を保存しました (ID: ${saved.id})`);
        await loadSavedHistory();
    } catch (error) {
        updateStatus('保存エラー: ' + error.message);
    }
}

async function saveAllProposals() {
    if (!AppState.proposals || !AppState.proposals.length) {
        alert('保存する提案がありません');
        return;
    }
    const targetPaperId = getTargetPaperIdForSave();
    if (!targetPaperId) {
        alert('論文IDが未設定です');
        return;
    }

    updateStatus('提案を保存中...');
    let savedCount = 0;
    let failedCount = 0;

    const saveModels = getSelectedModels();
    for (const [index, proposal] of AppState.proposals.entries()) {
        try {
            const source = AppState.proposalSources[index] || 'ideagraph';
            const proposalType = getProposalTypeFromSource(source);
            const prompt = getProposalPromptForSave(proposal, source);
            const response = await fetch('/api/storage/proposals', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_paper_id: targetPaperId,
                    target_paper_title: AppState.selectedPaperTitle,
                    analysis_id: AppState.analysisId || null,
                    proposal: proposal,
                    prompt: prompt,
                    rating: proposal.rating || null,
                    proposal_type: proposalType,
                    model_name: saveModels.ideagraph,
                }),
            });

            if (!response.ok) {
                throw new Error(await response.text());
            }
            savedCount += 1;
        } catch (error) {
            failedCount += 1;
            console.error('保存エラー:', error);
        }
    }

    if (failedCount === 0) {
        updateStatus(`提案を保存しました (${savedCount}件)`);
    } else {
        updateStatus(`保存完了: ${savedCount}件, 失敗: ${failedCount}件`);
    }

    await loadSavedHistory();
}

async function saveProposal(index) {
    if (!AppState.proposals[index]) return;

    try {
        const proposal = AppState.proposals[index];
        const source = AppState.proposalSources[index] || 'ideagraph';
        const proposalType = getProposalTypeFromSource(source);
        const prompt = getProposalPromptForSave(proposal, source);
        const singleModels = getSelectedModels();
        const targetPaperId = getTargetPaperIdForSave();
        if (!targetPaperId) {
            alert('論文IDが未設定です');
            return;
        }
        const response = await fetch('/api/storage/proposals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: targetPaperId,
                target_paper_title: AppState.selectedPaperTitle,
                proposal: proposal,
                prompt: prompt,
                rating: proposal.rating || null,
                proposal_type: proposalType,
                model_name: singleModels.ideagraph,
            }),
        });

        if (!response.ok) throw new Error(await response.text());

        const saved = await response.json();
        updateStatus(`提案を保存しました (ID: ${saved.id})`);
        await loadSavedHistory();
    } catch (error) {
        updateStatus('保存エラー: ' + error.message);
    }
}

async function loadSavedHistory() {
    try {
        const [analysesRes, proposalsRes] = await Promise.all([
            fetch('/api/storage/analyses?limit=20'),
            fetch('/api/storage/proposals?limit=20'),
        ]);

        if (analysesRes.ok) {
            const data = await analysesRes.json();
            AppState.savedAnalyses = data.analyses || [];
        }

        if (proposalsRes.ok) {
            const data = await proposalsRes.json();
            AppState.savedProposals = data.proposals || [];
        }

        if (AppState.currentTab === 'history') {
            renderHistory();
        }
    } catch (error) {
        console.error('履歴の読み込みに失敗:', error);
    }
}

async function loadAnalysis(index) {
    const saved = AppState.savedAnalyses[index];
    if (!saved) return;

    try {
        const response = await fetch(`/api/storage/analyses/${saved.id}?preview_limit=${ANALYSIS_DISPLAY_LIMIT}`);
        if (!response.ok) throw new Error('読み込みに失敗しました');

        const analysis = await response.json();
        AppState.analysisResult = analysis.data;
        AppState.selectedPaperId = analysis.target_paper_id;
        AppState.selectedPaperTitle = analysis.target_paper_title;
        AppState.analysisId = analysis.id || null;
        switchTab('analyze');
        updateStatus(`分析を読み込みました: ${analysis.target_paper_id}`);
    } catch (error) {
        updateStatus('読み込みエラー: ' + error.message);
    }
}

async function loadProposal(index) {
    const saved = AppState.savedProposals[index];
    if (!saved) return;

    try {
        const response = await fetch(`/api/storage/proposals/${saved.id}`);
        if (!response.ok) throw new Error('読み込みに失敗しました');

        const proposal = await response.json();
        AppState.proposals = [proposal.data];
        AppState.selectedPaperId = proposal.target_paper_id;
        AppState.selectedPaperTitle = proposal.target_paper_title;
        AppState.proposalPrompt = proposal.prompt || (proposal.data && proposal.data.prompt) || '';
        AppState.proposalSources = { 0: getProposalSourceFromType(proposal.proposal_type) };
        switchTab('propose');
        updateStatus(`提案を読み込みました: ${proposal.title}`);
    } catch (error) {
        updateStatus('読み込みエラー: ' + error.message);
    }
}

function loadProposalGroup(groupIndex) {
    const group = AppState.savedProposalGroups[groupIndex];
    if (!group || !group.proposals.length) return;

    AppState.proposals = group.proposals.map((proposal) => proposal.data);
    AppState.selectedPaperId = group.target_paper_id;
    AppState.selectedPaperTitle = group.target_paper_title;
    AppState.proposalPrompt = group.prompt || '';
    AppState.proposalSources = {};
    group.proposals.forEach((proposal, index) => {
        AppState.proposalSources[index] = getProposalSourceFromType(proposal.proposal_type);
    });
    switchTab('propose');
    updateStatus(`提案セットを読み込みました: ${group.target_paper_id}`);
}

// ========== ノード・エッジ情報表示 ==========
function showNodeInfo(node) {
    const infoDiv = document.getElementById('nodeInfo');
    const detailsDiv = document.getElementById('nodeDetails');

    if (node && node.raw) {
        const props = node.raw.properties || {};
        const labels = node.raw.labels || [];

        // Paper の場合は ID を自動入力
        if (labels.includes('Paper') && props.id) {
            document.getElementById('paperId').value = props.id;
            AppState.selectedPaperId = props.id;
            AppState.selectedPaperTitle = props.title || props.id;
        }

        let html = `<p><strong>ラベル:</strong> ${labels.join(', ')}</p>`;
        for (const [key, value] of Object.entries(props)) {
            let displayValue = value;
            if (Array.isArray(value)) {
                displayValue = value.join(', ');
            } else if (typeof value === 'object') {
                displayValue = JSON.stringify(value);
            }
            if (typeof displayValue === 'string' && displayValue.length > 100) {
                displayValue = displayValue.substring(0, 100) + '...';
            }
            html += `<p><strong>${key}:</strong> ${displayValue}</p>`;
        }
        detailsDiv.innerHTML = html || '<p>プロパティなし</p>';
        infoDiv.style.display = 'block';
        document.getElementById('edgeInfo').style.display = 'none';
    } else {
        infoDiv.style.display = 'none';
    }
}

function showEdgeInfo(edge) {
    const infoDiv = document.getElementById('edgeInfo');
    const detailsDiv = document.getElementById('edgeDetails');

    if (edge && edge.raw) {
        const props = edge.raw.properties || {};
        const relType = edge.raw.type || 'Unknown';

        const citationType = props.citation_type || 'Unknown';
        const importanceScore = props.importance_score || 0;
        const context = props.context || '情報なし';

        let sourceTitle = '不明';
        let targetTitle = '不明';

        if (AppState.viz.nodes) {
            const sourceNode = AppState.viz.nodes.get(edge.from);
            const targetNode = AppState.viz.nodes.get(edge.to);
            if (sourceNode && sourceNode.raw) {
                sourceTitle = sourceNode.raw.properties?.title || sourceNode.label || '不明';
            }
            if (targetNode && targetNode.raw) {
                targetTitle = targetNode.raw.properties?.title || targetNode.label || '不明';
            }
        }

        const scoreStars = importanceScore > 0
            ? '★'.repeat(importanceScore) + '☆'.repeat(5 - importanceScore)
            : '未評価';

        const citationColor = getCitationColor(citationType);

        let html = `
            <div style="margin-bottom: 0.5rem;">
                <span class="citation-badge" style="background-color: ${citationColor};">
                    ${citationType}
                </span>
            </div>
            <p><strong>関係タイプ:</strong> ${relType}</p>
            <p><strong>重要度:</strong> <span class="importance-score">${scoreStars}</span> (${importanceScore}/5)</p>
            <p><strong>引用元:</strong> ${truncateText(sourceTitle, 60)}</p>
            <p><strong>引用先:</strong> ${truncateText(targetTitle, 60)}</p>
            <div class="context-section">
                <strong>引用コンテキスト:</strong>
                <p class="context-text">${context}</p>
            </div>
        `;

        detailsDiv.innerHTML = html;
        infoDiv.style.display = 'block';
        document.getElementById('nodeInfo').style.display = 'none';
    } else {
        infoDiv.style.display = 'none';
    }
}

// ========== CoI機能 ==========
async function runCoI() {
    // トピックを決定（ターゲット論文のタイトルまたはID）
    const topic = AppState.selectedPaperTitle || AppState.selectedPaperId;
    if (!topic) {
        alert('CoIを実行するには、まず分析対象の論文を選択してください');
        return;
    }

    AppState.coiRunning = true;
    AppState.coiResult = null;
    switchTab('propose');
    renderProposals();

    const statusEl = document.getElementById('coiProgressText');
    const logEl = document.getElementById('coiProgressLog');
    let conversionAttempted = false;

    try {
        // ストリーミングでCoIを実行
        const coiModels = getSelectedModels();
        const response = await fetch('/api/coi/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                topic: topic,
                max_chain_length: 5,
                min_chain_length: 3,
                max_chain_numbers: 1,
                improve_cnt: 1,
                coi_main_model: coiModels.coi_main,
                coi_cheap_model: coiModels.coi_cheap,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // SSEイベントをパース
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (statusEl) statusEl.textContent = data.progress || data.status;
                        if (logEl && data.progress) {
                            logEl.innerHTML += `<div>${escapeHtml(data.progress)}</div>`;
                            logEl.scrollTop = logEl.scrollHeight;
                        }

                        if (data.status === 'completed' && data.result) {
                            AppState.coiResult = data.result;
                            updateStatus('CoI実行完了。変換中...');
                            conversionAttempted = true;
                            await convertCoIToProposal();
                        } else if (data.status === 'error') {
                            throw new Error(data.error || 'CoI execution failed');
                        }
                    } catch (e) {
                        console.error('SSE parse error:', e);
                    }
                }
            }
        }
    } catch (error) {
        updateStatus('CoIエラー: ' + error.message);
        alert('CoI実行エラー: ' + error.message);
    } finally {
        AppState.coiRunning = false;
        if (AppState.coiResult && !conversionAttempted) {
            await convertCoIToProposal();
        }
        renderProposals();
    }
}

async function convertCoIToProposal() {
    if (!AppState.coiResult) {
        alert('変換するCoI結果がありません');
        return false;
    }

    try {
        const convertModels = getSelectedModels();
        const response = await fetch('/api/coi/convert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                coi_result: AppState.coiResult,
                model_name: convertModels.ideagraph,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        const proposal = { ...result.proposal };
        const coiMetadata = buildCoIMetadata(AppState.coiResult);
        if (coiMetadata) {
            proposal.coi = coiMetadata;
        }
        await appendCoIProposal(proposal);
        return true;

    } catch (error) {
        console.error('CoI conversion failed:', error);
        const fallbackProposal = buildCoIFallbackProposal(AppState.coiResult);
        await appendCoIProposal(fallbackProposal, 'CoI提案を追加しました（簡易表示）');
        updateStatus('変換エラー（簡易表示に切り替え）: ' + error.message);
        return true;
    }
}

function openCoILoadModal() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'coiLoadModal';
    modal.innerHTML = `
        <div class="modal" style="width: 500px;">
            <div class="modal-header">
                <h2 class="modal-title">CoI結果の読み込み</h2>
                <button class="modal-close" onclick="closeCoILoadModal()">&times;</button>
            </div>
            <div class="modal-body">
                <p style="font-size: 0.85rem; color: #ccc; margin-bottom: 1rem;">
                    既存のCoI実行結果（result.json）を読み込んでProposal形式に変換します。
                </p>
                <label style="font-size: 0.8rem; color: #aaa;">result.jsonのパス:</label>
                <input type="text" id="coiResultPath" placeholder="/path/to/result.json" style="width: 100%; padding: 0.5rem; margin-top: 0.25rem; background: var(--bg-primary); border: 1px solid var(--bg-tertiary); border-radius: 4px; color: #fff;">
                <div id="coiLoadError" style="margin-top: 0.5rem; font-size: 0.75rem; color: #f44336;"></div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeCoILoadModal()">キャンセル</button>
                <button class="btn-primary" onclick="loadCoIResult()">読み込み</button>
            </div>
        </div>
    `;

    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeCoILoadModal();
    });

    document.body.appendChild(modal);
}

function closeCoILoadModal() {
    const modal = document.getElementById('coiLoadModal');
    if (modal) modal.remove();
}

async function loadCoIResult() {
    const pathInput = document.getElementById('coiResultPath');
    const errorEl = document.getElementById('coiLoadError');
    const path = pathInput?.value?.trim();

    if (!path) {
        if (errorEl) errorEl.textContent = 'パスを入力してください';
        return;
    }

    try {
        // ファイルを読み込み
        const loadResponse = await fetch('/api/coi/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ result_path: path }),
        });

        if (!loadResponse.ok) {
            throw new Error(await loadResponse.text());
        }

        const coiResult = await loadResponse.json();
        AppState.coiResult = coiResult;

        closeCoILoadModal();

        // 変換
        updateStatus('CoI結果を変換中...');
        await convertCoIToProposal();

    } catch (error) {
        if (errorEl) errorEl.textContent = 'エラー: ' + error.message;
    }
}

// ========== 右パネル折りたたみ ==========
function toggleRightPanel() {
    const panel = document.getElementById('rightPanel');
    if (panel) {
        panel.classList.toggle('collapsed');
    }
}

// ========== 初期化 ==========
document.addEventListener('DOMContentLoaded', () => {
    initGraph();

    // モデルプリセットの詳細表示を初期化
    onModelPresetChange();

    // 履歴を読み込み
    loadSavedHistory();

    // Enterキーで検索
    const keywordInput = document.getElementById('keyword');
    if (keywordInput) {
        keywordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchKeyword();
        });
    }

    // タブクリックイベント
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchTab(tab.dataset.tab);
        });
    });
});
