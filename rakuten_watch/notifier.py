"""メール送信。

いまは Gmail の SMTP のみを実装しているが、Notifier を差し替えれば
Slack や Discord にも同じ呼び出し方で通知できる。
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT = 30


class NotifyError(RuntimeError):
    """通知の送信に失敗したことを表す例外。"""


class Notifier(ABC):
    @abstractmethod
    def send(self, subject: str, text_body: str, html_body: str | None = None) -> None:
        ...


class GmailNotifier(Notifier):
    """Gmail の SMTP からメールを送る。

    認証には Google アカウントの「アプリパスワード」（16桁）が必要で、
    通常のログインパスワードでは送信できない。
    """

    def __init__(
        self,
        address: str,
        app_password: str,
        recipients: list[str],
        from_name: str = "楽天トラベル空室監視",
    ):
        if not address:
            raise NotifyError("GMAIL_ADDRESS が設定されていません。")
        if not app_password:
            raise NotifyError("GMAIL_APP_PASSWORD が設定されていません。")
        if not recipients:
            raise NotifyError("NOTIFY_TO が設定されていません。")

        self.address = address.strip()
        # アプリパスワードは画面上 4桁ずつ空白区切りで表示されるため、空白を除去する
        self.app_password = app_password.replace(" ", "").strip()
        self.recipients = recipients
        self.from_name = from_name

    def build_message(
        self, subject: str, text_body: str, html_body: str | None = None
    ) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.from_name, self.address))
        message["To"] = ", ".join(self.recipients)
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain="gmail.com")
        # 自動送信であることを明示する。受信側の自動応答ループを防ぐ意味もある。
        message["Auto-Submitted"] = "auto-generated"

        message.set_content(text_body, subtype="plain", charset="utf-8")
        if html_body:
            message.add_alternative(html_body, subtype="html", charset="utf-8")
        return message

    def send(self, subject: str, text_body: str, html_body: str | None = None) -> None:
        message = self.build_message(subject, text_body, html_body)
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self.address, self.app_password)
                server.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise NotifyError(
                "Gmail の認証に失敗しました。2段階認証を有効にしたうえで発行した"
                "「アプリパスワード」16桁を GMAIL_APP_PASSWORD に設定してください。"
                f"（{exc.smtp_code}）"
            ) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise NotifyError(f"メールの送信に失敗しました: {exc}") from exc

        logger.info("メールを送信しました → %s", ", ".join(self.recipients))


class ConsoleNotifier(Notifier):
    """--dry-run / --preview-mail 用。送信せず標準出力に表示する。"""

    def __init__(self, show_html: bool = False):
        self.show_html = show_html

    def send(self, subject: str, text_body: str, html_body: str | None = None) -> None:
        line = "=" * 70
        print(f"\n{line}\n件名: {subject}\n{line}\n{text_body}\n{line}")
        if self.show_html and html_body:
            print("\n--- HTML版 ---\n")
            print(html_body)


def parse_recipients(raw: str | None) -> list[str]:
    """カンマ／セミコロン／改行区切りの宛先文字列をリストに変換する。"""
    if not raw:
        return []
    separators = [";", "\n", " "]
    normalized = raw
    for sep in separators:
        normalized = normalized.replace(sep, ",")
    return [part.strip() for part in normalized.split(",") if part.strip()]


def build_notifier_from_env(from_name: str) -> GmailNotifier:
    """環境変数から GmailNotifier を組み立てる。"""
    return GmailNotifier(
        address=os.getenv("GMAIL_ADDRESS", ""),
        app_password=os.getenv("GMAIL_APP_PASSWORD", ""),
        recipients=parse_recipients(os.getenv("NOTIFY_TO")),
        from_name=from_name,
    )
