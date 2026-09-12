# 記事用素材ノート — ai-taskboard v1.0

記事を書く担当の入口。**見せ場 → 該当コード（ファイル:行）→ スクショ／ログ**の対応表と、スパイクで詰まった点のうち記事向きのものをまとめる。記事プランそのものは [SPEC.md §8](../SPEC.md)。

> **スクショ・ログはすべてダミー DB（`data/demo.sqlite3`・`seed/demo.json`・架空データ）で撮ったもの。** author 名は `human` と `ai:demo-assistant` だけ。実運用の DB・項目・author 名（SPEC §8-3）は一切写っていないし、記事にも出さない。

行番号は v1.0.0（2026-09-12）時点。ずれたら関数名・マクロ名で探す。

---

## 0. 記事①②で共通に使う図・表

| 素材 | 場所 | 使い方 |
|:--|:--|:--|
| 3 つの入口が 1 つの service 層に集まる図 | README 冒頭の ASCII 図／SPEC §4-1 | ①の「なぜ作るか」と②の冒頭。②では「MCP は 3 本目の入口に過ぎない」を言う |
| 画面遷移（mermaid） | SPEC §2-6 | ①の画面紹介の前 |
| ER 図（mermaid）と DDL | SPEC §3-1／`src/taskboard/migrations/0001_init.sql` | ①の「履歴を残す」節。`event` テーブル（L58-69）は **追記のみ・UPDATE/DELETE しない** のコメントごと見せる |
| 既製ツールとの比較表 | SPEC §11-2（Notion／Trello／GitHub Projects／Obsidian） | ①の導入。「AI が書ける口」「ページ分割」「ローカル完結」の 3 軸 |
| 実装基盤の比較表 | SPEC §11-1（Node／Streamlit／SPA／Django／Flask／htmx 4） | ①の技術選定。**htmx 4.0 が出ているのに 2.0.10 を選んだ理由**は `spike/ENV.md §2`（htmx.org の告知文を引用） |
| 依存ライブラリと版・ライセンス | README「依存ライブラリ」 | 両記事の末尾「環境」 |
| 記事の相互リンク | ①→②「次回はここに MCP を生やす」／②→前作 MCP チュートリアル（`/posts/claude-code-mcp-server-tutorial-python/`） | SPEC §8-1／§8-2 |

---

## 1. 記事①「候補と残項目を人と AI で管理する自作 Web アプリ｜FastAPI＋SQLite＋htmx で動くまで」

位置づけ: 設計 → v0.2。**MCP は出さない**（②の引き）。

### 見せ場 A: 「なぜ既製のタスク管理ではなく作るのか」

- SPEC §1-1（置き換えるもの）・§1-3（やらないこと）・§11-2（既製ツール比較）
- 要点: AI に「書ける口」を渡したい／仕事の項目をクラウドに置きたくない／ページ（ワークスペース）ごとに AI の見え方を変えたい（`ai_policy` 3 段階）
- コード: `src/taskboard/migrations/0001_init.sql` L7-8（`ai_policy` の CHECK）、`src/taskboard/app.py` L27-31（初期ワークスペースと既定の `ai_policy`）
- スクショ: `01-workspaces.png`（ワークスペース一覧。AI からの見え方バッジ）

### 見せ場 B: htmx で「JS を書かずに列が動く」瞬間

- **カード移動は `<select>` ＋ `hx-post` だけ**: `src/taskboard/templates/_macros.html` L18-25（`move_select` マクロ）。`hx-post="/items/{id}/move"`・`hx-target="#board"`・`hx-swap="outerHTML"`・`hx-trigger="change"`。`<noscript>` の送信ボタン（L24）で JS 無しでも動く
- **サーバー側は HX-Target を見て「部分テンプレート」か「303」かを選ぶ**: `src/taskboard/routes/items.py` L32-54（`_after_write`）、`src/taskboard/deps.py` L26-31（`is_htmx` / `hx_target`）。同じ URL がブラウザのフォーム POST と htmx の両方に応える
- クイック追加も同じ型: `routes/items.py` L62-67
- **唯一の自前 JS は 5 行**: `src/taskboard/templates/base.html` L20-27。htmx は 4xx/5xx を差し込まないので、サーバーの短いエラー文を `#flash` に出すだけ
- htmx の罠（記事向き）: リスト表示の状態フィルタ `status` と、状態変更 POST の `status` が同名で衝突する。`_board.html` L3-4 の隠し `#status-filter` と `hx-include="#filters [name]:not([name=status]), #status-filter"`（`_macros.html` L19・L21）で回避
- スクショ: `02-kanban-blog.png`（かんばん）→ `03-kanban-after-quick-add.png`（クイック追加後・リロード無し）→ `04-kanban-after-move.png`（select で着手列へ）→ `05-list-blog.png`（リスト切替）
- 実ブラウザでの証拠: `docs/screenshots/RESULTS.json` の "quick add: no full reload (window marker kept)" と "move via select: … (partial update)"（headless Chrome 152 + CDP で `window` にマーカーを置き、操作後も残っている＝ページ全体は再読み込みされていない）
- テスト: `tests/test_web.py` L42（htmx ヘッダ付き POST が部分 HTML だけ返す）・L54（通常 POST は 303）

