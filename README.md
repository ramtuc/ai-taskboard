# ai-taskboard

人と AI が一緒に書く「候補・残項目」ボード。ワークスペース（＝ページ）ごとにかんばん／リストで管理し、**誰が書いたか（human / ai:名前）を全操作で残す**ローカル専用の Web アプリです。

- FastAPI + SQLite（1 ファイル）+ htmx 2.0.10（ローカル同梱・ビルド工程なし）
- Python 3.12（uv 管理）／`uv run` だけで起動
- Web UI（ワークスペース・かんばん 6 列・リスト表示・詳細・Markdown 本文・ノート・履歴・タグ・リンク・フィルタ）・取り込み・バックアップ
- **MCP サーバー（stdio）**: Claude Code などの AI が同じボードを読み書きする口（公式 MCP Python SDK 2.x）
- **REST API `/api/v1`**: 他の AI・スクリプト用（Bearer トークン必須）
- 3 つの入口（UI・MCP・REST）はすべて同じ service 層を呼ぶので、誰が書いても同じ履歴が残る

設計仕様は [SPEC.md](SPEC.md)、技術検証の記録は [spike/ENV.md](spike/ENV.md)。

## 起動

```powershell
cd E:\prog\ai-taskboard
uv sync                      # 初回のみ（.venv を作って依存を入れる）
uv run taskboard serve       # http://127.0.0.1:8765/
```

初回起動時に `data/taskboard.sqlite3` を作り、初期ワークスペース **ブログ `/w/blog`・仕事 `/w/work`（AI 非公開）・開発 `/w/dev`** を用意します。停止は Ctrl+C。

## CLI

| コマンド | 何をするか |
|:--|:--|
| `uv run taskboard serve [--port 8765] [--db PATH] [--reload]` | Web UI を起動（**127.0.0.1 固定**。`--host` はありません） |
| `uv run taskboard init-db [--db PATH]` | DB の作成・マイグレーション・初期ワークスペース |
| `uv run taskboard seed --demo [--db PATH]` | ダミーデータを **`data/demo.sqlite3`**（通常 DB とは別ファイル）へ投入 |
| `uv run taskboard import FILE.json\|FILE.csv [--dry-run] [--author human]` | 取り込み（下記） |
| `uv run taskboard backup [--keep 30] [--dir DIR]` | `data/backups/` へオンラインバックアップ |
| `uv run taskboard mcp` | MCP サーバー（stdio）。通常は Claude Code が子プロセスとして起動する（下記） |

`--db` を省略すると環境変数 `TASKBOARD_DB`、それも無ければ `data/taskboard.sqlite3` を使います。ポートは `TASKBOARD_PORT` でも指定できます。

## 画面

| URL | 画面 |
|:--|:--|
| `/` | ワークスペース一覧（状態別の件数・AI からの見え方バッジ） |
| `/w/{slug}` | かんばん（候補／着手／待ち（人）／待ち（AI）／完了／保留）。`?view=list` でリスト、`?tag=`・`?owner=`・`?q=`・`?status=`（リストのみ）で絞り込み |
| `/w/{slug}/items/{id}` | 項目の詳細（Markdown 本文・ノート・履歴・タグ・リンク）。編集・状態変更・完了・ノート追加は htmx で部分更新 |
| `/workspaces/new`・`/w/{slug}/settings` | ワークスペースの追加・設定（名前・説明・`ai_policy`・アーカイブ） |
| `/healthz` | 稼働確認 JSON |

- Web UI からの書き込みは常に author = `human`。すべての変更が `event` テーブルに（author・種別・前後の値・時刻・source）残り、詳細画面の「履歴」に出ます
- `ai:*` が作った項目・ノートは青いバッジ、`human` は灰色のバッジ
- 状態は「状態を変更」のセレクト（かんばん・リスト・詳細）からだけ変えられます。編集フォームでは変えられません（履歴を必ず残すため）
- 削除機能はありません。「保留」列とワークスペースのアーカイブで代用します

## MCP サーバー（Claude Code から書く）

MCP サーバーは Web サーバーとは**別プロセス**で、同じ SQLite ファイルを直接開きます（WAL）。Web が止まっていても動きます。

| 環境変数 | 意味 |
|:--|:--|
| `TASKBOARD_AUTHOR` | **書き込みの author（`ai:<名前>`・必須）**。ツール引数では変えられない（なりすまし防止）。未設定だと読み取りだけ |
| `TASKBOARD_DB` | SQLite ファイル（省略時 `data/taskboard.sqlite3`。`uv run --directory` で起動すると相対パスの基準はプロジェクト） |
| `TASKBOARD_BASE_URL` | 戻り値の `url` の土台（省略時 `http://127.0.0.1:8765`）。AI が「ここを見て」と人間に渡す URL になる |

### Claude Code への登録

