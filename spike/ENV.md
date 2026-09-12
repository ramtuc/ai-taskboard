# AI タスクボード 技術検証スパイク — 結果

実施日: 2026-09-12 ／ 担当: 実装担当 ／ 場所: `C:\path\to\ai-taskboard\spike\`（SPEC.md には触れていない・git 操作なし）

結論（先に）:
- **Claude Code への MCP 登録は通った**。`claude mcp add` → `claude mcp list` で `√ Connected`、さらに headless の `claude -p` から `add_item`/`list_items` を実際に呼んで日本語が往復することまで確認。
- **FastAPI＋SQLite＋HTMX の最小ページは `uv run` 一発で起動**し、実ブラウザ（headless Chrome）で hx-post の部分更新（リロード無し）を確認。127.0.0.1 のみにバインド。
- 主な詰まりは3点（§5）: ①公式 MCP Python SDK は v2 で **`FastMCP` が `MCPServer` に改名**（旧 import は消えている）②MCP Inspector v2 は **Node ≥22.19.0 要求**（この PC は 22.17.0。警告付きで動いた）③PowerShell で `npx … --` の **`--` が npx.ps1 シムに食われる**（`'--'` と引用するか `npx.cmd`）。

---

## 1. 環境の棚卸し

| 項目 | この PC | 備考 |
|:--|:--|:--|
| OS | Windows 11 Pro 10.0.26200 | シェルは Windows PowerShell 5.1.26100 と Git Bash |
| Python (`py` ランチャ) | 3.11.9 (`-3.11`), 3.10.11 (`-3.10`) | **`python` は PATH に無い**（`py` 経由か uv 経由）。3.11.9 の SQLite は 3.45.1、3.10.11 は 3.40.1 |
| uv | 0.9.21 (2025-12-30) | `C:\Users\<user>\.local\bin\uv.exe`。`uv python find` の既定は **uv 管理の CPython 3.12.12** |
| Python (uv 管理・本スパイクで採用) | 3.12.12 | **SQLite 3.50.4**。`.python-version` = 3.12 で固定 |
| node / npm / npx | v22.17.0 / 10.9.2 / 10.9.2 | `C:\Program Files\nodejs`。PowerShell では `npx` → `npx.ps1` シムに解決される（§5 の罠） |
| Claude Code CLI | 2.1.269 | `C:\Users\<user>\.local\bin\claude.exe` |
| Chrome（検証用） | 152.0.7977.83 | headless Chrome + CDP で HTMX を実ブラウザ検証 |

SQLite 版の確認コマンド（`python` が無いので uv 経由）:
```
uv run --directory C:/path/to/ai-taskboard/spike python -c "import sqlite3;print(sqlite3.sqlite_version)"   # 3.50.4
py -3.11 -c "import sqlite3;print(sqlite3.sqlite_version)"                                                  # 3.45.1
```

### Claude Code の MCP 登録（公式ドキュメント）
- Claude Code MCP リファレンス: https://code.claude.com/docs/en/mcp （`docs.claude.com/en/docs/claude-code/mcp` はここへリダイレクト）
  - 構文: `claude mcp add [options] <name> -- <command> [args...]`。**`--` より後ろがサーバー起動コマンド**（`--transport`/`--env`/`--scope` は `--` より前）
  - スコープ: `local`（既定・`~/.claude.json` の当該プロジェクト配下・自分だけ）／`project`（リポジトリの `.mcp.json`・要承認）／`user`（全プロジェクト）
  - 確認: `claude mcp list`（接続ヘルス付き）／`claude mcp get <name>`／セッション内 `/mcp`
  - stdio サーバーの環境変数に **`CLAUDE_PROJECT_DIR`**（プロジェクトルート）が入る
  - 起動タイムアウトは `MCP_TIMEOUT`（ms）、出力上限は 25,000 トークン既定（`MAX_MCP_OUTPUT_TOKENS`）
- 公式 MCP Python SDK の「ホストに繋ぐ」ページ: https://py.sdk.modelcontextprotocol.io/get-started/real-host/
  - 推奨起動コマンド: `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`
  - Claude Code 登録例: `claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`
  - 「表示されないとき」の3大原因: 相対パス／ホストが古い設定を持ったまま／**stdout に何か書いた**（stdio では stdout がプロトコル）

## 2. ライブラリの一次確認（2026-09-12 時点）

| ライブラリ | 採用版 | ライセンス | 一次資料 | 備考 |
|:--|:--|:--|:--|:--|
| FastAPI | **0.141.1** (2026-07-29) | MIT | PyPI JSON `license_expression: MIT`／https://github.com/fastapi/fastapi | requires-python ≥3.10。docs https://fastapi.tiangolo.com/ |
| Starlette（FastAPI 依存） | 1.6.0 (2026-08-08) | BSD-3-Clause | PyPI／https://github.com/Kludex/starlette | uv が解決 |
| uvicorn | **0.52.4** (2026-08-19) | BSD-3-Clause | PyPI `license_expression: BSD-3-Clause`／https://uvicorn.dev/ | |
| Jinja2 | **3.1.6** (2025-03-05) | BSD-3-Clause | PyPI classifier "BSD License"／GitHub pallets/jinja = BSD-3-Clause | FastAPI の `Jinja2Templates` が使う |
| python-multipart | **0.0.32** (2026-06-04) | Apache-2.0 | PyPI／https://github.com/Kludex/python-multipart | FastAPI の `Form(...)` に必須 |
| MCP Python SDK（`mcp`） | **2.2.0** (2026-09-07) | MIT | PyPI／docs https://py.sdk.modelcontextprotocol.io/ ／https://github.com/modelcontextprotocol/python-sdk | **v2 が安定系**（docs 明記）。1.x 系も同日 1.30.0 が出ている（並行保守）。高レベル API は **`MCPServer`**（v1 の `FastMCP` を改名）。`mcp[cli]` extra で `mcp` コマンド（`mcp dev`/`mcp run`） |
| （参考）`fastmcp`（PrefectHQ・別パッケージ） | 4.0.3 (2026-09-05) | Apache-2.0 | PyPI／https://gofastmcp.com | 公式 SDK とは別物。**今回は不採用**（公式 SDK で足りる） |
| htmx | **2.0.10** | **0BSD**（Zero-Clause BSD） | https://htmx.org/docs/#installing ／GitHub Release v2.0.10 の `LICENSE` アセット | ローカルバンドル `static/htmx.min.js`（51,238 B）。**SHA-384 が htmx.org 掲載の integrity 値と一致**: `H5SrcfygHmAuTDZphMHqBJLc3FhssKjG7w/CeCpFReSfwBWDTKpkzPP8c+cLsK+V` |
| MCP Inspector（開発時のみ） | 2.6.0 (2026-09-09) | MIT（package.json 宣言。tarball・リポジトリ root に LICENSE ファイルは見当たらず） | https://github.com/modelcontextprotocol/inspector ／`docs/cli-smoke-testing.md` | **engines: node ≥22.19.0**。v1 系は `@v1-latest`(1.0.2, node ≥22.7.5) |
| pytest / httpx（dev） | 9.1.1 / 0.28.1 | MIT / BSD-3-Clause | PyPI | `[dependency-groups] dev` |

### htmx の版について（SPEC 側で決めてほしい点）
- htmx.org トップの告知（2026-09-12 取得）: **「htmx 4.0 has been released! It is not currently marked as latest in NPM so that people using the 2.x line are not accidentally upgraded. We will mark it latest at some point in 2027.」**（詳細 https://four.htmx.org）
- npm dist-tags: `latest = 2.0.10`、`next = 4.0.0`。htmx.org/docs のインストール手順は 2.0.10 を掲示。
- スパイクは **2.0.10 を採用**（公式が現時点で latest としている系列）。4.0 は `htmx-2-compat.js` 等の互換層付きで配布されており、v1.0 記事化時点で乗り換えるかは判断事項。

## 3. MCP スパイク（`mcp_spike.py`）の実証ログ

サーバー: 公式 SDK v2 `MCPServer("ai-taskboard-spike")`、ツール `add_item(title, author)` / `list_items()` / `spike_env()`（診断用）。戻り値は `TypedDict` で宣言（素の `dict` だと output_schema が付かず構造化出力にならない — 公式 docs「Structured Output」の通り）。

### 3-1. SDK 同梱 Client での自動テスト（`tests/test_mcp_spike.py`・2件 pass）
- インメモリ `Client(server)` と、**実 stdio 子プロセス** `Client(StdioServerParameters(command="uv", args=["run","--directory",<spike>,"mcp_spike.py"]))` の両方で `add_item("日本語のタイトル ✓ 〜 ①")` → `list_items` が一致。
- 子プロセス側の `sys.stdout.encoding` は **cp932** だったが文字化けなし → SDK の `stdio_server` が stdin/stdout のバイナリバッファを **UTF-8 で再ラップ**している（`mcp/server/stdio.py` L170 のコメント「the std handles' platform encodings are unreliable」）。**stdio の文字コードは SDK 側で解決済み**。

### 3-2. MCP Inspector CLI（v2.6.0）
```
# Git Bash から（Node 22.17.0 なので EBADENGINE 警告が出るが動作した）
npx --yes @modelcontextprotocol/inspector@2.6.0 --cli uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py -- --method tools/list --format json
#  → add_item (in: title,author / out: Item), list_items (out: list_itemsOutput), spike_env (out: EnvInfo)
npx --yes @modelcontextprotocol/inspector@2.6.0 --cli uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py -- --method tools/call --tool-name add_item --tool-args-json '{"title":"日本語タイトル ✓ 〜","author":"ai:inspector"}' --format json
#  → {"result":{"content":[{"type":"text","text":"{...}"}],"structuredContent":{"id":1,"title":"日本語タイトル ✓ 〜","author":"ai:inspector","created_at":"2026-09-12T01:43:46+00:00"},"isError":false}}
#  空タイトル → {"content":[{"type":"text","text":"Error executing tool add_item: title must not be empty"}],"isError":true}
```
- Inspector CLI は 1 コマンド = 1 プロセスなので、`list_items` を別コマンドで呼ぶと空（メモリが消える）。これは仕様。
- 公式 docs 推奨形 `uv run --with "mcp[cli]==2.2.0" mcp run C:/path/to/ai-taskboard/spike/mcp_spike.py` でも接続可（`mcp run` はモジュール直下の `mcp` 変数を探す）。
- 単体起動 `uv run --directory … mcp_spike.py` は何も出力せず待機（stdin 待ち）= 正常。

### 3-3. ★Claude Code への登録（実証）
```
PS C:\path\to\ai-taskboard\spike> claude mcp add taskboard-spike -- uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py
Added stdio MCP server taskboard-spike with command: uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py to local config
File modified: C:\Users\<user>\.claude.json [project: C:\path\to\ai-taskboard\spike]