### 見せ場 C: event テーブルで「誰が書いたか」が全部残る画面

- 書き込みは **`service.py` だけ**が行い、必ず `_log_event` を呼ぶ: `src/taskboard/service.py` L26-43（`_log_event`: kind・author・payload・source）、L513-536（`move_item`: from/to/reason を payload に）
- author の形式: `src/taskboard/models.py` L36（`^(human|ai:[a-z0-9][a-z0-9._-]{0,39})$`）
- バッジ: `_macros.html` L2-8（`ai:*` は青・`human` は灰）。履歴の表: `src/taskboard/templates/_detail.html` L60-80（`item.moved` は「候補 → 着手『理由』」、`item.updated` は変更フィールド名だけ、右端に `source`）
- **本文は payload に入れない**（`tests/test_service.py` L103 のアサーション）— 履歴に機密が溜まらない設計
- スクショ: `06-item-detail.png`（詳細。AI バッジ・Markdown 表・履歴 6 件）→ `07-item-detail-after-note.png`（ノート追加後）→ `08-item-edit.png`（編集フォームを `#detail` に差し込み）
- ダークモード: `09-kanban-workshop-dark.png`（`prefers-color-scheme` だけ・`style.css` L8）

### 見せ場 D（小ネタ・任意）: SQLite を「ちゃんと」使う

- 接続ごとの PRAGMA（WAL・foreign_keys・busy_timeout）: `src/taskboard/db.py` L43-55。SQLite は既定で foreign_keys OFF
- `check_same_thread=False` の理由（FastAPI は同期依存関係をスレッドプールで動かす）: `db.py` L48-49
- オンラインバックアップ `sqlite3.Connection.backup()`: `db.py` L103-128。WAL の途中でも 1 ファイルで整合
- 前方にだけ当てるマイグレーション: `db.py` L75-89
- Markdown の安全側: `src/taskboard/render.py` L16（`html=False`）。`tests/test_web.py` L80 で `<script>` がエスケープされることを確認
- Windows の Python には tz データベースが無く `ZoneInfo("Asia/Tokyo")` が失敗する → ローカル TZ に任せる: `render.py` L36-43・README「既知の制限」

### スクショの一覧（①）

| 番号 | ファイル | 何が写っているか |
|:--|:--|:--|
| 01 | `01-workspaces.png` | ワークスペース一覧（ブログ／工作室／読書・件数・AI バッジ） |
| 02 | `02-kanban-blog.png` | ブログのかんばん 6 列 |
| 03 | `03-kanban-after-quick-add.png` | クイック追加直後（候補列に 1 枚増・リロード無し） |
| 04 | `04-kanban-after-move.png` | select で着手列へ移動した直後 |
| 05 | `05-list-blog.png` | リスト表示（`?view=list`） |
| 06 | `06-item-detail.png` | 項目の詳細（AI バッジ・Markdown 表・ノート・履歴） |
| 07 | `07-item-detail-after-note.png` | ノート追加後（Markdown 描画・即反映） |
| 08 | `08-item-edit.png` | 編集フォーム（`#detail` に差し込み） |
| 09 | `09-kanban-workshop-dark.png` | 工作室のかんばん・ダークモード |

いずれも 1280×860・demo DB。撮り直すときは `uv run taskboard seed --demo` → `TASKBOARD_DB=data/demo.sqlite3 uv run taskboard serve`。

---

## 2. 記事②「自作 Web アプリに MCP を生やして Claude Code から書き込む｜状態を持つ MCP サーバーの作り方」

位置づけ: v0.3。前作（計算＝状態なし）との差分＝**DB に書く MCP** に絞る。前作で書いた `FastMCP`→`MCPServer` 改名・`ToolError` 以外は文言が届かない・フルパス登録は**繰り返さず参照する**。

### 見せ場 A: `MCPServer` に 9 本のツールを載せ、author をサーバー側で固定する

