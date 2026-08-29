"""前回の結果と今回の結果を比べて、変化を求める。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .models import Hotel


@dataclass
class Diff:
    """前回と今回の差分。メールのテンプレートからも参照される。"""

    prev_count: int
    curr_count: int
    added: list[Hotel] = field(default_factory=list)
    removed: list[Hotel] = field(default_factory=list)
    current: list[Hotel] = field(default_factory=list)

    @property
    def count_changed(self) -> bool:
        return self.prev_count != self.curr_count

    @property
    def hotels_changed(self) -> bool:
        return bool(self.added or self.removed)

    @property
    def changed(self) -> bool:
        return self.count_changed or self.hotels_changed

    @property
    def diff_value(self) -> int:
        return self.curr_count - self.prev_count

    @property
    def diff_text(self) -> str:
        """「+2」「-1」「±0」のような符号付き表記。"""
        value = self.diff_value
        if value > 0:
            return f"+{value}"
        if value < 0:
            return str(value)
        return "±0"

    @property
    def direction(self) -> str:
        if self.diff_value > 0:
            return "増加"
        if self.diff_value < 0:
            return "減少"
        return "入れ替わり"

    @property
    def direction_mark(self) -> str:
        if self.diff_value > 0:
            return "▲"
        if self.diff_value < 0:
            return "▼"
        return "◆"

    @property
    def min_price(self) -> int | None:
        prices = [h.price for h in self.current if h.price is not None]
        return min(prices) if prices else None

    @property
    def min_price_text(self) -> str:
        price = self.min_price
        return f"{price:,}" if price is not None else "―"

    def content_hash(self) -> str:
        """通知内容が前回とまったく同じかを判定するためのハッシュ。"""
        parts = [
            str(self.prev_count),
            str(self.curr_count),
            "|".join(sorted(h.hotel_no for h in self.added)),
            "|".join(sorted(h.hotel_no for h in self.removed)),
            "|".join(sorted(h.hotel_no for h in self.current)),
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def compute_diff(
    prev_count: int,
    prev_hotels: list[Hotel],
    curr_count: int,
    curr_hotels: list[Hotel],
) -> Diff:
    """前回と今回の宿一覧を突き合わせて Diff を作る。"""
    prev_map = {h.hotel_no: h for h in prev_hotels}
    curr_map = {h.hotel_no: h for h in curr_hotels}

    added = [curr_map[no] for no in curr_map if no not in prev_map]
    removed = [prev_map[no] for no in prev_map if no not in curr_map]

    # 表示順を安定させる（料金の安い順 → 名前順）
    def sort_key(hotel: Hotel):
        return (hotel.price if hotel.price is not None else 10**9, hotel.name)

    return Diff(
        prev_count=prev_count,
        curr_count=curr_count,
        added=sorted(added, key=sort_key),
        removed=sorted(removed, key=sort_key),
        current=sorted(curr_hotels, key=sort_key),
    )


def should_notify(diff: Diff, notify_on: str, notify_on_hotel_change: bool) -> bool:
    """設定に照らして、この変化を通知すべきか判定する。"""
    if not diff.changed:
        return False

    if diff.count_changed:
        if notify_on == "increase":
            return diff.diff_value > 0
        if notify_on == "decrease":
            return diff.diff_value < 0
        return True

    # 件数は同じで、宿の顔ぶれだけが入れ替わったケース
    return notify_on_hotel_change
