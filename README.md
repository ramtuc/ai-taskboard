# ai-taskboard

人と AI が一緒に書く「候補・残項目」ボード。ワークスペース（＝ページ）ごとにかんばん／リストで管理し、**誰が書いたか（human / ai:名前）を全操作で残す**ローカル専用の Web アプリです。

- FastAPI + SQLite（1 ファイル）+ htmx 2.0.10（ローカル同梱・ビルド工程なし）
- Python 3.12（uv 管理）／`uv run` だけで起動
- v0.2 時点: Web UI（ワークスペース・かんばん 6 列・リスト表示・詳細・Markdown 本文・ノート・履歴・タグ・リンク・フィルタ）・取り込み・バックアップ
- v0.3（予定）: MCP サーバー（Claude Code から読み書き）と REST API

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
- 秘密情報（トークン等）は v0.2 では扱いません。`event.payload` に本文は入れません（変更したフィールド名だけ）

## テスト

```powershell
uv run pytest -q          # DDL・service・Web UI（TestClient）・取り込み・バックアップ
```

実ブラウザでの hx-post 部分更新／かんばん→リスト切替の確認は headless Chrome（CDP）で行い、結果を `docs/screenshots/RESULTS.json` に残しています。

## 依存（固定版・ライセンス）

fastapi 0.141.1 (MIT) / uvicorn 0.52.4 (BSD-3-Clause) / jinja2 3.1.6 (BSD-3-Clause) / python-multipart 0.0.32 (Apache-2.0) / markdown-it-py 4.2.0 (MIT) / htmx 2.0.10 (0BSD・`src/taskboard/static/htmx.min.js` に同梱、SHA-384 は htmx.org 掲載値と一致) / dev: pytest 9, httpx 0.28

## ライセンス

MIT（[LICENSE](LICENSE)）。DB・取り込みデータ・バックアップはリポジトリに含めません。
