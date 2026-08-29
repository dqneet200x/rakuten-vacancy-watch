"""config.yaml の読み込みと、監視条件の表現。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

VALID_NOTIFY_ON = {"both", "increase", "decrease"}


class ConfigError(ValueError):
    """設定ファイルの内容が不正なときに送出される。"""


@dataclass
class Watch:
    """監視条件1件。"""

    id: str
    name: str
    checkin: date
    checkout: date
    large_class_code: str = "japan"
    middle_class_code: str = ""
    small_class_code: str = ""
    detail_class_code: str = ""
    adult_num: int = 2
    room_num: int = 1
    hits: int = 30
    max_pages: int = 10
    notify_on: str = "both"
    notify_on_hotel_change: bool = True
    enabled: bool = True

    @property
    def nights(self) -> int:
        return (self.checkout - self.checkin).days

    @property
    def checkin_text(self) -> str:
        return self.checkin.strftime("%Y-%m-%d")

    @property
    def checkout_text(self) -> str:
        return self.checkout.strftime("%Y-%m-%d")

    @property
    def stay_label(self) -> str:
        """「9/20-21」のような短い表記。件名で使う。"""
        return (
            f"{self.checkin.month}/{self.checkin.day}"
            f"-{self.checkout.day if self.checkin.month == self.checkout.month else f'{self.checkout.month}/{self.checkout.day}'}"
        )


@dataclass
class MailConfig:
    from_name: str = "楽天トラベル空室監視"
    send_html: bool = True


@dataclass
class AppConfig:
    mail: MailConfig = field(default_factory=MailConfig)
    watches: list[Watch] = field(default_factory=list)

    @property
    def enabled_watches(self) -> list[Watch]:
        return [w for w in self.watches if w.enabled]


def _parse_date(value: Any, field_name: str, watch_id: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ConfigError(
                f"watch「{watch_id}」の {field_name} が YYYY-MM-DD 形式ではありません: {value!r}"
            ) from exc
    raise ConfigError(f"watch「{watch_id}」の {field_name} が未設定です。")


def load_config(path: str | Path) -> AppConfig:
    """config.yaml を読み込んで AppConfig を返す。"""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"設定ファイルが見つかりません: {path}")

    # utf-8-sig にしておくと、メモ帳などが付ける BOM があっても読める
    with path.open("r", encoding="utf-8-sig") as fp:
        raw = yaml.safe_load(fp) or {}

    mail_raw = raw.get("mail") or {}
    mail = MailConfig(
        from_name=str(mail_raw.get("from_name", MailConfig.from_name)),
        send_html=bool(mail_raw.get("send_html", True)),
    )

    defaults = raw.get("defaults") or {}
    watches_raw = raw.get("watches") or []
    if not watches_raw:
        raise ConfigError("config.yaml に watches が1件もありません。")

    watches: list[Watch] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(watches_raw, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"watches の {index} 件目が辞書形式ではありません。")

        merged: dict[str, Any] = {**defaults, **item}
        watch_id = str(merged.get("id") or f"watch{index}")
        if watch_id in seen_ids:
            raise ConfigError(f"watch の id が重複しています: {watch_id}")
        seen_ids.add(watch_id)

        notify_on = str(merged.get("notify_on", "both")).strip().lower()
        if notify_on not in VALID_NOTIFY_ON:
            raise ConfigError(
                f"watch「{watch_id}」の notify_on は "
                f"{'/'.join(sorted(VALID_NOTIFY_ON))} のいずれかにしてください: {notify_on!r}"
            )

        checkin = _parse_date(merged.get("checkin"), "checkin", watch_id)
        checkout = _parse_date(merged.get("checkout"), "checkout", watch_id)
        if checkout <= checkin:
            raise ConfigError(
                f"watch「{watch_id}」: checkout は checkin より後の日付にしてください。"
            )

        watches.append(
            Watch(
                id=watch_id,
                name=str(merged.get("name") or watch_id),
                checkin=checkin,
                checkout=checkout,
                large_class_code=str(merged.get("large_class_code", "japan") or ""),
                middle_class_code=str(merged.get("middle_class_code", "") or ""),
                small_class_code=str(merged.get("small_class_code", "") or ""),
                detail_class_code=str(merged.get("detail_class_code", "") or ""),
                adult_num=int(merged.get("adult_num", 2)),
                room_num=int(merged.get("room_num", 1)),
                hits=min(int(merged.get("hits", 30)), 30),
                max_pages=int(merged.get("max_pages", 10)),
                notify_on=notify_on,
                notify_on_hotel_change=bool(merged.get("notify_on_hotel_change", True)),
                enabled=bool(merged.get("enabled", True)),
            )
        )

    return AppConfig(mail=mail, watches=watches)
