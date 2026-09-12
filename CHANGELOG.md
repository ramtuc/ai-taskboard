# Changelog

このプロジェクトの変更履歴。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、版番号は [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [Unreleased]

### Added
- `scripts/`（Windows 専用）: 起動の手間を減らす補助スクリプト。`serve.cmd`（ダブルクリック起動。ポート使用中なら PID を表示して終わる）・`serve-hidden.vbs`（コンソールを出さずに起動。ログは `data/logs/serve.log`）・`stop.cmd`（ポートを LISTEN している PID だけを `taskkill /PID`）・`install-autostart.ps1`／`uninstall-autostart.ps1`（ログオン時自動起動のタスク スケジューラ登録／解除。ドライラン表示 → 確認 → 登録。登録は利用者が実行）
- README「常駐させる」節、SPEC §6-4 に v1.1 の 1 行
- `.gitattributes`: `*.cmd` / `*.vbs` / `*.ps1` を `eol=crlf` に固定

## [1.0.0] - 2026-09-12

公開版。0.3.0 から機能の追加・変更はない。

### Added
- `CHANGELOG.md`（この文書）
- `docs/article-notes.md`: 記事化のための見せ場・該当コード・スクショの対応表（スクショはすべてダミー DB）
- README: 概要・セットアップ・MCP 登録（権限設定の例）・REST・取り込み JSON・バックアップ・依存ライブラリのライセンス一覧・既知の制限

### Changed
- 版番号を 1.0.0 に（`pyproject.toml`・`taskboard --version`・画面フッタ・`/healthz`）
- README・`docs/inspector.example.json`・ソースの docstring から作者環境の絶対パスを外し、`C:\path\to\ai-taskboard` の書き方に統一

## [0.3.0] - 2026-09-12

AI の書き込み口。

### Added
- **MCP サーバー**（`uv run taskboard mcp`・stdio・公式 MCP Python SDK 2.2.0 の `MCPServer`）: `list_workspaces` / `get_workspace_summary` / `list_items` / `get_item` / `add_item` / `update_item` / `move_item` / `add_note` / `complete_item` の 9 ツール。戻り値は Pydantic モデル（`output_schema` / `structured_content` 付き）、失敗は `ToolError` でモデルに文言が届く
- 書き込みの author はサーバー側の環境変数 `TASKBOARD_AUTHOR`（`ai:<名前>`）で固定。ツール引数では変えられない。未設定なら読み取りのみ
- **REST API `/api/v1`**（`Authorization: Bearer` ＋ `X-Taskboard-Author` 必須）: ワークスペース一覧・サマリ・項目の一覧／詳細／追加／更新／移動／ノート／完了・監査用 `GET /api/v1/events`。`TASKBOARD_API_TOKEN` 未設定のときは `/api/v1/*` 全体が 404
- `ai_policy` の強制（MCP・REST）: `hidden` は存在しない扱い（一覧に出ず ID 指定も 404 / not found）、`read_only` は書き込み系を拒否（403 / ToolError）
- MCP サーバーは初回接続時に DB を作り、空なら初期ワークスペースも作る（Web を一度も起動していなくても動く）
- `docs/inspector.example.json`: MCP Inspector CLI に環境変数を渡す設定例
- テスト 14 件追加（MCP 7・REST 6・Web と MCP の 2 プロセス同時書き込み 1）→ 46 passed
- `docs/screenshots/10-*.png`・`11-*.png`・`claude-code-mcp-log.md`: Claude Code から MCP 経由で demo DB に書いた記録

### Changed
- 検証エラーの HTTP 状態を 400 に統一（FastAPI 既定の 422 ではなく）。`read_only` 違反は `Forbidden`（403）

## [0.2.0] - 2026-09-12

Web アプリ本体。

### Added
- ワークスペース（`/w/{slug}`・作成・設定・`ai_policy`・アーカイブ）。初回起動時に「ブログ `blog`」「仕事 `work`（hidden）」「開発 `dev`」を作る
- かんばん 6 列（候補／着手／待ち（人）／待ち（AI）／完了／保留）とリスト表示（`?view=list`・状態／タグ／担当／全文の絞り込み・並び替え・ページング）
- 項目の詳細（Markdown 本文・ノート・履歴・タグ・リンク）と編集。状態変更は「状態を変更」のセレクトからだけ（履歴を必ず残す）
- htmx 2.0.10（ローカル同梱）による部分更新: クイック追加・状態変更・ノート追加・編集フォームの差し込み。JS 無しでも通常のフォーム POST（303）で動く
- `event` テーブルに全操作の履歴（author・種別・前後の値・時刻・source）。`ai:*` は青、`human` は灰のバッジ
- Markdown は markdown-it-py（`html=False`）で描画。生 HTML はエスケープ、`javascript:` 等の URL は落とす
- 取り込み `uv run taskboard import FILE.json|FILE.csv [--dry-run]`（JSON が正・CSV が副・同じワークスペースの同じタイトルはスキップ・任意の `moves` で履歴を再現）
- バックアップ `uv run taskboard backup`（`sqlite3.Connection.backup()`・30 世代）と、起動時＋1 時間ごとの日次判定
- ダミーデータ `seed/demo.json`（架空・`uv run taskboard seed --demo` で `data/demo.sqlite3` へ）
- CLI `taskboard serve / init-db / seed / import / backup`（`--host` は無く 127.0.0.1 固定）
- テスト 32 件（DDL・service・Web・取り込み）、headless Chrome での実クリック検証 13 項目（`docs/screenshots/RESULTS.json`）

## [0.1.0] - 2026-09-12

設計と技術検証。

### Added
- `SPEC.md`: 画面・URL・データモデル（SQLite DDL）・MCP ツール定義・REST・技術選定・セキュリティ・取り込み形式・記事プラン・見送った案
- `spike/`: MCP サーバー（stdio）と FastAPI＋htmx の最小構成で技術検証。結果と詰まった点 9 件は `spike/ENV.md`
- `LICENSE`（MIT）
