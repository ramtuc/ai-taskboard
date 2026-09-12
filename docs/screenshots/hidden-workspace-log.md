# hidden のワークスペースは AI から「存在しない」— Inspector CLI 実ログ（demo DB）

2026-09-12 18:59〜19:00 JST / 実装担当 / すべて **`data/demo.sqlite3`（架空データ）** に対して実施。本番 DB には触っていない。
Web UI は `TASKBOARD_DB=data/demo.sqlite3 uv run taskboard serve --port 8766`（8765 は別のサーバーが使用中だったため）、MCP 側は `docs/inspector.example.json` のパスを実環境に置き換えた設定ファイルを `--config` で渡した（`TASKBOARD_DB` を env で demo DB に固定）。テキストのみ・画像なし。

## 0. 手順の流れ

| 時刻 (JST) | 操作 | 結果 |
|:--|:--|:--|
| 18:59:09 | UI の設定フォーム `POST /w/reading/settings` で 読書 を `read_only` → **`hidden`** | HTTP 200（履歴に `workspace.updated` #55・source=ui） |
| 18:59:18 | Inspector CLI `list_workspaces` | **reading が消える**（blog / workshop の 2 件だけ） |
| 18:59:34 | Inspector CLI `get_workspace_summary("reading")` | **ToolError `workspace 'reading' not found`**（isError: true） |
| 18:59:47 | Inspector CLI `add_item(workspace="reading")` | 同じく `not found`（read-only 時の「is read-only for AI」ではない＝存在自体を明かさない） |
| 19:00:01 | 設定フォームで 読書 を **`read_only` に戻す** | HTTP 200（`workspace.updated` #56）。`list_workspaces` に reading が再び出る（3 件） |

## 1. 読書を hidden に切り替える（UI 側）

`/w/reading/settings` の select「AI: 非公開」を選んで保存するのと同じリクエスト（フォームの POST を直接送った）。

```
before: slug=reading name='読書' description='積読と読み返したい本' ai_policy=read_only
POST /w/reading/settings ai_policy=hidden -> HTTP 200; after: ai_policy=hidden
2026-09-12 18:59:09 +0900
```

## 2. `list_workspaces` — reading が返ってこない

```bash
$ npx --yes @modelcontextprotocol/inspector@2.6.0 --cli --config inspector.demo.json --server taskboard-demo \
    --method tools/call --tool-name list_workspaces --format json
# 2026-09-12 18:59:18 +0900
```

`structuredContent` 部分（`content[0].text` は同じ内容の整形 JSON）:

```json
{
  "workspaces": [
    {
      "slug": "blog",
      "name": "ブログ",
      "description": "記事の候補と書きかけ",
      "ai_policy": "read_write",
      "counts": {"candidate": 1, "doing": 4, "waiting_human": 1, "waiting_ai": 2, "done": 1, "hold": 1},
      "url": "http://127.0.0.1:8766/w/blog"
    },
    {
      "slug": "workshop",
      "name": "工作室",
      "description": "作りたいもの・直したいもの",
      "ai_policy": "read_write",
      "counts": {"candidate": 2, "doing": 1, "waiting_human": 1, "waiting_ai": 0, "done": 1, "hold": 1},
      "url": "http://127.0.0.1:8766/w/workshop"
    }
  ]
}
```

（`"isError": false`。hidden の reading は `ai_policy: "hidden"` として並ぶのではなく、**配列から無くなる**）

## 3. `get_workspace_summary("reading")` — ToolError（not found）

```bash
$ npx --yes @modelcontextprotocol/inspector@2.6.0 --cli --config inspector.demo.json --server taskboard-demo \
    --method tools/call --tool-name get_workspace_summary --tool-args-json '{"workspace":"reading"}' --format json
# 2026-09-12 18:59:34 +0900
```

stderr（サーバー側 FastMCP のログ）:

```
[09/12/26 18:59:38] INFO     Tool 'get_workspace_summary' failed: "Error executing tool get_workspace_summary: workspace 'reading' not found"   server.py:444
```

stdout:

```json
{"result":{"content":[{"type":"text","text":"Error executing tool get_workspace_summary: workspace 'reading' not found"}],"isError":true}}
{"error":{"code":"tool_is_error","message":"Tool 'get_workspace_summary' returned isError:true."}}
```

Inspector CLI の終了コードは 5（isError を非 0 終了で知らせる）。

### 3-1. おまけ: hidden 中に `add_item(workspace="reading")` を投げる

```bash
$ … --method tools/call --tool-name add_item --tool-args-json '{"workspace":"reading","title":"Inspector から（hidden 中）"}' --format json
# 2026-09-12 18:59:47 +0900
{"result":{"content":[{"type":"text","text":"Error executing tool add_item: workspace 'reading' not found"}],"isError":true}}
```

`read_only` のときは `workspace 'reading' is read-only for AI`（claude-code-mcp-log.md §3）だったのが、hidden では読み取り・書き込みとも一律 `not found`。「読めない」ではなく「無い」に倒している（SPEC §4-2）。

## 4. `read_only` に戻す → 一覧に復帰

```
before: slug=reading name='読書' description='積読と読み返したい本' ai_policy=hidden
POST /w/reading/settings ai_policy=read_only -> HTTP 200; after: ai_policy=read_only
2026-09-12 19:00:01 +0900
```

直後の `list_workspaces`（抜粋）— 3 件目に reading が戻る:

```json
{"slug":"reading","name":"読書","description":"積読と読み返したい本","ai_policy":"read_only",
 "counts":{"candidate":2,"doing":1,"waiting_human":0,"waiting_ai":1,"done":1,"hold":1},
 "url":"http://127.0.0.1:8766/w/reading"}
```

demo DB の最終状態: blog=read_write / workshop=read_write / reading=read_only（元どおり）。切り替えの痕跡として `event` に `workspace.updated` が 2 行（#55, #56・source=ui・author=human）残る。

## 5. 使った設定ファイル

`docs/inspector.example.json` の `C:/path/to/ai-taskboard` を実パスに、`TASKBOARD_BASE_URL` を `http://127.0.0.1:8766` に置き換えたコピー（リポジトリ外に置いた）。Inspector CLI は親シェルの環境変数を子プロセスに渡さないので、`TASKBOARD_DB` は必ずこの `env` で指定する。
