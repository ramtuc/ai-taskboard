# ai-taskboard

人と AI が**同じボードに書く**「候補・残項目」管理アプリ。ローカル専用（127.0.0.1）の Web アプリに、AI 用の書き込み口として **MCP サーバー**と **REST API** を付けたもの。

- **ページ＝ワークスペース**（例: ブログ／開発／読書）。ワークスペースごとにかんばん（6 列）またはリストで見る
- **誰が書いたかを全操作で残す**。author は `human` か `ai:<名前>`。項目・ノート・状態変更のすべてが `event` テーブルに（author・前後の値・時刻・経路）記録され、詳細画面の「履歴」に出る
- **AI からの見え方はワークスペースごとに 3 段階**（`ai_policy`）: `read_write`／`read_only`／`hidden`（AI には存在しないものとして扱う）。人間の Web UI からは常に全部見える
- 入口は 3 つ（Web UI・MCP・REST）だが、**書き込みはすべて同じ `service` 層**を通る。誰がどこから書いても同じ履歴が残る
- FastAPI + SQLite（1 ファイル）+ htmx 2.0.10（ローカル同梱・ビルド工程なし）。Python 3.12・uv 管理。`uv run` だけで起動

```
 人間 ──ブラウザ──▶ Web UI (/w/{slug})  ─┐
 Claude Code ──stdio──▶ MCP サーバー      ─┼─▶ service.py ─▶ SQLite (WAL)
 他の AI／スクリプト ──HTTP──▶ REST /api/v1 ─┘        └─ event（履歴）
```

設計仕様は [SPEC.md](SPEC.md)、変更履歴は [CHANGELOG.md](CHANGELOG.md)、技術検証の記録は [spike/ENV.md](spike/ENV.md)、記事化のための素材一覧は [docs/article-notes.md](docs/article-notes.md)。

## 動作環境

