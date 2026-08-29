"""前回の結果（state）の保存と読み込み。

state には「宿名・件数・日時」だけを保存する。
リポジトリを公開しても問題ないよう、メールアドレスやパスワードは一切書き込まない。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .models import Hotel

logger = logging.getLogger(__name__)


@dataclass
class WatchState:
    """監視条件1件分の保存内容。"""

    watch_id: str
    last_count: int | None = None
    hotels: list[Hotel] = field(default_factory=list)
    last_notified_hash: str = ""
    last_checked_at: str = ""
    last_change_at: str = ""
    consecutive_failures: int = 0
    last_error_mail_date: str = ""
    source: str = ""

    @property
    def is_baseline(self) -> bool:
        """まだ一度も取得できていない（初回実行）か。"""
        return self.last_count is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch_id,
            "last_count": self.last_count,
            "hotels": [h.to_dict() for h in self.hotels],
            "last_notified_hash": self.last_notified_hash,
            "last_checked_at": self.last_checked_at,
            "last_change_at": self.last_change_at,
            "consecutive_failures": self.consecutive_failures,
            "last_error_mail_date": self.last_error_mail_date,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WatchState":
        return cls(
            watch_id=str(data.get("watch_id", "")),
            last_count=data.get("last_count"),
            hotels=[Hotel.from_dict(h) for h in data.get("hotels") or []],
            last_notified_hash=str(data.get("last_notified_hash", "")),
            last_checked_at=str(data.get("last_checked_at", "")),
            last_change_at=str(data.get("last_change_at", "")),
            consecutive_failures=int(data.get("consecutive_failures", 0) or 0),
            last_error_mail_date=str(data.get("last_error_mail_date", "")),
            source=str(data.get("source", "")),
        )


class StateStore:
    """state ディレクトリの読み書き。"""

    def __init__(self, directory: str | Path = "state"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, watch_id: str) -> Path:
        safe = "".join(ch for ch in watch_id if ch.isalnum() or ch in "-_")
        return self.directory / f"{safe or 'watch'}.json"

    def load(self, watch_id: str) -> WatchState:
        path = self.path_for(watch_id)
        if not path.exists():
            return WatchState(watch_id=watch_id)
        try:
            # utf-8-sig にしておくと、メモ帳などが付ける BOM があっても読める
            with path.open("r", encoding="utf-8-sig") as fp:
                return WatchState.from_dict(json.load(fp))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "state ファイルを読めませんでした（%s）。初回扱いで続行します: %s", path, exc
            )
            return WatchState(watch_id=watch_id)

    def save(self, state: WatchState) -> None:
        path = self.path_for(state.watch_id)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fp:
            json.dump(state.to_dict(), fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        tmp.replace(path)


def touch_heartbeat(path: str | Path, today: date, interval_days: int = 6) -> bool:
    """週1回だけ heartbeat ファイルを更新する。

    GitHub は「60日間まったく更新のないリポジトリ」のスケジュール実行を
    自動停止する。空室に変化がない期間が続いても監視が止まらないよう、
    定期的にファイルを書き換えてコミット対象を作る。

    更新したら True を返す。
    """
    path = Path(path)
    if path.exists():
        try:
            previous = date.fromisoformat(path.read_text(encoding="utf-8").strip()[:10])
            if (today - previous).days < interval_days:
                return False
        except (ValueError, OSError):
            pass  # 読めなければ書き直す

    path.write_text(f"{today.isoformat()}\n", encoding="utf-8")
    return True
