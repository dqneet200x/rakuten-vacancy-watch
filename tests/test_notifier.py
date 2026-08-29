import pytest

from rakuten_watch.notifier import GmailNotifier, NotifyError, parse_recipients


def test_parse_recipients_comma():
    assert parse_recipients("a@x.jp, b@y.jp") == ["a@x.jp", "b@y.jp"]


def test_parse_recipients_other_separators():
    assert parse_recipients("a@x.jp; b@y.jp\nc@z.jp") == ["a@x.jp", "b@y.jp", "c@z.jp"]


def test_parse_recipients_empty():
    assert parse_recipients("") == []
    assert parse_recipients(None) == []


def test_missing_settings_raise():
    with pytest.raises(NotifyError):
        GmailNotifier("", "pw", ["a@x.jp"])
    with pytest.raises(NotifyError):
        GmailNotifier("a@gmail.com", "", ["a@x.jp"])
    with pytest.raises(NotifyError):
        GmailNotifier("a@gmail.com", "pw", [])


def test_app_password_spaces_are_stripped():
    notifier = GmailNotifier("a@gmail.com", "abcd efgh ijkl mnop", ["b@yahoo.co.jp"])
    assert notifier.app_password == "abcdefghijklmnop"


def make_notifier():
    return GmailNotifier(
        "sender@gmail.com", "abcdefghijklmnop", ["to@yahoo.co.jp"], from_name="空室監視"
    )


def test_message_headers():
    message = make_notifier().build_message("件名テスト", "本文です")
    assert message["To"] == "to@yahoo.co.jp"
    assert "sender@gmail.com" in message["From"]
    assert message["Auto-Submitted"] == "auto-generated"
    assert message["Subject"] == "件名テスト"


def test_japanese_subject_is_encoded_and_decodes_back():
    """日本語の件名がヘッダとして正しくエンコードされ、元に戻せること。"""
    from email.header import decode_header

    subject = "▲【楽天トラベル】青森 9/20-21 の空室 1件 → 3件"
    message = make_notifier().build_message(subject, "本文")

    raw = message["Subject"]
    decoded = "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in decode_header(raw)
    )
    assert decoded == subject


def test_multipart_when_html_given():
    message = make_notifier().build_message("件名", "テキスト本文", "<p>HTML本文</p>")
    assert message.is_multipart()
    types = [part.get_content_type() for part in message.walk()]
    assert "text/plain" in types
    assert "text/html" in types


def test_plain_only_when_no_html():
    message = make_notifier().build_message("件名", "テキスト本文")
    assert message.get_content_type() == "text/plain"


def test_body_survives_round_trip():
    body = "空室が 1件 → 3件 に変化しました。\n最安 12,800円"
    message = make_notifier().build_message("件名", body)
    assert message.get_content().strip() == body.strip()