- サーバー定義と `instructions`（AI に渡す一言）: `src/taskboard/mcp_server.py` L51-58
- **author はツール引数に無い**。環境変数 `TASKBOARD_AUTHOR` だけから決まる: `mcp_server.py` L86-97（`author()`）。`add_item` の引数（L181-189）に `author` が無いことをテストで固定: `tests/test_mcp.py` L58（`"author" not in input_schema`）
- `claude mcp add -e TASKBOARD_AUTHOR=ai:demo-assistant …` の実コマンドと `claude mcp get` の出力: `docs/screenshots/claude-code-mcp-log.md §1`
- ツール引数は `Annotated[..., Field(description=...)]` で AI 向けの説明を付ける: `mcp_server.py` L144-152（`list_items`）。docstring がツールの説明になる
- **戻り値は Pydantic モデル**（SDK が `output_schema`／`structured_content` を作る。素の `dict` では付かない）: `src/taskboard/schemas.py` 冒頭 docstring・`tests/test_mcp.py` L57（全ツールに `output_schema`）
- **stdout はプロトコル**: `mcp_server.py` L13・L284（logging は stderr）・`src/taskboard/cli.py` の `cmd_mcp`（何も print しない）。`spike/ENV.md §1` の「表示されないときの 3 大原因」の 3 つ目
- 1 呼び出し 1 接続・初回だけマイグレーション・Web が止まっていても動く: `mcp_server.py` L67-83（`session()`）

### 見せ場 B: Claude Code に頼むと、ブラウザの列に AI バッジ付きで現れる

- **実ログ**（headless `claude -p`・`--allowedTools mcp__taskboard__add_item,…`）: `docs/screenshots/claude-code-mcp-log.md §2`。`add_item` → `list_items` → `add_note` の 3 ツールの `structured_content` がそのまま載っている（`created_by: "ai:demo-assistant"`・`url` 付き）
- スクショ: `10-kanban-after-claude-code-add.png`（候補列に #21・AI バッジ）→ `11-item-detail-claude-code-mcp.png`（AI のノート・履歴の `source` が `mcp`）。判定は `RESULTS-v0.3.json`（2/2）
- 記事では `claude -p` ではなく対話セッションで「候補を 3 つ足して」と頼む場面にしてもよい（ダミー項目のみ。撮り直しは demo DB で）
- MCP の戻り値の `url`（`TASKBOARD_BASE_URL` ＋ `/w/{slug}/items/{id}`）を AI が人間に渡す運用: `src/taskboard/schemas.py` の `base_url()`

### 見せ場 C: `ToolError` で「見つからない」を返すと AI が自分で言い直せる

- service の例外を `ToolError` に読み替えるデコレータ: `mcp_server.py` L100-110（`tool_errors`）。`NotFound`／`ValidationError`／`Conflict` → モデルに届く文言
- 文言の例: `workspace 'reading' is read-only for AI`（Inspector ログ `claude-code-mcp-log.md §3`）、`item #22 is already 'waiting_ai'`（REST ログ §4・MCP でも同じ文言）、`nothing to update: pass at least one field`（`mcp_server.py` L241）
- テスト: `tests/test_mcp.py`（read_only の 5 つの書き込み系すべてが「is read-only for AI」・409／400 相当が ToolError の文言で届く）
- **未収録**: 「Claude が `ToolError` を読んで `list_items` を叩き直す」場面の実ログはまだ無い。撮るなら demo DB に対して `claude -p "workspace='blogs'（存在しない）に add_item して、失敗したら list_workspaces で正しい slug を調べてやり直して"` を `--allowedTools mcp__taskboard__list_workspaces,mcp__taskboard__add_item --output-format json` で 1 回（数十円・demo DB に 1 件増える）

### 見せ場 D: `hidden` ワークスペースが AI から本当に見えない

- 実装: `src/taskboard/service.py` L117-137（`check_ai_writable`・`ai_get_workspace`・`ai_get_item`）。hidden は `NotFound`（存在しない扱い）、read_only は `Forbidden`
- Inspector CLI で `list_workspaces` に hidden が出ない: `claude-code-mcp-log.md §3`。REST でも 404: `§4`
- テスト: `tests/test_mcp.py`（hidden の `work` は一覧に出ず ID 指定も not found）
- **注意**: demo DB には hidden のワークスペースが無い（ブログ／工作室＝read_write・読書＝read_only）。スクショで見せるなら `/w/reading/settings` で読書を `hidden` に切り替えてから `list_workspaces` を呼ぶ（設定変更は `workspace.updated` として履歴に残る。撮ったら戻す）

### 見せ場 E: Web と MCP の 2 プロセスが同じ SQLite を開く（WAL）

- `tests/test_integration.py` L64（uvicorn 子プロセス＋stdio 子プロセス。MCP の `add_item` が Web のボードに即出る／Web のノートが MCP の `get_item` で読める）
- PRAGMA: `src/taskboard/db.py` L52-54。「サーバー DB は要らない」の根拠（SPEC §11-1）

### 検証の見せ方（SPEC §8-2）

