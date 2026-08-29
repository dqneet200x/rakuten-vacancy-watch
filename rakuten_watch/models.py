"""アプリ全体で使うデータ構造。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class Hotel:
    """空室のある宿1件分の情報。メールのテンプレートからも参照される。"""

    hotel_no: str
    name: str
    price: int | None = None
    url: str = ""
    review_average: float | None = None

    @property
    def price_text(self) -> str:
        """3桁区切りの料金文字列。料金不明なら「―」を返す。"""
        if self.price is None:
            return "―"
        return f"{self.price:,}"

    @property
    def review_text(self) -> str:
        if self.review_average is None:
            return "―"
        return f"{self.review_average:.2f}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Hotel":
        return cls(
            hotel_no=str(data.get("hotel_no", "")),
            name=data.get("name", ""),
            price=data.get("price"),
            url=data.get("url", ""),
            review_average=data.get("review_average"),
        )


@dataclass
class FetchResult:
    """1回の検索結果。"""

    count: int
    hotels: list[Hotel]
    source: str  # "api" または "html"


class FetchError(RuntimeError):
    """空室情報の取得に失敗したことを表す例外。"""
