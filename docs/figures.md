# IdeaGraph 図表生成プロンプト集

`docs/ideagraph.md` に含まれる各図のプロンプト。画像生成AIに入力して使用する。

---

## 目次

1. [Fig.1 システム全体パイプライン](#fig1-システム全体パイプライン)
2. [Fig.2 システムアーキテクチャ](#fig2-システムアーキテクチャ)
3. [Fig.3 引用グラフの構造（抽象）](#fig3-引用グラフの構造抽象)
4. [Fig.4 引用グラフの構造（具体例）](#fig4-引用グラフの構造具体例)
5. [Fig.5 エンティティグラフの構造（抽象）](#fig5-エンティティグラフの構造抽象)
6. [Fig.6 エンティティグラフの構造（具体例）](#fig6-エンティティグラフの構造具体例)
7. [Fig.7 グラフコンテキストのプロンプト変換フロー](#fig7-グラフコンテキストのプロンプト変換フロー)
8. [Fig.8 ターゲット論文の選定戦略](#fig8-ターゲット論文の選定戦略)
9. [Fig.9 論文ダウンロードフロー](#fig9-論文ダウンロードフロー)
10. [Fig.10 要素抽出パイプライン](#fig10-要素抽出パイプライン)
11. [Fig.11 再帰的グラフ成長（優先度BFS）](#fig11-再帰的グラフ成長優先度bfs)
12. [Fig.12 マルチホップ分析フロー](#fig12-マルチホップ分析フロー)
13. [Fig.13 パススコアリング計算式](#fig13-パススコアリング計算式)
14. [Fig.14 プロンプトスコープの3種類](#fig14-プロンプトスコープの3種類)
15. [Fig.15 アイデア生成パイプライン](#fig15-アイデア生成パイプライン)
16. [Fig.16 評価モードの概要](#fig16-評価モードの概要)
17. [Fig.17 Pairwise評価とスワップテスト](#fig17-pairwise評価とスワップテスト)
18. [Fig.18 ELOレーティング計算](#fig18-eloレーティング計算)
19. [Fig.19 実験フレームワーク全体フロー](#fig19-実験フレームワーク全体フロー)

---

## Fig.1 システム全体パイプライン

**セクション**: 1.1 システムの全体像

**説明**: IdeaGraphの5段階パイプラインを左から右に流れるフロー図。

```
Prompt:

Create a clean, professional horizontal pipeline diagram for an academic paper. The diagram shows 5 sequential stages flowing left to right, connected by arrows. Use a white background with a modern flat design style.

The 5 stages are:
1. "Graph Construction" (labeled "Ingestion" below) — icon: a stack of papers being fed into a graph database
2. "Multi-hop Analysis" (labeled "Analysis" below) — icon: a magnifying glass over graph paths
3. "Prompt Generation" (labeled "Prompt Context" below) — icon: a document with graph snippet
4. "Idea Generation" (labeled "Proposal" below) — icon: a lightbulb with brain/AI
5. "Evaluation" (labeled "Evaluation" below) — icon: a checklist with star ratings

On the far left, show a cluster of academic paper icons as the input. Each stage is a rounded rectangle with a subtle gradient. Arrows between stages have a consistent style. Below the main flow, show small labels: "(ingestion)", "(analysis)", "(prompt_context)", "(proposal)", "(evaluation)".

Color scheme: professional blues and grays. No text in Japanese. Dimensions: 1200x300px, suitable for embedding in an academic paper.
```

---

## Fig.2 システムアーキテクチャ

**セクション**: 1.3 アーキテクチャ

**説明**: CLI/API/UIの3層アーキテクチャ。CLI・APIが共通サービス層を経由し、Neo4j/Cacheにアクセスする。

```
Prompt:

Create a clean system architecture diagram for an academic paper. White background, flat design.

Layout (left to right, with branching):
- Left side: Two entry points stacked vertically:
  - Top: "CLI" box (labeled "cli.py") with terminal icon
  - Bottom: "Web API" box (labeled "app.py") with API icon
  - Below Web API: "Web UI" box (labeled "app.js") with browser icon, arrow pointing UP to Web API

- Both CLI and Web API have arrows pointing right to a central "Services" box (larger, emphasized)
- Services box has arrow pointing right to "Models" box (labeled "Pydantic")
- Models box has arrows pointing right to two destinations stacked vertically:
  - "Neo4j" (graph database icon, cylinder shape)
  - "File Cache" (folder icon, cylinder shape)

Use rounded rectangles for components. Color code: entry points in blue, services in green, data stores in orange. Dimensions: 900x400px. No Japanese text.
```

---

## Fig.3 引用グラフの構造（抽象）

**セクション**: 2.1 論文のつながりのグラフ化 — 抽象的な概念図

**説明**: 論文間のCITES（引用）関係を示すグラフ。エッジにimportance_score、citation_type、contextの3属性が付与されている。

```
Prompt:

Create a knowledge graph diagram showing academic paper citation relationships for a research paper figure. White background, clean academic style.

Graph structure:
- 4 circular nodes representing papers, labeled "Paper A", "Paper B", "Paper C", "Paper D"
- Paper nodes are blue circles (large, prominent)

Directed edges (arrows) between papers:
1. Paper A → Paper B: labeled "CITES", with attributes shown: "importance=5, type=EXTENDS, context='...'"
2. Paper B → Paper C: labeled "CITES", with attributes: "importance=3, type=USES, context='...'"
3. Paper A → Paper D: labeled "CITES", with attributes: "importance=4, type=COMPARES"

Edge styling:
- Thicker edges = higher importance score
- Edge labels show the three attributes (importance_score, citation_type, context) in a small annotation box or inline

Include a small legend box in the corner explaining:
- Edge thickness = importance (1-5)
- citation_type: EXTENDS / COMPARES / USES / BACKGROUND / MENTIONS
- context: free-text description

Dimensions: 900x500px. No Japanese text. Professional academic figure style.
```

---

## Fig.4 引用グラフの構造（具体例）

**セクション**: 2.1 論文のつながりのグラフ化 — 具体例

**説明**: "Attention Is All You Need" を中心とした具体的な引用グラフ。

```
Prompt:

Create a knowledge graph diagram showing real academic paper citations, suitable for an academic paper figure. White background.

Central node (blue, large):
- "Attention Is All You Need"

Three outgoing CITES edges to:
1. → "Sequence to Sequence Learning" — Edge label: "CITES (importance=5, EXTENDS)" — Small annotation below: "Our model replaces recurrence with attention mechanisms"
2. → "Neural Machine Translation by Jointly Learning to Align and Translate" — Edge label: "CITES (importance=4, COMPARES)" — Annotation: "Comparison baseline for attention-based translation"
3. → "Layer Normalization" — Edge label: "CITES (importance=3, USES)" — Annotation: "Applied after each sub-layer"

Edge styling: thicker line for higher importance. Use color coding: EXTENDS=red-orange, COMPARES=blue, USES=green.

Paper nodes are rounded rectangles with the paper title inside. Dimensions: 1000x500px. Clean academic style.
```

---

## Fig.5 エンティティグラフの構造（抽象）

**セクション**: 2.2 論文の内容のグラフ化 — 抽象的な概念図

**説明**: 論文→エンティティの MENTIONS 関係、エンティティ間の EXTENDS/ADDRESSES 関係を示す。

```
Prompt:

Create a heterogeneous knowledge graph diagram for an academic paper. White background, clean style.

Two types of nodes:
1. Paper nodes (blue circles): "Paper A", "Paper B"
2. Entity nodes (diamond shapes, color-coded by type):
   - "Method: Technique X" (orange diamond)
   - "Dataset: Dataset Y" (purple diamond)
   - "Method: Technique Z" (orange diamond)
   - "Challenge: Problem W" (red diamond)

Edges:
- Paper A → Method: Technique X (green arrow, labeled "MENTIONS")
- Paper A → Dataset: Dataset Y (green arrow, labeled "MENTIONS")
- Paper B → Method: Technique X (green arrow, labeled "MENTIONS") — emphasize this shared entity with a highlight or annotation "Same entity shared across papers"
- Method: Technique X → Method: Technique Z (orange dashed arrow, labeled "EXTENDS")
- Challenge: Problem W → Method: Technique X (purple dashed arrow, labeled "ADDRESSES")

Include a legend showing entity types and their colors:
- Method: orange
- Dataset: purple
- Task: pink
- Challenge: red
- Framework: green

Dimensions: 900x550px. No Japanese text.
```

---

## Fig.6 エンティティグラフの構造（具体例）

**セクション**: 2.2 論文の内容のグラフ化 — 具体例

**説明**: "Attention Is All You Need" 論文から抽出されたエンティティとその関係。

```
Prompt:

Create a knowledge graph diagram showing entities extracted from a real paper, for an academic figure. White background.

Central paper node (blue rounded rectangle):
- "Attention Is All You Need"

Connected to entity nodes via green "MENTIONS" arrows:
1. → "Transformer" (orange diamond, labeled "Method")
2. → "Multi-Head Attention" (orange diamond, labeled "Method")
3. → "Machine Translation" (pink diamond, labeled "Task")
4. → "WMT 2014" (purple diamond, labeled "Dataset")
5. → "BLEU score" (gray diamond, labeled "Metric")

Entity-to-entity relationships:
- "Multi-Head Attention" → "Transformer" (orange dashed arrow, labeled "COMPONENT_OF")
- "Transformer" → "Long-Range Dependencies" (red diamond, labeled "Challenge"; purple dashed arrow labeled "ADDRESSES")

Color coding consistent with entity types. Diamond shapes for entities, rounded rectangle for the paper. Dimensions: 1000x600px. Clean academic style.
```

---

## Fig.7 グラフコンテキストのプロンプト変換フロー

**セクション**: 2.3 グラフ構造のプロンプト

**説明**: 分析結果をMermaid図やPaths形式に変換し、LLMプロンプトコンテキストとして組み込むフロー。

```
Prompt:

Create a flowchart diagram for an academic paper showing how graph analysis results are converted into LLM prompt context. White background, clean style.

Flow (left to right):
1. Input: "Target Paper" (blue rectangle)
2. → "Path Exploration" (rounded rectangle, process)
3. → "Scoring" (rounded rectangle, process)
4. → "Filtering" (rounded rectangle, process)
5. → Fork into two output formats (shown as two parallel boxes):
   a. "Mermaid Diagram" — with a small code snippet preview showing "graph LR / N1[Paper A] --> N2[Paper B]"
   b. "Paths Format" — with a small code snippet preview showing "1. Paper A -(CITES)-> Paper B -(CITES)-> Paper C"
6. Both formats feed into → "LLM Prompt Context" (large highlighted box)

Above the flow, label "Analysis Result" spanning steps 2-4. Use arrows to show the data flow. Professional color scheme: blues and grays. Dimensions: 1100x400px.
```

---

## Fig.8 ターゲット論文の選定戦略

**セクション**: 3.1 ターゲット論文の選定方法

**説明**: 5つのターゲット論文選定戦略を示すツリー図。

```
Prompt:

Create a tree diagram for an academic paper showing target paper selection strategies. White background, clean flat design.

Root node: "Paper Selection Strategy" (large, centered at left)

Branches to 6 leaf nodes (right side):
1. "manual" — description: "Manual specification"
2. "random" — description: "Random sampling"
3. "connectivity" — description: "Top by CITES out-degree"
4. "connectivity_stratified" — description: "Out-degree 3-tier equal sampling"
5. "in_degree" — description: "Top by CITES in-degree"
6. "in_degree_stratified" — description: "In-degree 3-tier equal sampling"

For "connectivity_stratified", add a small illustration showing a histogram divided into 3 tiers (low/medium/high) with equal sampling from each tier.

Use a horizontal tree layout. Each leaf is a rounded rectangle. Color the stratified strategies slightly differently to emphasize they are recommended. Dimensions: 1000x400px.
```

---

## Fig.9 論文ダウンロードフロー

**セクション**: 3.2 論文のダウンロード

**説明**: タイトルからarXiv API → Semantic Scholar APIへのフォールバック付きダウンロードフロー。

```
Prompt:

Create a decision flowchart for an academic paper showing the paper download process. White background, clean style.

Flow:
1. Start: "Paper Title" (oval)
2. → Decision diamond: "arXiv API Search"
3. If success → "Download LaTeX Source (tar.gz)" (green box)
   - If LaTeX fails → "Download PDF" (yellow box, fallback)
4. If arXiv fails → Decision diamond: "Semantic Scholar API Search"
5. If success → "Download Open Access PDF" (green box)
6. If fails → "Recorded as 'not_found'" (red/gray box)

Add small icons: arXiv logo placeholder near step 2, Semantic Scholar near step 4. Use green for success paths, red for failure paths. Success/failure labels on arrows from decision diamonds. Dimensions: 600x700px (vertical layout).
```

---

## Fig.10 要素抽出パイプライン

**セクション**: 3.4 要素抽出

**説明**: 論文ファイルから前処理→LLM抽出→後処理を経てExtractedInfoを生成するパイプライン。

```
Prompt:

Create a horizontal pipeline diagram for an academic paper showing the information extraction process from papers. White background.

4 stages left to right, connected by thick arrows:

1. "Paper File" (input)
   - Sub-labels: "LaTeX (tar.gz)" and "PDF"
   - Icon: document

2. "Preprocessing" (rounded rect, light blue)
   - Sub-labels: "tar.gz extraction", "bibliography parsing", "reference number mapping"
   - For PDF: "Base64 encoding"

3. "LLM Extraction" (rounded rect, light green)
   - Label: "Gemini (structured output)"
   - Sub-items: "summary, claims, entities, relations, cited_papers"
   - Icon: brain/AI chip

4. "Postprocessing" (rounded rect, light yellow)
   - Sub-labels: "Reference number → title resolution", "Title normalization", "Fallback LLM extraction"

5. Output: "ExtractedInfo" (output box, emphasized)
   - Show a small JSON-like schema: {paper_summary, claims, entities, relations, cited_papers}

Dimensions: 1200x350px. Professional academic figure style.
```

---

## Fig.11 再帰的グラフ成長（優先度BFS）

**セクション**: 3.6 再帰的な構築によるグラフの成長

**説明**: シード論文から重要度優先の幅優先探索でグラフが段階的に拡大する様子。

```
Prompt:

Create a diagram for an academic paper showing recursive graph growth via priority-based breadth-first search. White background.

Show 3 depth levels (top to bottom or left to right):

Depth 0 (top):
- 2 seed paper nodes: "Seed Paper A" and "Seed Paper B" (blue circles, large)
- Label: "Depth 0: Dataset papers"

Depth 1 (middle):
- 4 paper nodes branching from the seeds:
  - From A: "Paper C (imp=5)" and "Paper D (imp=4)" — connected by arrows labeled with importance scores
  - From B: "Paper E (imp=5)" and "Paper F (imp=4)"
- Label: "Depth 1: Top-N citations"
- Annotation: "Priority queue sorts by (-importance, depth)"

Depth 2 (bottom):
- 2-3 additional paper nodes branching from depth 1 nodes
- "Paper G (imp=5)" from Paper C, "Paper H (imp=3)" from Paper D
- Label: "Depth 2: Further citations"

On the right side, show a priority queue visualization:
- A vertical list sorted by priority: "(-5, 1) Paper C", "(-5, 1) Paper E", "(-4, 1) Paper D", "(-4, 1) Paper F", etc.

Use fading opacity or smaller node sizes at deeper levels to show diminishing priority. Dimensions: 900x600px.
```

---

## Fig.12 マルチホップ分析フロー

**セクション**: 4.1 マルチホップ分析

**説明**: ターゲット論文からのパス探索→Paper引用パスとEntity関連パスへの分類→スコアリング→ランキング。

```
Prompt:

Create a flowchart for an academic paper showing the multi-hop analysis process. White background.

Flow:
1. Input: "Target Paper" (blue node on the left)
2. → "Neo4j Path Exploration" (large process box)
   - Label: "1..max_hops"
   - Show a small graph snippet inside with nodes and edges

3. Fork into two parallel branches:
   a. "Paper Citation Paths" (blue box)
      - Description: "Paths containing CITES edges"
      - Small illustration: Paper → CITES → Paper → CITES → Paper
   b. "Entity Relation Paths" (orange box)
      - Description: "Paths with MENTIONS and entity relations only"
      - Small illustration: Paper → MENTIONS → Entity → EXTENDS → Entity

4. Both branches → "Scoring" (green process box)
   - Formula hint: "importance + type_score + relation_score - length_penalty + base"

5. → "Ranking" (output box)
   - Description: "Sorted by score descending"
   - Show a small ranked list: "#1 Score=144, #2 Score=132, ..."

Dimensions: 1100x500px. Professional style with consistent colors.
```

---

## Fig.13 パススコアリング計算式

**セクション**: 4.2 重要度の算出方法

**説明**: パススコアの各構成要素とその重み付けを示す分解図。

```
Prompt:

Create an infographic-style formula breakdown diagram for an academic paper. White background, clean typography.

Central formula (large, prominent):
"Path Score = Citation Importance + Citation Type + Entity Relation + Length Penalty + Base Score"

Below the formula, show 5 component boxes arranged horizontally, each with:

1. "Citation Importance Score" (blue box)
   - Formula: "Σ importance_score × 2.0"
   - Example: "(5 + 3) × 2.0 = 16.0"

2. "Citation Type Score" (green box)
   - Table: "EXTENDS=20, COMPARES=15, USES=12, Other=10"
   - Example: "1×20 + 1×12 = 32"

3. "Entity Relation Score" (orange box)
   - Table: "EXTENDS=10, ENABLES=9, USES=8, IMPROVES=8, COMPARES=7, ADDRESSES=6, MENTIONS=3"

4. "Length Penalty" (red box)
   - Formula: "-path_length × 2.0"
   - Example: "-2 × 2.0 = -4.0"

5. "Base Score" (gray box)
   - Value: "100"
   - Note: "Ensures all scores are positive"

At the bottom, show a worked example:
"Example: Paper A -(CITES, EXTENDS, imp=5)→ Paper B -(CITES, USES, imp=3)→ Paper C"
"= 16.0 + 32 + 0 + (-4.0) + 100 = 144.0"

Dimensions: 1200x550px. Use color-coded boxes matching the formula components.
```

---

## Fig.14 プロンプトスコープの3種類

**セクション**: 4.3 プロンプトの設計方法

**説明**: path / k_hop / path_plus_k_hop の3種類のプロンプトスコープの違いを可視化。

```
Prompt:

Create a 3-panel comparison diagram for an academic paper showing three prompt scope types. White background.

All three panels share the same base graph with a central "Target Paper" node (highlighted in red/gold) and surrounding paper/entity nodes.

Panel 1: "path" scope
- Only the scored analysis paths are highlighted (e.g., 3 paths radiating from the target)
- Other nodes are grayed out
- Label: "path — Analysis paths only"
- Caption: "Most focused; directly relevant information only"

Panel 2: "k_hop" scope
- All nodes within k=2 hops of the target are highlighted (flood-fill style)
- Analysis paths are not specifically emphasized
- Label: "k_hop — k-hop neighborhood"
- Caption: "Broad coverage; may include unscored relations"

Panel 3: "path_plus_k_hop" scope
- Both the analysis paths AND the k-hop neighborhood are highlighted
- Maximum coverage shown
- Label: "path_plus_k_hop — Both combined"
- Caption: "Maximum information; potential noise increase"

Use a consistent graph layout across all 3 panels. Highlighted = full color, non-highlighted = light gray. Dimensions: 1200x450px (3 panels side by side).
```

---

## Fig.15 アイデア生成パイプライン

**セクション**: 5.1 生成方法

**説明**: グラフコンテキスト＋プロンプトテンプレート→LLM→構造化出力→ProposalResult のパイプライン。

```
Prompt:

Create a vertical pipeline diagram for an academic paper showing the idea generation process. White background.

Flow (top to bottom):
1. Two inputs merging:
   a. "Graph Context" (blue box with a small Mermaid diagram icon)
   b. "Prompt Template" (gray box with a document icon)
   → These merge with a "+" symbol

2. → "LLM" (large centered box)
   - Label: "GPT-5.2 (temperature=0.0)"
   - Icon: brain/AI
   - Emphasis on "Structured Output"

3. → "Pydantic Model Validation" (small process box)

4. → "ProposalResult" (output box, emphasized with border)
   - Show N proposal cards fanning out:
     - Each card shows: "Title", "Rationale", "Method", "Experiment Plan"
   - Label: "N research proposals"

On the right side, show a comparison with two alternative methods:
- "IdeaGraph" (with graph context) — main flow
- "Direct LLM" (without graph, only paper info) — simplified flow
- "CoI-Agent" (external process) — separate flow

Dimensions: 800x700px.
```

---

## Fig.16 評価モードの概要

**セクション**: 6.1 評価の概要

**説明**: Pairwise評価とSingle評価の2つのモードを比較する概要図。

```
Prompt:

Create a comparison diagram for an academic paper showing two evaluation modes. White background.

Split into two halves:

LEFT: "Pairwise Evaluation"
- Show pairs of idea cards being compared: Idea A vs Idea B
- Arrow → "LLM Judge" → outputs "A wins / B wins / Tie" for each metric
- Below: "All pairs compared (O(n²))"
- Below: Show a matrix/bracket visualization
- Bottom: "→ ELO Ratings" with a ranked list

RIGHT: "Single (Absolute) Evaluation"
- Show individual idea cards being scored independently
- Arrow → "LLM Judge" → outputs scores "1-10" for each metric
- Below: "Each idea scored independently (O(n))"
- Below: Show individual score cards
- Bottom: "→ Average Score Ranking"

Shared elements (center):
- "5 Evaluation Metrics" box listing:
  1. Novelty
  2. Significance
  3. Feasibility
  4. Clarity
  5. Effectiveness

Use blue for Pairwise side, green for Single side. Dimensions: 1100x600px.
```

---

## Fig.17 Pairwise評価とスワップテスト

**セクション**: 6.3 Pairwise評価とスワップテスト

**説明**: 位置バイアス補正のためのスワップテストのフロー。AB順とBA順の2回評価→結果比較→一致/不一致の判定。

```
Prompt:

Create a detailed flowchart for an academic paper showing the swap test mechanism for position bias correction in pairwise evaluation. White background.

Flow:
1. Input: "Pair (A, B)" — two idea cards

2. Fork into two parallel evaluation paths:

   Path 1 (top):
   - Label: "Order 1: [A, B]"
   - → "LLM Evaluation" → "Result AB"
   - Show result: "Per metric: 0=A wins, 1=B wins, 2=Tie"

   Path 2 (bottom):
   - Label: "Order 2: [B, A]" (swapped)
   - → "LLM Evaluation" → "Result BA"
   - Show result: same format

3. "Normalize BA" step:
   - "Convert BA to original order: 0→1, 1→0, 2→2"

4. Merge → "Consistency Check" (diamond decision):

   If AB == BA_normalized:
   → "Adopt result as-is" (green output) ✓

   If AB ≠ BA_normalized:
   → "Force TIE (inconsistent)" (yellow output) ⚠

Include a small annotation: "Position bias: LLMs tend to favor the first-presented option"

Dimensions: 1000x550px. Use parallel layout for the two paths.
```

---

## Fig.18 ELOレーティング計算

**セクション**: 6.4 ELOレーティング

**説明**: ELOレーティングの計算フローと数式。

```
Prompt:

Create an infographic for an academic paper explaining the ELO rating calculation used for ranking research ideas. White background.

Structure:

Top section: "ELO Rating System"
- Initial rating: "All ideas start at 1000.0"
- K-factor: "K = 32.0"

Middle section: "Update Formula" (show mathematical formulas clearly)
1. Expected win rate: E_A = 1 / (1 + 10^((R_B - R_A) / 400))
2. New rating: R'_A = R_A + K × (S_A - E_A)
   where S_A = 1.0 (win), 0.5 (tie), 0.0 (loss)

Bottom section: "Process"
- Show a small tournament bracket or round-robin table
- "Each pairwise result updates both participants' ratings"
- "Per-metric ELO → Overall = average of 5 metric ELOs"

Right side: Visual example
- Before: "Idea A: 1000, Idea B: 1000"
- Match result: "A wins"
- After: "Idea A: 1016, Idea B: 984"

Dimensions: 900x500px. Clean mathematical typography.
```

---

## Fig.19 実験フレームワーク全体フロー

**セクション**: 7.1 実験フレームワーク

**説明**: YAML設定ファイルからExperimentRunner実行、結果ディレクトリ出力までの全体フロー。

```
Prompt:

Create a flowchart for an academic paper showing the experiment framework execution flow. White background.

Flow (top to bottom or left to right):

1. Input: "YAML Config File" (document icon)
   - Show a small YAML snippet: "experiment: EXP-101 / targets: connectivity_stratified / conditions: [ideagraph, direct_llm, coi]"

2. → "Pydantic Validation" (small process)

3. → "Target Paper Selection" (process box)
   - Sub-label: "Selection strategy (e.g., connectivity_stratified)"

4. → "For each paper × each condition:" (loop indicator)

5. → "Proposal Generation" (process box)
   - 3 sub-boxes: "IdeaGraph", "Direct LLM", "CoI-Agent"

6. → "Evaluation" (process box)
   - Sub-labels: "Single / Pairwise / Both"

7. → Output: "Results Directory" (folder icon)
   Show directory tree:
   - config.yaml
   - metadata.json
   - proposals/ (ideagraph/, direct_llm/, coi/)
   - evaluations/ (single/, pairwise/)
   - summary.json
   - report.md

Add a "Cache" box on the side with bidirectional arrows to steps 4-5, labeled "ExperimentCache (skip if cached)".

Dimensions: 800x800px (vertical layout) or 1200x500px (horizontal).
```

---

## 使用上の注意

- 各プロンプトは英語で記述しているが、必要に応じて日本語ラベルを追加指示できる。
- 画像生成AIの種類（DALL-E、Midjourney、Stable Diffusion等）によってプロンプトの調整が必要な場合がある。
- 学術論文向けの図として使用する場合は、以下を追加指示すると良い：
  - `"Vector-style, suitable for printing at 300 DPI"`
  - `"No decorative elements, minimal and professional"`
  - `"Use only black, white, and 2-3 accent colors"`
- Mermaid.jsやdraw.io等のツールで直接作成する場合は、上記プロンプトを構造の仕様書として使用できる。
