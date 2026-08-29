"""楽天トラベル 空室監視 — 実行スクリプト。

使い方:
    python main.py                 通常の監視（変化があればメール送信）
    python main.py --dry-run       取得と比較はするがメールは送らない
    python main.py --preview-mail  ダミーデータでメール文面だけ確認する
    python main.py --test-mail     テストメールを1通送って疎通確認する
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from rakuten_watch.config import ConfigError, Watch, load_config
from rakuten_watch.differ import compute_diff
from rakuten_watch.fetchers import build_fetchers
from rakuten_watch.logging_utils import register_secrets, setup_logging
from rakuten_watch.models import Hotel
from rakuten_watch.notifier import (
    ConsoleNotifier,
    GmailNotifier,
    Notifier,
    NotifyError,
    parse_recipients,
)
from rakuten_watch.runner import WatchRunner
from rakuten_watch.state import StateStore
from rakuten_watch.templating import TemplateRenderer, build_context, now_jst
from rakuten_watch.urls import build_search_url

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="楽天トラベルの空室件数を監視し、変化があればメールで通知します。"
    )
    parser.add_argument("--config", default=str(ROOT / "config.yaml"), help="設定ファイルのパス")
    parser.add_argument("--state-dir", default=str(ROOT / "state"), help="state の保存先")
    parser.add_argument("--templates", default=str(ROOT / "templates"), help="テンプレートの場所")
    parser.add_argument("--log-file", default=None, help="ログファイルのパス（省略時は画面のみ）")
    parser.add_argument("--dry-run", action="store_true", help="メールを送らずに結果を表示する")
    parser.add_argument("--test-mail", action="store_true", help="テストメールを1通送る")
    parser.add_argument(
        "--preview-mail", action="store_true", help="ダミーデータでメール文面を確認する"
    )
    parser.add_argument("--verbose", action="store_true", help="詳細ログを出す")
    return parser.parse_args(argv)


def load_secrets() -> dict[str, str]:
    """GitHub Actions では環境変数から、ローカルでは .env から読む。"""
    load_dotenv(ROOT / ".env")  # 既存の環境変数は上書きしない
    secrets = {
        "rakuten_application_id": (os.getenv("RAKUTEN_APPLICATION_ID") or "").strip(),
        "gmail_address": (os.getenv("GMAIL_ADDRESS") or "").strip(),
        "gmail_app_password": (os.getenv("GMAIL_APP_PASSWORD") or "").strip(),
        "notify_to": (os.getenv("NOTIFY_TO") or "").strip(),
    }
    # ログに出てしまわないよう、伏せ字の対象として登録する
    register_secrets(
        secrets["gmail_app_password"],
        secrets["gmail_app_password"].replace(" ", ""),
        secrets["rakuten_application_id"],
        secrets["gmail_address"],
        *parse_recipients(secrets["notify_to"]),
    )
    return secrets


def build_notifier(secrets: dict[str, str], from_name: str, dry_run: bool) -> Notifier:
    if dry_run:
        return ConsoleNotifier()
    return GmailNotifier(
        address=secrets["gmail_address"],
        app_password=secrets["gmail_app_password"],
        recipients=parse_recipients(secrets["notify_to"]),
        from_name=from_name,
    )


# ---------------------------------------------------------------------------
# --preview-mail 用のダミーデータ
# ---------------------------------------------------------------------------
def sample_preview(renderer: TemplateRenderer, send_html: bool) -> None:
    today = date.today()
    watch = Watch(
        id="preview",
        name="青森市周辺",
        checkin=today + timedelta(days=21),
        checkout=today + timedelta(days=22),
        middle_class_code="aomori",
        small_class_code="aomori",
    )
    prev_hotels = [
        Hotel(
            hotel_no="200696",
            name="スローハウス青森",
            price=30160,
            url="https://travel.rakuten.co.jp/HOTEL/200696/200696.html",
        ),
    ]
    curr_hotels = prev_hotels + [
        Hotel(
            hotel_no="123456",
            name="青森ベイサイドホテル",
            price=12800,
            url="https://travel.rakuten.co.jp/HOTEL/123456/123456.html",
            review_average=4.12,
        ),
        Hotel(
            hotel_no="654321",
            name="ホテル青森駅前",
            price=18500,
            url="https://travel.rakuten.co.jp/HOTEL/654321/654321.html",
            review_average=3.87,
        ),
    ]
    diff = compute_diff(1, prev_hotels, 3, curr_hotels)
    context = build_context(watch, diff, build_search_url(watch))

    subject = renderer.render_subject(context)
    text_body, html_body = renderer.render_bodies(context, send_html)

    line = "=" * 70
    print(line)
    print("--preview-mail によるプレビューです（メールは送信していません）")
    print(line)
    print(f"件名: {subject}")
    print(line)
    print(text_body)
    print(line)

    if html_body:
        preview_path = ROOT / "preview_mail.html"
        preview_path.write_text(html_body, encoding="utf-8")
        print(f"HTML版を書き出しました: {preview_path}")
        print("ブラウザで開くと、実際の見た目を確認できます。")


def send_test_mail(notifier: Notifier) -> int:
    now = now_jst().strftime("%Y-%m-%d %H:%M")
    subject = f"【テスト】楽天トラベル空室監視の疎通確認（{now}）"
    text = (
        "このメールが届いていれば、Gmail からの送信設定は正常です。\n\n"
        "迷惑メールフォルダに入っていた場合は、差出人アドレスを\n"
        "Yahoo!メールの「受信許可リスト」に登録してください。\n\n"
        f"送信日時: {now}（日本時間）\n"
    )
    html = (
        "<p>このメールが届いていれば、Gmail からの送信設定は<b>正常</b>です。</p>"
        "<p>迷惑メールフォルダに入っていた場合は、差出人アドレスを "
        "Yahoo!メールの「受信許可リスト」に登録してください。</p>"
        f"<p>送信日時: {now}（日本時間）</p>"
    )
    try:
        notifier.send(subject, text, html)
    except NotifyError as exc:
        logger.error("テストメールの送信に失敗しました: %s", exc)
        return 1
    print("テストメールを送信しました。受信箱と迷惑メールフォルダを確認してください。")
    return 0


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(verbose=args.verbose, log_file=args.log_file)
    secrets = load_secrets()

    renderer = TemplateRenderer(args.templates)

    # 文面のプレビューだけなら、認証情報は不要
    if args.preview_mail:
        try:
            send_html = load_config(args.config).mail.send_html
        except ConfigError:
            send_html = True
        sample_preview(renderer, send_html)
        return 0

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        logger.error("設定ファイルの読み込みに失敗しました: %s", exc)
        return 2

    try:
        notifier = build_notifier(secrets, config.mail.from_name, args.dry_run)
    except NotifyError as exc:
        logger.error("メールの設定が不足しています: %s", exc)
        logger.error("ローカル実行なら .env を、GitHub Actions なら Secrets を確認してください。")
        return 2

    if args.test_mail:
        return send_test_mail(notifier)

    if secrets["rakuten_application_id"]:
        logger.info("楽天APIのアプリIDが設定されています（API優先、失敗時はHTMLに切替）。")
    else:
        logger.info("楽天APIのアプリID未設定のため、検索ページのHTMLから取得します。")

    runner = WatchRunner(
        config=config,
        fetchers=build_fetchers(secrets["rakuten_application_id"]),
        notifier=notifier,
        store=StateStore(args.state_dir),
        renderer=renderer,
        dry_run=args.dry_run,
    )

    summary = runner.run()
    runner.update_heartbeat(ROOT / "heartbeat.txt")

    for message in summary.messages:
        logger.info("  - %s", message)

    # 一部が失敗しても終了コードは 0 のままにする。
    # （GitHub Actions から失敗メールが毎回飛ぶのを避けるため）
    if summary.failures and summary.checked == summary.failures:
        logger.error("すべての監視条件で取得に失敗しました。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