PS C:\path\to\ai-taskboard\spike> claude mcp get taskboard-spike
taskboard-spike:
  Scope: Local config (private to you in this project)
  Status: √ Connected
  Type: stdio
  Command: uv
  Args: run --directory C:/path/to/ai-taskboard/spike mcp_spike.py

PS C:\path\to\ai-taskboard\spike> claude mcp list
Checking MCP server health…
claude.ai Google Drive: … - √ Connected
claude.ai Gmail: … - √ Connected
claude.ai Google Calendar: … - √ Connected
plugin:comfy-cloud:comfy-cloud: https://cloud.comfy.org/mcp (HTTP) - ! Needs authentication
taskboard-spike: uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py - √ Connected
```
- local スコープなので **ブログリポジトリ（D:\website\electwork-hp）で `claude mcp list` しても出てこない**（確認済み・意図通り）。
- **ツールが本当に見えて呼べるかの決定打**: headless で Claude Code を起動して3ツールを呼ばせた。
```
PS C:\path\to\ai-taskboard\spike> claude -p "Using ONLY the MCP tools from the server 'taskboard-spike': (1) call add_item with title='日本語の項目 ✓' and author='ai:claude-code'; (2) then call list_items; (3) then call spike_env. Reply with exactly the raw JSON results…" --output-format json --allowedTools "mcp__taskboard-spike__add_item,mcp__taskboard-spike__list_items,mcp__taskboard-spike__spike_env" --max-turns 8
# is_error=False  num_turns=5  duration_ms=10862  (session cd9fddcd-…)
{"id":1,"title":"日本語の項目 ✓","author":"ai:claude-code","created_at":"2026-09-12T01:45:27+00:00"}
{"result":[{"id":1,"title":"日本語の項目 ✓","author":"ai:claude-code","created_at":"2026-09-12T01:45:27+00:00"}]}
{"cwd":"C:\\path\\to\\ai-taskboard\\spike","python":"3.12.12","executable":"C:\\path\\to\\ai-taskboard\\spike\\.venv\\Scripts\\python.exe","claude_project_dir":"C:\\path\\to\\ai-taskboard\\spike","stdin_encoding":"utf-8","stdout_encoding":"utf-8","pythonioencoding":"utf-8:surrogateescape"}
```
  - ツール名は `mcp__<server>__<tool>` で見える。`list_items` が `add_item` の結果を返している＝**同一セッション内は同じ子プロセスが生き続ける**。
  - Claude Code はサーバー環境に `CLAUDE_PROJECT_DIR` と **`PYTHONIOENCODING=utf-8:surrogateescape`** を入れて起動する（Inspector 経由では cp932 だった）。いずれにせよ SDK 側で UTF-8 固定なので差は出ない。
- 登録は **残してある**（次工程で本物に差し替えるまでの動作見本）。外すときは `claude mcp remove taskboard-spike -s local`（`C:\path\to\ai-taskboard\spike` で実行）。

## 4. FastAPI＋HTMX スパイク（`web_spike.py`）

- 構成: `items(id, title, author, created_at)` の1テーブル（`spike.db`・起動時 `CREATE TABLE IF NOT EXISTS`）。`GET /` = フルページ、`POST /items` = **部分テンプレート `_items.html` だけ**を返し、HTMX が `#item-list` を `outerHTML` で差し替え。`GET /api/items` = 同じ関数を REST で出す最小デモ。
- 起動: `uv run --directory C:/path/to/ai-taskboard/spike web_spike.py` → `spike: http://127.0.0.1:8000/ (pid=66556)`。ポートは `SPIKE_PORT` か 8000〜8099 の空き。
- バインド確認（netstat）: `TCP 127.0.0.1:8000 0.0.0.0:0 LISTENING 66556` — **127.0.0.1 のみ**。終了は自分の PID のみ `Stop-Process -Id 66556`。
- curl 検証: `GET /` 200（`hx-post="/items"`, `hx-target="#item-list"`, `hx-swap="outerHTML"`, `/static/htmx.min.js` 参照）／`GET /static/htmx.min.js` 200 51,238 B／`POST /items`（UTF-8 percent-encode）→ `<li>#3 日本語の項目 ✓ 〜<span class="badge ai">ai:spike</span>…` ／`<script>alert(1)</script>` は `&lt;script&gt;` にエスケープ（Jinja2 autoescape）／空白タイトルは追加されない。
- **実ブラウザ検証（headless Chrome 152 + CDP）**: ページ内 `htmx.version = "2.0.10"`（ローカルバンドル読込 OK）→ input に「ブラウザから追加 ✓」を入れて「追加」クリック → `#item-list` に `#6 ブラウザから追加 ✓` が増え、**`window.__marker` が保持＝ページリロード無し（部分更新）**、`hx-on::after-request` でフォームがリセット。RESULT: PASS。
- 自動テスト `tests/test_web_spike.py`（TestClient・4件 pass）: ローカル htmx 参照／hx-post が部分 HTML のみ返す＋autoescape／空タイトル非挿入／`HOST == "127.0.0.1"`。