- Python 3.12（[uv](https://docs.astral.sh/uv/) が `.python-version` を見て自動で用意する）
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- 開発・検証は Windows 11（PowerShell 5.1・Git Bash）。macOS／Linux では未検証（OS 依存のコードは無い）
- MCP を使うなら [Claude Code](https://code.claude.com/docs/en/overview) など stdio の MCP ホスト

この README では clone 先を **`C:\path\to\ai-taskboard`** と書く。自分の場所に読み替えること。`uv run --directory` と `claude mcp add` にはスラッシュ区切り `C:/path/to/ai-taskboard` が使える（バックスラッシュをエスケープしなくてよい）。

## セットアップ

```powershell
cd C:\path\to\ai-taskboard
uv sync                      # 初回のみ。.venv を作り、uv.lock どおりの版を入れる
uv run taskboard init-db     # data/taskboard.sqlite3 を作り、初期ワークスペースを用意する
uv run taskboard serve       # http://127.0.0.1:8765/  停止は Ctrl+C
```

- `init-db` は省略できる（`serve` の起動時にも同じ初期化が走る）
- 初期ワークスペースは **ブログ `/w/blog`（read_write）・仕事 `/w/work`（hidden）・開発 `/w/dev`（read_write）**。名前・`ai_policy` は `/w/{slug}/settings` で変えられる
- まず触ってみるなら [ダミーデータ](#ダミーデータ架空) で起動する
- 毎回コマンドを打つのが面倒なら [常駐させる](#常駐させる起動の手間を減らす)（ダブルクリック起動・非表示起動・ログオン時自動起動）

### CLI

| コマンド | 何をするか |
|:--|:--|
| `uv run taskboard serve [--port 8765] [--db PATH] [--reload] [--no-backup]` | Web UI を起動（**127.0.0.1 固定**。`--host` はない） |
| `uv run taskboard init-db [--db PATH]` | DB の作成・マイグレーション・初期ワークスペース |
| `uv run taskboard seed --demo [--db PATH]` | ダミーデータを **`data/demo.sqlite3`**（通常 DB とは別ファイル）へ投入 |
| `uv run taskboard import FILE.json\|FILE.csv [--dry-run] [--author human]` | 取り込み（[形式](#取り込みjson-が正csv-が副)） |
| `uv run taskboard backup [--keep 30] [--dir DIR]` | `data/backups/` へオンラインバックアップ |
| `uv run taskboard mcp` | MCP サーバー（stdio）。通常は Claude Code が子プロセスとして起動する |
| `uv run taskboard --version` | 版を表示 |

`--db` を省略すると環境変数 `TASKBOARD_DB`、それも無ければ `data/taskboard.sqlite3`。ポートは `TASKBOARD_PORT` でも指定できる。

## 常駐させる（起動の手間を減らす）

`scripts/` に Windows 用の補助スクリプトがある。どれも `uv run taskboard serve` を呼ぶだけの薄い皮で、サーバー本体の設定は変えない。**タスク スケジューラへの登録は、スクリプトを実行する本人が行う**（ドライラン表示 → 確認 → 登録。スクリプトが勝手に登録することはない）。macOS／Linux では使えない。

| やりたいこと | 方法 |
|:--|:--|
| 手動で起動（開発時） | `uv run taskboard serve`。停止は Ctrl+C |
| ダブルクリックで起動 | `scripts\serve.cmd`。コンソールが開く。閉じるか Ctrl+C で停止 |
| コンソールを出さずに起動 | `scripts\serve-hidden.vbs` をダブルクリック。ログは `data\logs\serve.log` |
| ログオン時に自動起動 | `scripts\install-autostart.ps1`（解除は `uninstall-autostart.ps1`） |
| 停止 | `scripts\stop.cmd`。**ポートを LISTEN している PID だけ**を止める |
| 動作確認 | <http://127.0.0.1:8765/healthz> が `{"ok":true,"db":...,"version":...}` を返せば動いている |

### ダブルクリックで起動: `serve.cmd`

`cd` してから `uv run taskboard serve` を実行するだけ。引数はそのまま `taskboard serve` に渡る（`serve.cmd --port 8770` など）。

- ポート（既定 8765、`--port` か `TASKBOARD_PORT`）を既に何かが LISTEN していれば「already running on port 8765 - PID …」と表示して終わる（二重起動しない）
- `uv` が PATH に無ければその旨を表示して終わる
- 終わりに `pause` するので、エラーがあっても窓が消えない。Ctrl+C で止めたときは cmd の「バッチ ジョブを終了しますか (Y/N)?」に Y

### コンソールを出さずに起動: `serve-hidden.vbs`

`wscript` が `serve.cmd` を非表示ウィンドウで動かす。uvicorn の出力と起動・終了の行は **`data\logs\serve.log`** に追記される（`data/` は .gitignore 済み）。止めるのは `stop.cmd`。

- 引数（省略可）: `/uv:"C:\path\to\uv.exe"`（PATH に頼らず uv を固定。自動起動の登録スクリプトが渡す）、`/port:8765`
- 環境変数 `TASKBOARD_LOG` を先に設定しておけばログの場所を変えられる
- 起動したかどうかは <http://127.0.0.1:8765/> を開くか、`serve.log` の末尾を見る（ダイアログは出さない）
- `wscript.exe` はサーバーが生きている間は残る（サーバーの終了コードをタスク スケジューラに返すため）。タスク マネージャーに `wscript.exe` が 1 つ居るのは正常

### ログオン時に自動起動: `install-autostart.ps1` ／ `uninstall-autostart.ps1`

PowerShell 5.1 で動く。`.ps1` の実行が既定でブロックされている場合は `powershell -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1` のように起動する（または `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`）。

```powershell
cd C:\path\to\ai-taskboard
.\scripts\install-autostart.ps1 -WhatIf     # ドライラン。登録する内容を表示するだけで何もしない
.\scripts\install-autostart.ps1             # 同じ表示のあと確認プロンプト。Y で登録（-Confirm:$false で省略）

# 登録できたか・最後にどう動いたか
Get-ScheduledTask -TaskName ai-taskboard | Get-ScheduledTaskInfo
# 次のログオンを待たずに今すぐ試す
Start-ScheduledTask -TaskName ai-taskboard
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/healthz

.\scripts\uninstall-autostart.ps1           # 解除（同じく表示 → 確認）。動いているサーバーは止めない → stop.cmd
```

登録される内容（`-WhatIf` で全部表示される）:

| 項目 | 値 |
|:--|:--|
| 実行ユーザー／トリガー | 自分（`New-ScheduledTaskTrigger -AtLogOn -User`）。自分のログオン時に、自分の権限で。パスワードは保存しない（`LogonType Interactive`・`RunLevel Limited`） |
| 実行ファイル | `C:\WINDOWS\System32\wscript.exe //B //Nologo "<repo>\scripts\serve-hidden.vbs" /uv:"<uv の絶対パス>" /port:8765`。作業ディレクトリは repo のルート |
| uv | `(Get-Command uv).Source` の絶対パスを埋め込む（ログオン直後の PATH に依存しない） |
| 実行時間の上限 | `ExecutionTimeLimit PT0S`（無制限。既定の 3 日で止められない） |
| 失敗時 | 1 分後に再試行、3 回まで（`RestartCount 3` / `RestartInterval PT1M`） |
| 多重起動 | `IgnoreNew`（起動中なら新しいインスタンスを無視）。`serve.cmd` 側でもポート使用中なら起動しない |
| 電源 | バッテリー駆動でも起動し、バッテリーに切り替わっても止めない。`StartWhenAvailable` |
| 引数 | `-TaskName`（既定 `ai-taskboard`）・`-Port`（既定 8765） |

`stop.cmd` で止めたときは、`serve.cmd` が終了コード 0 で終わるようにしてある（`%TEMP%\ai-taskboard-stop-<port>.flag` の受け渡し）。タスク スケジューラは「正常終了」と見なすので、**1 分後に勝手に復活しない**。もう一度動かすなら `Start-ScheduledTask -TaskName ai-taskboard` か `serve-hidden.vbs` をダブルクリック。サーバーが自分で落ちた（終了コード ≠ 0）ときだけ再試行が働く。

### 停止: `stop.cmd`

`netstat -ano` でポート（既定 8765、`--port N` か `TASKBOARD_PORT`）を **LISTENING** している PID を 1 つ探し、その PID だけを `taskkill /PID <pid> /F` で止める。イメージ名（`python.exe`）ではまとめて殺さないので、他の Python は巻き込まない。uvicorn のシャットダウン処理は走らないが、DB は SQLite の WAL モードなので途中で切れても壊れない前提（[SPEC §6-4](SPEC.md)）。親の `uv`／`cmd`／`wscript` はサーバーが消えると自分で終わる。

### ポートが競合したとき

- `serve.cmd` が「already running on port 8765 - PID N」と言う → 既にこのアプリが動いているなら <http://127.0.0.1:8765/> を開けばよい。別のアプリなら `tasklist /fi "PID eq N"` で正体を確認する
- 別のポートで動かす: `serve.cmd --port 8770`、または環境変数 `TASKBOARD_PORT=8770`。自動起動は `install-autostart.ps1 -Port 8770`（`stop.cmd --port 8770` で止める）
- MCP は stdio（ポートを使わない）なのでポートを変えても Claude Code 側の設定は変わらない。REST と Web UI の URL だけ変わる

### ログの場所

| 起動方法 | 出力先 |
|:--|:--|
| `uv run taskboard serve`／`serve.cmd` | そのコンソール |
| `serve-hidden.vbs`／ログオン時自動起動 | `data\logs\serve.log`（追記。ローテーションはしない。大きくなったらサーバーを止めてから消す） |

手で起動するときにファイルへ落とすなら、cmd から `uv run taskboard serve >> data\logs\serve.log 2>&1`。PowerShell 5.1 では stderr のリダイレクトが ErrorRecord に包まれるので `cmd /c "uv run taskboard serve >> data\logs\serve.log 2>&1"` の形にする。`serve.cmd` は環境変数 `TASKBOARD_LOG` にファイル名があれば同じことをする（フォルダは作る）。


## 画面

| URL | 画面 |
|:--|:--|
| `/` | ワークスペース一覧（状態別の件数・AI からの見え方バッジ） |
| `/w/{slug}` | かんばん（候補／着手／待ち（人）／待ち（AI）／完了／保留）。`?view=list` でリスト、`?tag=`・`?owner=`・`?q=`・`?status=`（リストのみ）で絞り込み |
| `/w/{slug}/items/{id}` | 項目の詳細（Markdown 本文・ノート・履歴・タグ・リンク）。編集・状態変更・完了・ノート追加は htmx で部分更新 |
| `/workspaces/new`・`/w/{slug}/settings` | ワークスペースの追加・設定（名前・説明・`ai_policy`・アーカイブ） |
| `/docs` | REST の OpenAPI UI |
| `/healthz` | 稼働確認 JSON |

- Web UI からの書き込みは常に author = `human`
- `ai:*` が作った項目・ノートは青いバッジ、`human` は灰色のバッジ
- 状態は「状態を変更」のセレクト（かんばん・リスト・詳細）からだけ変えられる。編集フォームでは変えられない（履歴を必ず残すため）
- 削除機能はない。「保留」列とワークスペースのアーカイブで代用する

スクショ（すべてダミー DB）: [docs/screenshots/](docs/screenshots/)

## MCP サーバー（Claude Code から書く）

MCP サーバーは Web サーバーとは**別プロセス**で、同じ SQLite ファイルを直接開く（WAL）。Web が止まっていても動き、DB が無ければ作る。

| 環境変数 | 意味 |
|:--|:--|
| `TASKBOARD_AUTHOR` | **書き込みの author（`ai:<名前>`）**。ここで固定され、ツール引数では変えられない（なりすまし防止）。未設定だと読み取り専用になる。AI ごとに違う名前を付けると、履歴で「どの AI が書いたか」が分かる |
| `TASKBOARD_DB` | SQLite ファイル（省略時 `data/taskboard.sqlite3`。`uv run --directory` で起動すると相対パスの基準はプロジェクト）。**絶対パス推奨** |
| `TASKBOARD_BASE_URL` | 戻り値の `url` の土台（省略時 `http://127.0.0.1:8765`）。AI が「ここを見て」と人間に渡す URL になる |
| `PYTHONUTF8` | `1` を推奨（Windows のコンソール文字コード対策。stdio プロトコル自体は SDK が UTF-8 固定なので必須ではない） |

### Claude Code への登録

```powershell
# local scope: このフォルダで claude を起動したときだけ見える（~/.claude.json に入る）
claude mcp add taskboard -e TASKBOARD_AUTHOR=ai:claude-code -e TASKBOARD_DB=C:/path/to/ai-taskboard/data/taskboard.sqlite3 -e PYTHONUTF8=1 -- uv run --directory C:/path/to/ai-taskboard taskboard mcp

# どのフォルダからでも使うなら user scope
claude mcp add -s user taskboard -e TASKBOARD_AUTHOR=ai:claude-code -e TASKBOARD_DB=C:/path/to/ai-taskboard/data/taskboard.sqlite3 -e PYTHONUTF8=1 -- uv run --directory C:/path/to/ai-taskboard taskboard mcp

claude mcp list            # taskboard: uv run --directory ... taskboard mcp - √ Connected
claude mcp get taskboard   # 登録内容（Environment に上の 3 つ）
claude mcp remove taskboard -s local   # 外すとき（user scope なら -s user）
```

- `--` より後ろがサーバーの起動コマンド。`-e` と `-s` は `--` より前に置く
- Claude Code 内では `/mcp` で接続状態が見え、ツールは `mcp__taskboard__add_item` のような名前で呼ばれる
- 記事・デモ用は `TASKBOARD_DB=.../data/demo.sqlite3`・`TASKBOARD_AUTHOR=ai:demo-assistant` で別の名前（例 `taskboard-demo`）で登録し、実運用の DB と混ぜない
- headless で試すなら: `claude -p "taskboard の list_workspaces を呼んで結果をそのまま返して" --allowedTools mcp__taskboard__list_workspaces`

### 権限設定の例（Claude Code）

Claude Code は MCP ツールの呼び出しごとに許可を求める。読み取り系だけ自動許可し、書き込み系は毎回確認する例（`.claude/settings.json` か `~/.claude/settings.json`）:

```json
{
  "permissions": {
    "allow": [
      "mcp__taskboard__list_workspaces",
      "mcp__taskboard__get_workspace_summary",
      "mcp__taskboard__list_items",
      "mcp__taskboard__get_item"
    ]
  }
}
```

書き込み系も含めて全部許可するなら `"mcp__taskboard"`（サーバー丸ごと）か `"mcp__taskboard__*"`。書き込みを禁止するなら `"deny": ["mcp__taskboard__add_item", "mcp__taskboard__update_item", "mcp__taskboard__move_item", "mcp__taskboard__add_note", "mcp__taskboard__complete_item"]`。書式は [Claude Code の permissions](https://code.claude.com/docs/en/permissions#mcp) を参照。

### ツール（SPEC §4-2）

| ツール | 何をするか |
|:--|:--|
| `list_workspaces()` | AI から見えるワークスペース（hidden は出ない）と状態別件数 |
| `get_workspace_summary(workspace)` | 件数・期限切れ・`waiting_ai` の項目・直近 20 イベント。**セッション開始時にまず呼ぶ** |
| `list_items(workspace, status?, tag?, owner?, query?, limit=50, offset=0)` | 一覧（本文なし）・`next_offset` |
| `get_item(item_id)` | 本文・ノート・履歴 |
| `add_item(workspace, title, body?, priority?, owner?, due?, tags?, links?)` | 候補を追加 |
| `update_item(item_id, …)` | 属性の変更（`status` は受けない） |
| `move_item(item_id, status, reason?)` | 列の移動（同じ状態へはエラー） |
| `add_note(item_id, body)` | ノート追記 |
| `complete_item(item_id, summary?)` | 完了（summary は完了ノートに） |

戻り値は Pydantic モデル（SDK が `output_schema` と `structured_content` を付ける）。失敗は `ToolError` としてモデルに文言が届く（「workspace 'x' not found」「is read-only for AI」「already 'done'」など）ので、AI が自分で言い直せる。

### MCP Inspector で手で叩く

Inspector CLI は親シェルの環境変数を子プロセスに渡さないので、[docs/inspector.example.json](docs/inspector.example.json) のパスを自分の環境に書き換えて `--config` で渡す:

```bash
npx --yes @modelcontextprotocol/inspector@2.6.0 --cli --config docs/inspector.example.json --server taskboard-demo --method tools/list
npx --yes @modelcontextprotocol/inspector@2.6.0 --cli --config docs/inspector.example.json --server taskboard-demo --method tools/call --tool-name list_workspaces
```

PowerShell では `npx` が `npx.ps1` に解決されて裸の `--` を食うので、Git Bash か `npx.cmd` で実行する（[spike/ENV.md §5](spike/ENV.md)）。

## REST API（`/api/v1`）

他の AI やスクリプト用。**`TASKBOARD_API_TOKEN` を設定して起動したときだけ有効**（未設定なら `/api/v1/*` は 404）。

```powershell
$env:TASKBOARD_API_TOKEN = "長いランダム文字列"   # トークンはシェルの環境変数か .env（.gitignore 済み）に置く。コード・コミット・README には書かない
uv run taskboard serve
```

```bash
H1='Authorization: Bearer 長いランダム文字列'
H2='X-Taskboard-Author: ai:gemini-analytics'        # 必須。'ai:<名前>' 形式でないと 400
curl -H "$H1" -H "$H2" http://127.0.0.1:8765/api/v1/workspaces
curl -H "$H1" -H "$H2" http://127.0.0.1:8765/api/v1/workspaces/blog/summary
curl -H "$H1" -H "$H2" "http://127.0.0.1:8765/api/v1/workspaces/blog/items?status=candidate&limit=20"
curl -H "$H1" -H "$H2" http://127.0.0.1:8765/api/v1/items/41
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' --data-binary @item.json http://127.0.0.1:8765/api/v1/workspaces/blog/items   # 201
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' -d '{"status":"doing","reason":"着手"}' http://127.0.0.1:8765/api/v1/items/41/move
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' -d '{"body":"ノート"}' http://127.0.0.1:8765/api/v1/items/41/notes
curl -H "$H1" -H "$H2" -X PATCH -H 'Content-Type: application/json' -d '{"priority":"high","due":"2026-12-31"}' http://127.0.0.1:8765/api/v1/items/41
curl -H "$H1" -H "$H2" -H 'Content-Type: application/json' -d '{"summary":"公開した"}' http://127.0.0.1:8765/api/v1/items/41/complete
curl -H "$H1" -H "$H2" "http://127.0.0.1:8765/api/v1/events?workspace=blog&limit=50"   # 監査（MCP には無い）
```

- OpenAPI は `/docs`
- エラーは `{"detail": "..."}`: 401 トークン／400 検証・author ヘッダ・`PATCH` に `status` を含めた／403 read_only／404 不明・hidden・REST 無効／409 同じ状態への移動・二重完了
- Windows の Git Bash で日本語を `-d '…'` すると文字コードが壊れるので、JSON はファイルにして `--data-binary @file` で送る

## `ai_policy` — AI からどう見えるか

ワークスペースごとに設定（`/w/{slug}/settings`）。**Web UI からは常に全部見える**。MCP と REST だけがこの値を見る。

| 値 | MCP／REST から |
|:--|:--|
| `read_write` | 読める・書ける（ブログ・開発の既定） |
| `read_only` | 読めるが書き込み系は拒否（403 / ToolError「is read-only for AI」） |
| `hidden` | **存在しないものとして扱う**（一覧に出ず、ID 指定でも 404 / not found） |

「仕事」ワークスペースが既定で `hidden` なのは、仕事の項目が機密になりうるため。アプリが守れるのは「AI が自分で読みに行けない」ことだけで、人間がチャットに貼れば当然 AI に渡る。

## 取り込み（JSON が正・CSV が副）

```powershell
uv run taskboard import items.json --dry-run   # 書き込まずに結果だけ
uv run taskboard import items.json
uv run taskboard import items.csv --author human
```

JSON の形式（完全な例は [seed/demo.json](seed/demo.json)）:

```json
{
  "format": "taskboard-import",
  "version": 1,
  "workspaces": [
    {"slug": "blog", "name": "ブログ", "description": "記事の候補", "ai_policy": "read_write"}
  ],
  "items": [
    {
      "workspace": "blog",
      "title": "555 タイマーの記事を書く",
      "body": "Markdown 本文（省略可）",
      "status": "candidate",
      "priority": "high",
      "owner": "human",
      "due": "2026-09-30",
      "tags": ["ic-lab", "ne555"],
      "links": [{"kind": "url", "target": "https://example.com/", "label": "参考"}],
      "created_by": "human",
      "notes": [{"author": "human", "body": "ノート本文"}],
      "moves": [{"to": "doing", "author": "human", "reason": "着手"}]
    }
  ]
}
```

- `status`: `candidate` / `doing` / `waiting_human` / `waiting_ai` / `done` / `hold`。`priority`: `low` / `normal` / `high` / `urgent`。`owner`・`created_by`・ノートの `author`: `human` か `ai:<名前>`。`links[].kind`: `article`（サイト内パス）/ `task`（外部タスク管理の ID。例: チケット番号・リンクにならない）/ `url`
- 無いワークスペースは作られる。**同じワークスペースに同じタイトルがあればスキップ**する（上書きしない）
- `moves` は任意。作成後にその順で状態変更が適用され、履歴になる（`status` は作成時の状態）
- `created_by` が無い項目は `--author`（既定 `human`）。取り込みの履歴は `source = import`
- CSV はヘッダ固定 `workspace,title,status,priority,owner,due,tags,body`。`tags` は `;` 区切り、本文の改行は `\n` リテラル。リンク・ノート・`moves` は CSV では扱わない

## データの場所とバックアップ

```
data/
  taskboard.sqlite3        # 本番 DB（WAL モード。-wal / -shm が並ぶことがある）
  demo.sqlite3             # seed --demo が作るダミー DB
  backups/<名前>-YYYYMMDD-HHMM.sqlite3   # backup コマンド／起動時 1 日 1 回（30 世代まで）
```

- `data/` と `*.sqlite3` は `.gitignore` 済み。**DB・取り込みデータ・バックアップはリポジトリに入れない**
- 手動: `uv run taskboard backup`。自動: `serve` が起動時と 1 時間ごとに「直近のバックアップが 24 時間より古ければ」1 回書く（`--no-backup` で止められる）
- バックアップは `sqlite3.Connection.backup()`（オンラインバックアップ API）で書くので、WAL の途中でも 1 ファイルで整合する。復旧はサーバーを止めてファイルを戻すだけ
- スキーマは `src/taskboard/migrations/000N_*.sql` を `schema_version` で前方にのみ適用する

## ダミーデータ（架空）

```powershell
uv run taskboard seed --demo                        # → data/demo.sqlite3
$env:TASKBOARD_DB = "data/demo.sqlite3"; uv run taskboard serve
```

`seed/demo.json` の内容は**すべて架空**である。ワークスペース「ブログ」「工作室」「読書（read_only）」、項目 18 件、ノート 12 件、状態変更の履歴 10 件、author は `human` と `ai:demo-assistant` のみ。実在の人物・案件・タスク ID・記事 URL は含まない。`docs/screenshots/` の画像と `docs/screenshots/claude-code-mcp-log.md` もこのダミー DB で撮ったもの。記事・スクショにはこの DB だけを使う。

## セキュリティ

- **127.0.0.1 にしかバインドしない**（LAN 公開はスコープ外。起動オプションもない）
- Web UI のフォームは同一オリジンからの利用を前提にしており、CSRF トークンは付けていない（localhost・単一ユーザー前提）。他のオリジンからブラウザ経由で POST させたい用途には向かない
- Markdown（本文・ノート）は markdown-it-py を `html=False` で使い、生 HTML は必ずエスケープ、`javascript:` 等の URL は落とす。テンプレートは Jinja2 の autoescape
- REST のトークン（`TASKBOARD_API_TOKEN`）は環境変数か `.env`（.gitignore 済み）に置く。`event.payload` に本文は入れない（変更したフィールド名だけ）
- MCP は stdio（ネットワークに出ない）。author はサーバー側の環境変数で固定

## テスト

```powershell
uv run pytest -q          # 46 passed: DDL・service・Web UI（TestClient）・取り込み・バックアップ・MCP（in-memory Client）・REST・2 プロセス統合
```

実ブラウザでの hx-post 部分更新／かんばん→リスト切替の確認は headless Chrome（CDP）で行い、結果を `docs/screenshots/RESULTS.json`・`RESULTS-v0.3.json` に残している。Claude Code から MCP 経由で実際に書き込んだログは `docs/screenshots/claude-code-mcp-log.md`。

## 既知の制限

- **削除機能はない**（履歴を残す方針）。項目は「保留」列へ、ワークスペースはアーカイブで隠す。物理削除したければ SQLite を直接触る
- **ローカル専用**。127.0.0.1 固定・ログイン無し・CSRF 対策無し。LAN や他 PC から使う設計になっていない
- **時刻表示はこの PC のローカルタイムゾーン**（DB は UTC）。Windows の Python には tz データベースが無く `ZoneInfo("Asia/Tokyo")` が失敗するため、`datetime.astimezone()` の OS 設定に任せている。サーバーの TZ とブラウザの TZ が違うとずれる
- 単一ユーザー前提（人間は 1 人・author は `human` 固定）。人間を区別したい用途には向かない
- ドラッグ＆ドロップでの列移動はない（`<select>` で移動）
- MCP は stdio のみ（Streamable HTTP での常時公開はしない）。ホストが子プロセスとして起動する運用が前提
- macOS／Linux は未検証
- `scripts/` の補助スクリプト（ダブルクリック起動・非表示起動・停止・ログオン時自動起動）は Windows 専用（cmd／WSH／タスク スケジューラ）

## ライセンス

MIT（[LICENSE](LICENSE)）。DB・取り込みデータ・バックアップはリポジトリに含めない。

### 依存ライブラリ（固定版）

| ライブラリ | 版 | ライセンス | 用途 |
|:--|:--|:--|:--|
| [FastAPI](https://fastapi.tiangolo.com/) | 0.141.1 | MIT | Web／REST／OpenAPI |
| [Starlette](https://www.starlette.io/) | 1.6.0 | BSD-3-Clause | FastAPI の土台（uv が解決） |
| [uvicorn](https://uvicorn.dev/) | 0.52.4 | BSD-3-Clause | ASGI サーバー |
| [Jinja2](https://jinja.palletsprojects.com/) | 3.1.6 | BSD-3-Clause | テンプレート |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.32 | Apache-2.0 | フォーム受信 |
| [markdown-it-py](https://markdown-it-py.readthedocs.io/) | 4.2.0 | MIT | Markdown 描画 |
| [mcp](https://github.com/modelcontextprotocol/python-sdk)（`mcp[cli]`・公式 MCP Python SDK） | 2.2.0 | MIT | MCP サーバー |
| [pydantic](https://docs.pydantic.dev/) | 2.13.5 | MIT | 入出力モデル（FastAPI／mcp 経由） |
| [htmx](https://htmx.org/) | 2.0.10 | 0BSD | `src/taskboard/static/htmx.min.js` に同梱。SHA-384 は htmx.org 掲載の integrity 値と一致 |
| dev: [pytest](https://pytest.org/) / [httpx](https://www.python-httpx.org/) | 9.1.1 / 0.28.1 | MIT / BSD-3-Clause | テスト |

版とライセンスは PyPI のメタデータ（`License-Expression` または classifier）と各プロジェクトの LICENSE による（2026-09-12 時点）。推移的依存の全一覧は `uv.lock`。
