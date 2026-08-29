"""ログ設定と、秘密情報のマスク。

リポジトリを公開して運用する前提のため、アプリパスワードやメールアドレスが
ログに残らないよう、出力の直前で必ず伏せ字に置き換える。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MIN_MASK_LENGTH = 4


class SecretMaskFilter(logging.Filter):
    """登録された文字列をログ出力から伏せ字にするフィルタ。"""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: list[str] = []

    def add(self, *values: str | None) -> None:
        for value in values:
            if value and len(value) >= _MIN_MASK_LENGTH and value not in self._secrets:
                self._secrets.append(value)

    def _mask(self, text: str) -> str:
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, "****")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        try:
            record.msg = self._mask(str(record.msg))
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: self._mask(str(v)) for k, v in record.args.items()}
                else:
                    record.args = tuple(self._mask(str(a)) for a in record.args)
        except Exception:  # ログ処理で本体を落とさない
            pass
        return True


mask_filter = SecretMaskFilter()


def setup_logging(verbose: bool = False, log_file: str | Path | None = None) -> None:
    """標準出力へのログを設定する。log_file を指定するとファイルにも残す。"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(mask_filter)
    root.addHandler(stream)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(formatter)
        rotating.addFilter(mask_filter)
        root.addHandler(rotating)

    # requests の詳細ログにURLごと秘密が乗ることがあるため抑制する
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def register_secrets(*values: str | None) -> None:
    """ログから伏せ字にしたい文字列を登録する。"""
    mask_filter.add(*values)
