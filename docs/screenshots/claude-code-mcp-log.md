# v0.3 実証ログ — Claude Code から MCP でボードに書く（demo DB）

2026-09-12 / 実装担当 / すべて **`data/demo.sqlite3`（架空データ）** に対して実施。author は `ai:demo-assistant`。

## 1. 登録（local scope・`C:\path\to\ai-taskboard` で実行）

```powershell
PS C:\path\to\ai-taskboard> claude mcp add taskboard -e TASKBOARD_DB=C:/path/to/ai-taskboard/data/demo.sqlite3 -e TASKBOARD_AUTHOR=ai:demo-assistant -e TASKBOARD_BASE_URL=http://127.0.0.1:8765 -e PYTHONUTF8=1 -- uv run --directory C:/path/to/ai-taskboard taskboard mcp
Added stdio MCP server taskboard with command: uv run --directory C:/path/to/ai-taskboard taskboard mcp to local config
File modified: C:\Users\<user>\.claude.json [project: C:\path\to\ai-taskboard]

PS C:\path\to\ai-taskboard> claude mcp get taskboard
taskboard:
  Scope: Local config (private to you in this project)
  Status: √ Connected
  Type: stdio
  Command: uv
  Args: run --directory C:/path/to/ai-taskboard taskboard mcp
  Environment:
    TASKBOARD_DB=C:/path/to/ai-taskboard/data/demo.sqlite3
    TASKBOARD_AUTHOR=ai:demo-assistant
    TASKBOARD_BASE_URL=http://127.0.0.1:8765
    PYTHONUTF8=1

PS C:\path\to\ai-taskboard> claude mcp list
Checking MCP server health…
claude.ai Google Drive: … - √ Connected
claude.ai Gmail: … - √ Connected
claude.ai Google Calendar: … - √ Connected
plugin:comfy-cloud:comfy-cloud: https://cloud.comfy.org/mcp (HTTP) - ! Needs authentication
taskboard-spike: uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py - √ Connected   ← スパイクの登録（本タスクの最後に remove）
taskboard: uv run --directory C:/path/to/ai-taskboard taskboard mcp - √ Connected
```

## 2. Claude Code がツールを呼ぶ（headless `claude -p`）

```powershell
PS C:\path\to\ai-taskboard> claude -p "Use ONLY the MCP tools of server 'taskboard'. (1) add_item workspace='blog' title='Claude Code から追加: LED 点滅の記事案（デモ）' … tags=['demo','mcp']; (2) list_items workspace='blog' query='Claude Code から追加'; (3) add_note on that item body='MCP 経由のノート（デモ）。次は写真を撮る。' Reply with the three raw JSON results." --output-format json --allowedTools "mcp__taskboard__add_item,mcp__taskboard__list_items,mcp__taskboard__add_note" --max-turns 8
# is_error=False  num_turns=5  duration_ms=13575  cost≈$0.18  session=285f474b-…
```

Claude の返答（3 ツールの structured_content そのまま）:

```json
{"id":21,"workspace":"blog","title":"Claude Code から追加: LED 点滅の記事案（デモ）","body":"- 555 と ESP32 の両方で LED を点滅させて比較する\n- ダミー項目","status":"candidate","priority":"normal","owner":null,"due":null,"tags":["demo","mcp"],"links":[],"created_by":"ai:demo-assistant","created_at":"2026-09-12T02:33:10Z","updated_at":"2026-09-12T02:33:10Z","completed_at":null,"url":"http://127.0.0.1:8765/w/blog/items/21"}
{"items":[{"id":21,"workspace":"blog","title":"Claude Code から追加: LED 点滅の記事案（デモ）","status":"candidate","priority":"normal","owner":null,"due":null,"tags":["demo","mcp"],"links":[],"created_by":"ai:demo-assistant","created_at":"2026-09-12T02:33:10Z","updated_at":"2026-09-12T02:33:10Z","completed_at":null,"url":"http://127.0.0.1:8765/w/blog/items/21"}],"total":1,"next_offset":null}
{"id":15,"item_id":21,"body":"MCP 経由のノート（デモ）。次は写真を撮る。","author":"ai:demo-assistant","created_at":"2026-09-12T02:33:13Z"}
```

- `created_by` / ノートの `author` は **サーバー側の `TASKBOARD_AUTHOR`**（ツール引数には author が無い）
- Web UI で確認: `10-kanban-after-claude-code-add.png`（候補列に #21・AI バッジ）／`11-item-detail-claude-code-mcp.png`（ノートに AI バッジ・履歴の source が `mcp`）。判定は `RESULTS-v0.3.json`

## 3. MCP Inspector CLI（v2.6.0・`--config` で環境変数を渡す）

Inspector CLI は親シェルの環境変数を子プロセスに渡さないので、設定ファイル（`docs/inspector.example.json`）で `env` を指定する。

```bash
npx --yes @modelcontextprotocol/inspector@2.6.0 --cli --config docs/inspector.example.json --server taskboard-demo --method tools/list --format json
# → list_workspaces / get_workspace_summary / list_items / get_item / add_item / update_item / move_item / add_note / complete_item（すべて outputSchema 付き）
… --method tools/call --tool-name list_workspaces --format json
# → blog(read_write) workshop(read_write) reading(read_only)   ※ hidden は出ない
… --method tools/call --tool-name add_item --tool-args-json '{"workspace":"reading","title":"Inspector から"}' --format json
# → isError: true | Error executing tool add_item: workspace 'reading' is read-only for AI
```

## 4. REST（`TASKBOARD_API_TOKEN=demo-token-change-me` で起動した demo サーバー）

```
GET  /api/v1/workspaces  (トークン未設定のサーバー)      → 404 {"detail":"REST API is disabled: set TASKBOARD_API_TOKEN to enable"}
GET  /api/v1/workspaces  Authorization: Bearer nope      → 401
GET  /api/v1/workspaces  (X-Taskboard-Author 無し)       → 400 {"detail":"X-Taskboard-Author header is required (e.g. ai:gemini-analytics)"}
GET  /api/v1/workspaces                                   → 200 blog(read_write), workshop(read_write), reading(read_only)
POST /api/v1/workspaces/blog/items {"title":"REST から追加（デモ）",…} → 201 {"id":22,"created_by":"ai:curl-demo","url":"http://127.0.0.1:8765/w/blog/items/22",…}
POST /api/v1/workspaces/reading/items                     → 403 {"detail":"workspace 'reading' is read-only for AI"}
PATCH /api/v1/items/21 {"status":"done"}                  → 400 {"detail":"status cannot be changed here: use POST /items/{id}/move"}
POST /api/v1/items/22/move {"status":"waiting_ai"}        → 200 / 同じ状態をもう一度 → 409 {"detail":"item #22 is already 'waiting_ai'"}
GET  /api/v1/items/22                                     → events: item.moved/rest, item.created/rest
GET  /api/v1/events?workspace=blog&limit=3                → note.added(mcp) / item.created(mcp) / item.moved(ui)
GET  /docs                                                → 200（OpenAPI UI）
```

curl の実コマンド例は README「REST API」節。Git Bash の curl は日本語の `-d '…'` を cp932 で送るので、JSON は UTF-8 ファイルにして `--data-binary @file` で送る（ハーネス側の注意）。
