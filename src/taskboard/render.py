"""Markdown 描画と表示用フィルタ。

- markdown-it-py（MIT）を html=False で使う。生 HTML は必ずエスケープされ、
  javascript:/data: などの URL は markdown-it の既定 validateLink が落とす（SPEC §2-5）
- リンクは rel="noopener noreferrer"。外部 URL は別タブ
- 時刻は DB の UTC 'YYYY-MM-DDTHH:MM:SSZ' を表示時にローカル（この PC のタイムゾーン）へ変換
"""

from __future__ import annotations

from datetime import datetime, timezone

from markdown_it import MarkdownIt
from markupsafe import Markup

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable(["table", "strikethrough"])


def _render_link_open(self, tokens, idx, options, env):  # noqa: ANN001 — markdown-it の rule 署名
    tok = tokens[idx]
    href = tok.attrGet("href") or ""
    tok.attrSet("rel", "noopener noreferrer")
    if href.startswith(("http://", "https://")):
        tok.attrSet("target", "_blank")
    return self.renderToken(tokens, idx, options, env)


_md.add_render_rule("link_open", _render_link_open)


def render_markdown(text: str) -> Markup:
    """Markdown → HTML（安全な HTML だけを返すので Markup で包む）。"""
    return Markup(_md.render(text or ""))


def local_dt(value: str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return dt.astimezone().strftime(fmt)


def local_date(value: str | None) -> str:
    return local_dt(value, "%Y-%m-%d")


def short_date(value: str | None) -> str:
    """'YYYY-MM-DD' → 'MM/DD'（カードの期限表示）。"""
    if not value or len(value) < 10:
        return value or ""
    return f"{value[5:7]}/{value[8:10]}"