## 5. 詰まった点と回避策

| # | 事象 | 原因 | 回避策 |
|:--|:--|:--|:--|
| 1 | `from mcp.server.fastmcp import FastMCP` が無い | 公式 SDK **v2 で `FastMCP` → `MCPServer` に改名**（旧 import は deprecated ではなく削除。`mcp.server.fastmcp.*` → `mcp.server.mcpserver.*`、`FastMCPError` → `MCPServerError`） | `from mcp.server import MCPServer`（v2 で書く）。公開済みの elec-calc-mcp（`mcp>=2.1,<3`）と MCP チュートリアル記事（20260903）はすでに `MCPServer` なので**同じ書き方で続編にできる**（2.1.1 → 2.2.0 で今回使った API に変更なし） |
| 2 | `CallToolResult.structuredContent` が無い | v2 は **snake_case**（`structured_content`, `output_schema`） | v2 の属性名で書く |
| 3 | `-> dict` のツールに output_schema が付かず `structured_content` が None | 型注釈がそのまま出力スキーマ。素の `dict` は対象外（`dict[str, X]`・TypedDict・BaseModel は対象）。`list[...]` は `{"result": [...]}` に包まれる | 戻り値は TypedDict／pydantic で宣言する |
| 4 | Inspector v2.6.0 が `npm warn EBADENGINE`（node ≥22.19.0 要求、実機 22.17.0） | engines 不一致（警告のみ） | そのまま動作した。**未確認: 22.17.0 で全機能が動く保証はない**。Node を 22.19 以上へ更新するか `@v1-latest`(1.0.2) を使う |
| 5 | PowerShell で `npx … <target> -- --method …` が `{"error":{"code":"error","message":"Connection closed"}}` | PowerShell では `npx` が **`npx.ps1` シム**に解決され、その `$args` が裸の `--` を「パラメータ終端」として飲み込む（`node -e` 直呼びでは `--` は渡る。`claude.exe` はネイティブ exe なので `claude mcp add … -- …` は裸でも OK だった） | `'--'` と引用する／`npx.cmd` を明示／Git Bash か cmd から実行 |
| 6 | テストハーネスの `print()` で `UnicodeEncodeError: 'cp932'` | **サーバーではなく自分のコンソール出力**が cp932 | `sys.stdout.reconfigure(encoding="utf-8")` か `PYTHONUTF8=1`。stdio プロトコル自体は SDK が UTF-8 固定なので影響なし |
| 7 | Git Bash の curl で日本語を `--data-urlencode` すると `���{��` に化ける | curl が受け取った引数バイトが cp932（ハーネスの問題） | UTF-8 の percent-encode 済み文字列を `--data` で送る。ブラウザ経由は問題なし（#3 以降・実ブラウザ PASS） |
| 8 | headless Chrome が exit 21 で即死 | `--user-data-dir` をスクラッチパッド（長い一時パス）に置いたとき | `D:\tmp\chrome-udd-*` に置く。Chrome の kill は自分の PID のみ |
| 9 | `python` コマンドが無い | PATH に 3.10 の Scripts しか無く本体が無い | `py -3.11` か **uv 経由**（プロジェクトは `.python-version`=3.12 で uv 管理 CPython を使う） |