- pytest の in-memory クライアント: `tests/test_mcp.py` L39-41（`async with Client(mcp_server.mcp, raise_exceptions=True)`）。子プロセスを立てずに 9 ツールを叩ける
- Inspector CLI: `docs/inspector.example.json` を `--config` で渡す（Inspector は親シェルの環境変数を子に渡さない）。コマンド例は README「MCP Inspector で手で叩く」・ログは `claude-code-mcp-log.md §3`
- `claude mcp list` → `√ Connected`、`claude mcp get` で Environment が見える: `claude-code-mcp-log.md §1`
- `claude -p … --allowedTools mcp__taskboard__*` を「MCP の統合テスト」として使う型: `spike/ENV.md §3-3`

### スクショ・ログの一覧（②）

| 番号 | ファイル | 何が写っているか |
|:--|:--|:--|
| 10 | `10-kanban-after-claude-code-add.png` | Claude Code が `add_item` した #21 が候補列に・AI バッジ |
| 11 | `11-item-detail-claude-code-mcp.png` | #21 の詳細。AI のノート・履歴の source が `mcp` |
| — | `claude-code-mcp-log.md` | 登録コマンド・`claude mcp get/list`・`claude -p` の 3 ツール呼び出し・Inspector CLI・REST の状態コード一覧 |
| — | `RESULTS-v0.3.json` | 上 2 枚の自動判定 |
| 未撮 | `/mcp` の接続画面（対話セッション） | 前作と同じ体裁で撮る場合。demo 登録（`taskboard-demo`）で |

---

## 3. スパイクで詰まった 9 件のうち記事向きのもの（`spike/ENV.md §5`）

| # | 事象 | 記事 | 使い方 |
|:--|:--|:--|:--|
| 1 | `FastMCP` → `MCPServer` 改名（SDK v2） | ② | **前作で既出。繰り返さず参照だけ** |
| 2 | `CallToolResult.structuredContent` が無い → v2 は snake_case（`structured_content`・`output_schema`） | ② | 「SDK 2.x で書くときの小さな段差」として 1 段落 |
| 3 | `-> dict` のツールに `output_schema` が付かない → TypedDict／Pydantic で宣言 | ② | **見せ場 A の根拠**。「型注釈がそのまま出力スキーマ」は記事の核 |
| 4 | Inspector v2.6.0 が Node ≥22.19 を要求（警告付きで動いた） | ② | 脚注程度 |
| 5 | PowerShell で `npx … --` の `--` が `npx.ps1` シムに食われる（`claude.exe` はネイティブなので平気） | ② | **Windows ユーザー向けの罠として 1 節**。回避は `npx.cmd`／Git Bash／`'--'` |
| 6 | ハーネスの `print()` が cp932 で落ちる | — | 記事にしない（自分のコンソールの問題。stdio 自体は SDK が UTF-8 固定） |
| 7 | Git Bash の curl で日本語 `-d` が化ける | ② REST の注記 | 1 行（README にも書いてある） |
| 8 | headless Chrome が exit 21（長い `--user-data-dir`） | — | 記事にしない（検証ハーネスの話） |
| 9 | `python` が PATH に無い → `uv run` で統一 | ① | 「uv だけで動く」の導入に 1 行 |

追加の小ネタ（`spike/ENV.md §3`）: Claude Code は MCP サーバーの環境に `CLAUDE_PROJECT_DIR` と `PYTHONIOENCODING=utf-8:surrogateescape` を入れて起動する／同一セッション内は同じ子プロセスが生き続ける（`list_items` が直前の `add_item` を見る）／local scope の登録は他のフォルダで `claude mcp list` しても出ない（意図通り）。

---

## 4. 記事に出してはいけないもの（SPEC §8-3）

- 実運用の DB・項目・author 名。記事の author は **`ai:demo-assistant`** のみ
- 外部タスク管理の ID・チーム内のメンバー名・チーム運用の内部の話
- 「実機確認済み」などのメタ注記。事実は断定、未検証は明示
- 「仕事」ワークスペースの存在を匂わせる実データ（demo DB には無い。`hidden` の説明は demo の「読書」を切り替えて撮る）

## 5. 撮り直し・追加撮影の手順

```powershell
cd C:\path\to\ai-taskboard
uv run taskboard seed --demo                                  # data/demo.sqlite3（既存なら同タイトルはスキップ）
$env:TASKBOARD_DB = "data/demo.sqlite3"; uv run taskboard serve
# 別ターミナル: demo 用の MCP 登録（実運用と混ぜない）
claude mcp add taskboard-demo -e TASKBOARD_AUTHOR=ai:demo-assistant -e TASKBOARD_DB=C:/path/to/ai-taskboard/data/demo.sqlite3 -e PYTHONUTF8=1 -- uv run --directory C:/path/to/ai-taskboard taskboard mcp
```

スクショは 1280×860（既存と揃える）。撮り終えたら `claude mcp remove taskboard-demo -s local`。
