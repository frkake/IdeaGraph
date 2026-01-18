/**
 * IdeaGraph - メインアプリケーション
 */

// ========== グローバル状態 ==========
const AppState = {
    viz: null,
    neo4jPassword: null,
    currentTab: 'explore',
    selectedPaperId: null,
    selectedPaperTitle: null,
    analysisResult: null,
    proposals: [],
    proposalPrompt: '',
    evaluationResult: null,
    savedAnalyses: [],
    savedProposals: [],
    savedProposalGroups: [],
    savedProposalGroupIndexByKey: {},
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
                top_n: 10,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        AppState.analysisResult = result;
        AppState.selectedPaperId = paperId;

        updateStatus(`分析完了: ${result.candidates ? result.candidates.length : 0}件のパス`);

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
    const candidates = result?.candidates || [];
    const paperPaths = result?.paper_paths || [];
    const entityPaths = result?.entity_paths || [];
    const allPaths = candidates.length > 0 ? candidates : [...paperPaths, ...entityPaths];

    if (!result || allPaths.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <div class="empty-state-text">分析結果がありません<br>左のサイドバーから論文を選択して<br>「分析実行」をクリックしてください</div>
            </div>
        `;
        return;
    }

    const maxScore = Math.max(...allPaths.map(c => c.score || 0), 1);

    let html = `
        <div class="analysis-header" style="margin-bottom: 0.75rem; padding: 0.75rem; background: var(--bg-tertiary); border-radius: 6px;">
            <div style="font-size: 0.75rem; color: #888;">対象論文</div>
            <div style="font-size: 0.9rem; color: #fff; font-weight: bold;">${truncateText(AppState.selectedPaperId, 35)}</div>
            <div style="font-size: 0.75rem; color: #666; margin-top: 0.25rem;">
                ${allPaths.length} パス (${result.multihop_k || 3} ホップ)
            </div>
        </div>
        <div class="analysis-actions" style="margin-bottom: 0.75rem; display: flex; gap: 0.5rem;">
            <button class="btn-primary" onclick="generateProposals()" style="flex: 1; padding: 0.6rem;">
                💡 提案を生成
            </button>
            <button class="btn-secondary" onclick="saveAnalysis()" title="分析を保存" style="padding: 0.6rem 0.8rem;">
                💾
            </button>
        </div>
        <div style="font-size: 0.8rem; color: #888; margin-bottom: 0.5rem;">発見されたパス:</div>
        <div class="analysis-results">
    `;

    allPaths.forEach((path, index) => {
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
        const response = await fetch('/api/propose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: AppState.selectedPaperId,
                analysis_result: AppState.analysisResult,
                num_proposals: 3,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        AppState.proposals = result.proposals || [];
        AppState.proposalPrompt = result.prompt || '';

        updateStatus(`提案生成完了: ${AppState.proposals.length}件`);

        // 提案タブに切り替え
        switchTab('propose');

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

    if (!AppState.proposals || !AppState.proposals.length) {
        content.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">💡</div>
                <div class="empty-state-text">提案がありません<br>分析を実行してから「提案を生成」をクリックしてください</div>
            </div>
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
        <div class="proposal-actions" style="margin-bottom: 0.75rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
            <button class="btn-primary" onclick="saveAllProposals()" title="提案を全て保存">
                💾 全て保存
            </button>
            ${AppState.proposals.length >= 2 ? `
            <button class="btn-evaluate" onclick="runEvaluation()" title="提案を評価・ランキング">
                🏆 評価を実行
            </button>
            ` : ''}
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
        ${promptHtml}
        <div class="proposal-cards">
    `;

    AppState.proposals.forEach((proposal, index) => {
        html += renderProposalCard(proposal, index);
    });

    html += '</div>';
    content.innerHTML = html;
}

function renderProposalCard(proposal, index) {
    return `
        <div class="proposal-card">
            <div class="proposal-card-header">
                <span class="proposal-title">${truncateText(proposal.title, 30)}</span>
                <div class="proposal-actions">
                    <button class="btn-icon" onclick="toggleProposalDetails(${index})" title="詳細">
                        📖
                    </button>
                    <button class="btn-icon" onclick="saveProposal(${index})" title="保存">
                        💾
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
async function runEvaluation() {
    if (!AppState.proposals || AppState.proposals.length < 2) {
        alert('評価には2件以上の提案が必要です');
        return;
    }

    updateStatus('提案を評価中... (数分かかる場合があります)');

    // 右パネルにローディング表示
    openRightPanel();
    const content = document.getElementById('rightPanelContent');
    const headerTitle = document.querySelector('.right-panel-header h3');
    if (headerTitle) headerTitle.textContent = '提案評価';
    if (content) {
        content.innerHTML = `
            <div class="loading">
                <div class="loading-spinner"></div>
            </div>
            <div style="text-align: center; color: #888; margin-top: 1rem;">
                LLMでペアワイズ比較を実行中...<br>
                <span style="font-size: 0.75rem;">${AppState.proposals.length}件の提案を評価しています</span>
            </div>
        `;
    }

    try {
        const response = await fetch('/api/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                proposals: AppState.proposals,
                include_experiment: true,
            }),
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        AppState.evaluationResult = result;

        updateStatus(`評価完了: ${result.ranking?.length || 0}件をランキング`);

        // 評価タブに切り替え
        switchTab('evaluate');

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

function renderEvaluation() {
    const content = document.getElementById('rightPanelContent');
    if (!content) return;

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

        html += `
            <div class="evaluation-rank-card ${medalClass}" data-index="${index}">
                <div class="rank-header">
                    <span class="rank-badge ${medalClass}">#${rank}</span>
                    <span class="rank-title">${truncateText(item.idea_title || '提案' + rank, 25)}</span>
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
            // 提案タイトルをIDから取得
            const proposalA = AppState.proposals.find((p, idx) => `proposal_${idx}` === comp.idea_a_id || idx === parseInt(comp.idea_a_id.replace('proposal_', '')));
            const proposalB = AppState.proposals.find((p, idx) => `proposal_${idx}` === comp.idea_b_id || idx === parseInt(comp.idea_b_id.replace('proposal_', '')));
            const titleA = proposalA?.title || comp.idea_a_id;
            const titleB = proposalB?.title || comp.idea_b_id;

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
    md += `| 順位 | 提案 | 総合スコア |\n`;
    md += `|------|------|------------|\n`;

    result.ranking.forEach((item) => {
        const title = item.idea_title || `提案${item.rank}`;
        const score = item.overall_score?.toFixed(1) || 'N/A';
        md += `| ${item.rank} | ${title} | ${score} |\n`;
    });

    md += `\n### スコア詳細\n\n`;
    result.ranking.forEach((item) => {
        const title = item.idea_title || `提案${item.rank}`;
        md += `#### ${item.rank}位: ${title}\n\n`;
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
            html += `
                <div class="history-item">
                    <div class="history-item-info" onclick="loadAnalysis(${i})" style="flex: 1; cursor: pointer;">
                        <div class="history-item-title">${truncateText(title, 24)}</div>
                        <div class="history-item-date">${date} · ${analysis.candidates_count || '?'}パス</div>
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
    if (!AppState.selectedPaperId) {
        alert('論文IDが未設定です');
        return;
    }

    updateStatus('提案を保存中...');
    let savedCount = 0;
    let failedCount = 0;

    for (const proposal of AppState.proposals) {
        try {
            const response = await fetch('/api/storage/proposals', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_paper_id: AppState.selectedPaperId,
                    target_paper_title: AppState.selectedPaperTitle,
                    proposal: proposal,
                    prompt: AppState.proposalPrompt || null,
                    rating: proposal.rating || null,
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
        const response = await fetch('/api/storage/proposals', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_paper_id: AppState.selectedPaperId,
                target_paper_title: AppState.selectedPaperTitle,
                proposal: proposal,
                prompt: AppState.proposalPrompt || null,
                rating: proposal.rating || null,
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
        const response = await fetch(`/api/storage/analyses/${saved.id}`);
        if (!response.ok) throw new Error('読み込みに失敗しました');

        const analysis = await response.json();
        AppState.analysisResult = analysis.data;
        AppState.selectedPaperId = analysis.target_paper_id;
        AppState.selectedPaperTitle = analysis.target_paper_title;
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