```powershell
# local scope（このフォルダで claude を起動したときだけ見える。~/.claude.json に入る）
claude mcp add taskboard -e TASKBOARD_AUTHOR=ai:claude-manager -e TASKBOARD_DB=E:/prog/ai-taskboard/data/taskboard.sqlite3 -e PYTHONUTF8=1 -- uv run --directory E:/prog/ai-taskboard taskboard mcp

# どのフォルダからでも使うなら user scope
claude mcp add -s user taskboard -e TASKBOARD_AUTHOR=ai:claude-manager -e TASKBOARD_DB=E:/prog/ai-taskboard/data/taskboard.sqlite3 -e PYTHONUTF8=1 -- uv run --directory E:/prog/ai-taskboard taskboard mcp

claude mcp list          # taskboard: … - √ Connected
claude mcp get taskboard # 登録内容の確認。外すときは claude mcp remove taskboard -s local（または -s user）
```

- `--` より後ろがサーバーの起動コマンド。パスは絶対パス（`E:/...` のスラッシュ表記で OK）
- Claude Code 内では `/mcp` で接続状態が見え、ツールは `mcp__taskboard__add_item` のような名前で呼ばれる。書き込み系（add／update／move／note／complete）を許可リストに入れるなら `mcp__taskboard__*`
- 記事・デモ用は `TASKBOARD_DB=E:/prog/ai-taskboard/data/demo.sqlite3` と `TASKBOARD_AUTHOR=ai:demo-assistant` で別登録する（実運用の DB と混ぜない）
- MCP Inspector で手で叩くときは `docs/inspector.example.json` を `--config` で渡す（Inspector CLI は親シェルの環境変数を子プロセスに渡さない）:
  `npx --yes @modelcontextprotocol/inspector@2.6.0 --cli --config docs/inspector.example.json --server taskboard-demo --method tools/list`

### ツール（SPEC §4-2）

| ツール | 何をするか |
|:--|:--|
| `list_workspaces()` | AI から見えるワークスペース（hidden は出ない）と状態別件数 |
| `get_workspace_summary(workspace)` | 件数・期限切れ・`waiting_ai` の項目・直近 20 イベント。**セッション開始時にまず呼ぶ** |
| `list_items(workspace, status?, tag?, owner?, query?, limit=50, offset=0)` | 一覧（本文なし）・`next_offset` |
| `get_item(item_id)` | 本文・ノート・履歴 |
| `add_item(workspace, title, body?, priority?, owner?, due?, tags?, links?)` | 候補を追加 |
| `update_item(item_id, …)` | 属性の変更（`status` は受けない） |
| `move_item(item_id, status, reason?)` | 列の移動（同じ状態へは 409 相当のエラー） |
| `add_note(item_id, body)` | ノート追記 |
| `complete_item(item_id, summary?)` | 完了（summary は完了ノートに） |

失敗は `ToolError` としてモデルに文言が届く（「workspace 'x' not found」「is read-only for AI」「already 'done'」など）ので、AI が自分で言い直せる。

## REST API（`/api/v1`）

他の AI（BlogAnalytics など）やスクリプト用。**`TASKBOARD_API_TOKEN` を設定して起動したときだけ有効**（未設定なら `/api/v1/*` は 404 を返す）。

```powershell
$env:TASKBOARD_API_TOKEN = "長いランダム文字列"      # トークンはシェルの環境変数か .env（.gitignore 済み）に置く。コードやコミットには入れない
uv run taskboard serve
```

```bash
H1='Authorization: Bearer 長いランダム文字列'
H2='X-Taskboard-Author: ai:gemini-analytics'        # 必須。'ai:<名前>' 形式でないと 400
curl -H "$H1" -H "$H2" http://127.0.0.1:8765/api/v1/workspaces
curl -H "$H1" -H "$H2" http://127.0.0.1:8765/api/v1/workspaces/blog/summary
curl -H "$H1" -H "$H2" "http://127.0.0.1:8765/api/v1/workspaces/blog/items?status=candidate&limit=20"
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' --data-binary @item.json http://127.0.0.1:8765/api/v1/workspaces/blog/items   # 201
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' -d '{"status":"doing","reason":"着手"}' http://127.0.0.1:8765/api/v1/items/41/move
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' -d '{"body":"ノート"}' http://127.0.0.1:8765/api/v1/items/41/notes
curl -H "$H1" -H "$H2" -X PATCH -H 'Content-Type: application/json' -d '{"priority":"high","due":"2026-12-31"}' http://127.0.0.1:8765/api/v1/items/41
curl -H "$H1" -H "$H2" "http://127.0.0.1:8765/api/v1/events?workspace=blog&limit=50"   # 監査（MCP には無い）
```

- OpenAPI は `/docs`（127.0.0.1 からだけ見える）
- エラーは `{"detail": "..."}`: 401 トークン／400 検証・author ヘッダ・`PATCH` に `status` を含めた／403 read_only／404 不明・hidden／409 同じ状態への移動・二重完了
- Windows の Git Bash で日本語を `-d '…'` すると文字コードが壊れるので、JSON はファイルにして `--data-binary @file` で送る

