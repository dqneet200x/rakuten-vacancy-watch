"""メール文面のテンプレート描画。

文面は templates/ 配下のファイルを書き換えるだけで自由に変更できる。
テンプレートに文法ミスがあっても監視自体は止めず、内蔵の予備文面で通知する。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateError, select_autoescape

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9), "JST")

SUBJECT_TEMPLATE = "subject.txt"
BODY_TEXT_TEMPLATE = "body.txt"
BODY_HTML_TEMPLATE = "body.html"
ERROR_SUBJECT_TEMPLATE = "error_subject.txt"
ERROR_BODY_TEMPLATE = "error_body.txt"

# テンプレートが壊れていても通知だけは届くようにするための予備文面。
FALLBACKS: dict[str, str] = {
    SUBJECT_TEMPLATE: (
        "{{ direction_mark }}【楽天トラベル】{{ area_name }} "
        "{{ stay_label }} の空室 {{ prev_count }}件 → {{ curr_count }}件"
    ),
    BODY_TEXT_TEMPLATE: (
        "{{ area_name }}（{{ checkin }}〜{{ checkout }}）の空室件数が\n"
        "{{ prev_count }}件 → {{ curr_count }}件（{{ diff_text }}）に変化しました。\n\n"
        "{{ search_url }}\n\n"
        "※本メールは自動送信です（{{ now.strftime('%Y-%m-%d %H:%M') }}）\n"
    ),
    BODY_HTML_TEMPLATE: (
        "<p>{{ area_name }}（{{ checkin }}〜{{ checkout }}）の空室件数が"
        "<b>{{ prev_count }}件 → {{ curr_count }}件</b>に変化しました。</p>"
        '<p><a href="{{ search_url }}">楽天トラベルで見る</a></p>'
        "<p>※本メールは自動送信です（{{ now.strftime('%Y-%m-%d %H:%M') }}）</p>"
    ),
    ERROR_SUBJECT_TEMPLATE: "【楽天トラベル監視】取得エラーが続いています（{{ area_name }}）",
    ERROR_BODY_TEMPLATE: (
        "{{ area_name }} の空室情報を {{ consecutive_failures }} 回連続で取得できていません。\n\n"
        "直近のエラー内容:\n{{ error_message }}\n\n"
        "※本メールは自動送信です（{{ now.strftime('%Y-%m-%d %H:%M') }}）\n"
    ),
}


def now_jst() -> datetime:
    return datetime.now(JST)


class TemplateRenderer:
    """templates/ ディレクトリを読むレンダラ。"""

    def __init__(self, directory: str | Path = "templates"):
        self.directory = Path(directory)
        self.env = Environment(
            # utf-8-sig にしておくと、メモ帳で編集して BOM が付いても壊れない
            loader=FileSystemLoader(str(self.directory), encoding="utf-8-sig"),
            autoescape=select_autoescape(enabled_extensions=("html",), default=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        """テンプレートを描画する。失敗したら予備文面に切り替える。"""
        try:
            return self.env.get_template(template_name).render(**context).strip()
        except TemplateError as exc:
            logger.error(
                "テンプレート %s の描画に失敗しました（%s）。既定の文面で送信します。",
                template_name,
                exc,
            )
        except OSError as exc:
            logger.error(
                "テンプレート %s を読めませんでした（%s）。既定の文面で送信します。",
                template_name,
                exc,
            )

        fallback = FALLBACKS.get(template_name, "")
        try:
            return self.env.from_string(fallback).render(**context).strip()
        except TemplateError:
            return fallback

    def render_subject(self, context: dict[str, Any]) -> str:
        # 件名に改行が混ざるとメールヘッダが壊れるため1行に潰す
        subject = self.render(SUBJECT_TEMPLATE, context)
        return " ".join(subject.splitlines()).strip()

    def render_bodies(self, context: dict[str, Any], send_html: bool) -> tuple[str, str | None]:
        text = self.render(BODY_TEXT_TEMPLATE, context)
        html = self.render(BODY_HTML_TEMPLATE, context) if send_html else None
        return text, html

    def render_error(self, context: dict[str, Any]) -> tuple[str, str]:
        subject = " ".join(self.render(ERROR_SUBJECT_TEMPLATE, context).splitlines()).strip()
        body = self.render(ERROR_BODY_TEMPLATE, context)
        return subject, body


def build_context(watch, diff, search_url: str, now: datetime | None = None) -> dict[str, Any]:
    """テンプレートに渡す変数一式を組み立てる。

    ここで定義した名前が、そのまま templates/ の中で使える変数になる。
    README の「テンプレート変数一覧」と対応させること。
    """
    return {
        "area_name": watch.name,
        "watch_id": watch.id,
        "checkin": watch.checkin_text,
        "checkout": watch.checkout_text,
        "stay_label": watch.stay_label,
        "nights": watch.nights,
        "adult_num": watch.adult_num,
        "room_num": watch.room_num,
        "prev_count": diff.prev_count,
        "curr_count": diff.curr_count,
        "diff": diff.diff_value,
        "diff_text": diff.diff_text,
        "direction": diff.direction,
        "direction_mark": diff.direction_mark,
        "added_hotels": diff.added,
        "removed_hotels": diff.removed,
        "current_hotels": diff.current,
        "min_price": diff.min_price,
        "min_price_text": diff.min_price_text,
        "search_url": search_url,
        "now": now or now_jst(),
    }