Windows パス: `--directory C:/path/to/ai-taskboard/spike` のスラッシュ表記で uv・Claude Code・Inspector すべて通った（バックスラッシュのエスケープ地獄を避けられる）。

## 6. 再現手順（まとめ）
```
cd C:\path\to\ai-taskboard\spike
uv sync                                                        # .python-version=3.12, uv.lock で固定
uv run python -m pytest -q tests                               # 6 passed（MCP 2 + Web 4）
uv run web_spike.py                                            # http://127.0.0.1:8000/  Ctrl+C で終了
npx.cmd --yes @modelcontextprotocol/inspector@2.6.0 --cli uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py -- --method tools/list --format json
claude mcp add taskboard-spike -- uv run --directory C:/path/to/ai-taskboard/spike mcp_spike.py   # local scope
claude mcp list                                                # taskboard-spike … √ Connected
```

## 7. SPEC／次工程への申し送り
- 依存の固定値: fastapi 0.141.1 / uvicorn 0.52.4 / jinja2 3.1.6 / python-multipart 0.0.32 / mcp[cli] 2.2.0 / htmx 2.0.10（0BSD・ローカル同梱）/ Python 3.12（uv 管理）。
- MCP は公式 SDK v2 の `MCPServer` で書く。ツールの戻り値は TypedDict／pydantic で宣言（AI 側が `structured_content` を受け取れる）。エラーは `ToolError`（`isError: true` で返る）。
- Claude Code 登録は local スコープ推奨（`~/.claude.json` にプロジェクト単位で入る・リポジトリを汚さない）。チームで共有するなら `project` スコープ（`.mcp.json`・初回承認あり）。
- 記事ネタ候補（20260903 チュートリアルで既出の「FastMCP→MCPServer 改名」「ToolError」は除く）: 「TypedDict で structured_content を返す」「stdout に print すると壊れる」「PowerShell の `--` 落ち」「`claude -p` で MCP ツール呼び出しをテストする」。
- 未確認: Node 22.17.0 で Inspector v2 の Web UI（`mcp dev`）が完全に動くか（CLI モードのみ確認）。htmx 4.0 の採否。