## `ai_policy` — AI からどう見えるか

ワークスペースごとに設定（`/w/{slug}/settings`）。**Web UI からは常に全部見える**。MCP と REST だけがこの値を見る。

| 値 | MCP／REST から |
|:--|:--|
| `read_write` | 読める・書ける（ブログ・開発の既定） |
| `read_only` | 読めるが書き込み系は拒否（403 / ToolError「is read-only for AI」） |
| `hidden` | **存在しないものとして扱う**（一覧に出ず、ID 指定でも 404 / not found） |

「仕事」ワークスペースが既定で `hidden` なのは、仕事の項目が機密になりうるため。アプリが守れるのは「AI が自分で読みに行けない」ことだけで、人間がチャットに貼れば当然 AI に渡ります。

## データの場所とバックアップ

```
data/
  taskboard.sqlite3        # 本番 DB（WAL モード。-wal / -shm が並ぶことがある）
  demo.sqlite3             # seed --demo が作るダミー DB
  backups/<名前>-YYYYMMDD-HHMM.sqlite3   # backup コマンド／起動時 1 日 1 回（30 世代まで）
```

- `data/` と `*.sqlite3` は `.gitignore` 済み。**DB はリポジトリに入れません**
- バックアップは `sqlite3.Connection.backup()`（オンラインバックアップ API）で書くので、WAL の途中でも 1 ファイルで整合します。復旧はサーバーを止めてファイルを戻すだけ
- スキーマは `src/taskboard/migrations/000N_*.sql` を `schema_version` で前方にのみ適用します

## 取り込み（JSON が正・CSV が副）

```powershell
uv run taskboard import items.json --dry-run   # 書き込まずに結果だけ
uv run taskboard import items.json
uv run taskboard import items.csv
```

- JSON は `{"format": "taskboard-import", "version": 1, "workspaces": [...], "items": [...]}`（例: [seed/demo.json](seed/demo.json)）。無いワークスペースは作られ、**同じワークスペースに同じタイトルがあればスキップ**します（上書きしない）
- 任意拡張: 項目の `"moves": [{"to": "doing", "author": "...", "reason": "..."}]` を書くと作成後にその順で状態変更が適用され、履歴になります（`status` は作成時の状態）
- CSV はヘッダ固定 `workspace,title,status,priority,owner,due,tags,body`。`tags` は `;` 区切り、本文の改行は `\n` リテラル。リンク・ノートは CSV では扱いません

## ダミーデータ（記事・スクショ用）

```powershell
uv run taskboard seed --demo
$env:TASKBOARD_DB = "data/demo.sqlite3"; uv run taskboard serve
```

`seed/demo.json` は**すべて架空**です（ワークスペース「ブログ」「工作室」「読書」、項目 18 件、author は `human` と `ai:demo-assistant` のみ）。記事やスクショにはこの DB だけを使い、実運用の DB は写しません。`docs/screenshots/` の画像もこのダミー DB から撮ったものです。

## セキュリティ

- **127.0.0.1 にしかバインドしません**（LAN 公開は v1 のスコープ外。起動オプションもありません）
- Web UI のフォームは同一オリジンからの利用を前提にしており、CSRF トークンは付けていません（localhost・単一ユーザー前提）。他のオリジンからブラウザ経由で POST させたい用途には向きません
- Markdown（本文・ノート）は markdown-it-py を `html=False` で使い、生 HTML は必ずエスケープ、`javascript:` 等の URL は落とします。テンプレートは Jinja2 の autoescape
- REST のトークン（`TASKBOARD_API_TOKEN`）は環境変数か `.env`（.gitignore 済み）に置き、コード・コミット・README には入れない。`event.payload` に本文は入れません（変更したフィールド名だけ）
- MCP は stdio（ネットワークに出ない）。author はサーバー側の環境変数で固定

## テスト

```powershell
uv run pytest -q          # DDL・service・Web UI（TestClient）・取り込み・バックアップ・MCP（in-memory Client）・REST・2 プロセス統合
```

実ブラウザでの hx-post 部分更新／かんばん→リスト切替の確認は headless Chrome（CDP）で行い、結果を `docs/screenshots/RESULTS.json` に残しています。Claude Code から MCP 経由で実際に書き込んだログは `docs/screenshots/claude-code-mcp-log.md`。

## 依存（固定版・ライセンス）

fastapi 0.141.1 (MIT) / uvicorn 0.52.4 (BSD-3-Clause) / jinja2 3.1.6 (BSD-3-Clause) / python-multipart 0.0.32 (Apache-2.0) / markdown-it-py 4.2.0 (MIT) / mcp[cli] 2.2.0 (MIT・公式 MCP Python SDK) / htmx 2.0.10 (0BSD・`src/taskboard/static/htmx.min.js` に同梱、SHA-384 は htmx.org 掲載値と一致) / dev: pytest 9, httpx 0.28

## ライセンス

MIT（[LICENSE](LICENSE)）。DB・取り込みデータ・バックアップはリポジトリに含めません。
