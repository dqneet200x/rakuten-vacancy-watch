"""秘密情報マスクのテスト。

マスクが有効なときに限って壊れる不具合があったため、
「秘密情報を登録した状態」でログが正しく出ることを必ず確認する。
"""

import logging

import pytest

from rakuten_watch.logging_utils import SecretMaskFilter


@pytest.fixture
def masking_logger():
    """秘密情報を登録済みのロガーと、その出力を集めるハンドラを返す。"""
    records: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    mask = SecretMaskFilter()
    mask.add("abcdefghijklmnop", "himitsu@gmail.com")

    handler = Collector()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(mask)

    logger = logging.getLogger("test_masking")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger, records


def test_numeric_format_still_works(masking_logger):
    """マスクが有効でも %d の書式が壊れないこと。"""
    logger, records = masking_logger
    logger.info("取得成功（経路=%s, 件数=%d, 宿一覧=%d件）", "html", 1, 1)
    assert records == ["取得成功（経路=html, 件数=1, 宿一覧=1件）"]


def test_float_format_still_works(masking_logger):
    logger, records = masking_logger
    logger.info("%.1f秒後に再試行", 1.5)
    assert records == ["1.5秒後に再試行"]


def test_secret_in_string_arg_is_masked(masking_logger):
    logger, records = masking_logger
    logger.info("送信元: %s", "himitsu@gmail.com")
    assert "himitsu@gmail.com" not in records[0]
    assert "****" in records[0]


def test_secret_in_message_is_masked(masking_logger):
    logger, records = masking_logger
    logger.info("パスワードは abcdefghijklmnop です")
    assert "abcdefghijklmnop" not in records[0]


def test_mixed_args(masking_logger):
    """文字列と数値が混ざっていても、両方正しく扱えること。"""
    logger, records = masking_logger
    logger.info("%s に %d 通送信", "himitsu@gmail.com", 3)
    assert "3 通送信" in records[0]
    assert "himitsu@gmail.com" not in records[0]


def test_short_values_are_not_registered():
    """短すぎる値をマスク対象にすると、無関係な文字まで伏せ字になってしまう。"""
    mask = SecretMaskFilter()
    mask.add("ab", "")
    assert mask._mask("abcdef") == "abcdef"


def test_no_secrets_registered_is_passthrough(masking_logger):
    mask = SecretMaskFilter()
    record = logging.LogRecord("x", logging.INFO, "f", 1, "件数=%d", (5,), None)
    assert mask.filter(record) is True
    assert record.args == (5,)
