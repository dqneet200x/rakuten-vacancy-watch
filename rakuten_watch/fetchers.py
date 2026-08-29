"""空室情報の取得。

取得経路は2通りある。

1. 楽天ウェブサービスの「空室検索API」 … アプリIDが必要。構造が安定していて堅牢。
2. 楽天トラベルの検索ページのHTML … アプリID不要。誰でもすぐ使える。

アプリIDが設定されていれば 1 を使い、無ければ 2 に自動で切り替わる。
1 が使えない状況（IP制限など）では 2 にフォールバックする。
"""

from __future__ import annotations

import html as html_module
import logging
import random
import re
import time
from typing import Callable

import requests

from .config import Watch
from .models import FetchError, FetchResult, Hotel
from .urls import build_search_url

logger = logging.getLogger(__name__)

API_ENDPOINT = "https://app.rakuten.co.jp/services/api/Travel/VacantHotelSearch/20170426"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30


# --------------------------------------------------------------------------
# 1. 楽天ウェブサービス API
# --------------------------------------------------------------------------
class RakutenApiFetcher:
    """楽天ウェブサービスの空室検索APIから取得する。"""

    name = "api"

    def __init__(self, application_id: str, session: requests.Session | None = None):
        self.application_id = application_id
        self.session = session or requests.Session()

    def fetch(self, watch: Watch) -> FetchResult:
        hotels: list[Hotel] = []
        total = 0
        page = 1

        while page <= watch.max_pages:
            payload = self._request_page(watch, page)
            if payload is None:  # 該当なし
                break

            paging = payload.get("pagingInfo") or {}
            total = int(paging.get("recordCount", 0) or 0)
            hotels.extend(self._parse_hotels(payload))

            page_count = int(paging.get("pageCount", 1) or 1)
            if page >= page_count:
                break
            page += 1
            time.sleep(1.0)  # 楽天APIへの負荷を避けるため1秒あける

        # recordCount が取れないケースに備え、実際に取れた件数で補完する
        if total == 0 and hotels:
            total = len(hotels)

        return FetchResult(count=total, hotels=hotels, source=self.name)

    def _request_page(self, watch: Watch, page: int) -> dict | None:
        params = {
            "applicationId": self.application_id,
            "format": "json",
            "formatVersion": 2,
            "largeClassCode": watch.large_class_code,
            "middleClassCode": watch.middle_class_code,
            "smallClassCode": watch.small_class_code,
            "checkinDate": watch.checkin_text,
            "checkoutDate": watch.checkout_text,
            "adultNum": watch.adult_num,
            "roomNum": watch.room_num,
            "hits": watch.hits,
            "page": page,
        }
        if watch.detail_class_code:
            params["detailClassCode"] = watch.detail_class_code

        try:
            response = self.session.get(API_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise FetchError(f"楽天APIへの接続に失敗しました: {exc}") from exc

        # 「該当なし」は異常ではなく 0 件として扱う
        if response.status_code == 404:
            if "not_found" in response.text:
                logger.info("楽天API: 該当する空室がありませんでした（0件）")
                return None
            raise FetchError(f"楽天APIが404を返しました: {response.text[:200]}")

        if response.status_code == 429:
            raise FetchError("楽天APIのレート制限に達しました（429）")

        if response.status_code >= 400:
            raise FetchError(
                f"楽天APIがエラーを返しました（HTTP {response.status_code}）: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError("楽天APIの応答をJSONとして解釈できませんでした。") from exc

        if isinstance(payload, dict) and payload.get("error"):
            if payload.get("error") == "not_found":
                return None
            raise FetchError(
                f"楽天APIエラー: {payload.get('error')} / {payload.get('error_description')}"
            )
        return payload

    @staticmethod
    def _parse_hotels(payload: dict) -> list[Hotel]:
        """formatVersion=2 と 1 の両方の構造を受け付ける。"""
        results: list[Hotel] = []
        for entry in payload.get("hotels") or []:
            # formatVersion=1 は {"hotel": [...]}、2 は [...] の形
            parts = entry.get("hotel") if isinstance(entry, dict) else entry
            if not isinstance(parts, list):
                continue

            basic = None
            for part in parts:
                if isinstance(part, dict) and "hotelBasicInfo" in part:
                    basic = part["hotelBasicInfo"]
                    break
            if not basic:
                continue

            price = basic.get("hotelMinCharge")
            review = basic.get("reviewAverage")
            results.append(
                Hotel(
                    hotel_no=str(basic.get("hotelNo", "")),
                    name=str(basic.get("hotelName", "")).strip(),
                    price=int(price) if isinstance(price, (int, float)) else None,
                    url=str(basic.get("hotelInformationUrl", "") or ""),
                    review_average=float(review) if isinstance(review, (int, float)) else None,
                )
            )
        return results


# --------------------------------------------------------------------------
# 2. 検索ページのHTML
# --------------------------------------------------------------------------
# 実際の楽天トラベル検索結果ページで確認した並び。
_RE_TOTAL = re.compile(r'pagination__info-text--total"[^>]*>\s*([\d,]+)\s*<')
_RE_HOTEL_NO = re.compile(r"travel\.rakuten\.co\.jp/HOTEL/(\d+)/", re.IGNORECASE)
_RE_NAME = re.compile(r"hotel-list__title-text[^>]*>(.*?)</h2>", re.DOTALL)
_RE_PRICE = re.compile(r'class="ndPrice"[^>]*>\s*合計\s*<strong>\s*([\d,]+)\s*</strong>')
# レビュー評価は「クチコミへのリンク → <strong>4.50</strong>（2件）」の形で入っている。
# 宿番号ごと拾えるので、並び順に頼らず宿番号で突き合わせられる。
_RE_REVIEW = re.compile(
    r"review\.travel\.rakuten\.co\.jp/hotel/voice/(\d+).{0,400}?<strong>\s*([\d.]+)\s*</strong>",
    re.DOTALL,
)
_RE_TAG = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str) -> str:
    text = _RE_TAG.sub("", fragment)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_hotel_name(name: str) -> str:
    """宿名の末尾に付く装飾記号を取り除く。

    楽天トラベルの一覧では宿名のうしろに「＾」などの記号が付くことがあり、
    そのままだと宿名として不自然なうえ、表記ゆれで差分検知が誤作動しかねない。
    """
    return name.rstrip(" 　^＾*＊").strip()


class HtmlFetcher:
    """楽天トラベルの検索結果ページを読んで件数と宿名を取り出す。

    アプリIDが不要な代わりに、楽天側のページ構造が変わると壊れる可能性がある。
    そのため「件数」と「宿の一覧」を独立して解析し、一覧の解析が失敗しても
    件数だけは取れるようにしている。
    """

    name = "html"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def fetch(self, watch: Watch) -> FetchResult:
        url = build_search_url(watch)
        try:
            response = self.session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": BROWSER_UA,
                    "Accept-Language": "ja,en;q=0.8",
                },
            )
        except requests.RequestException as exc:
            raise FetchError(f"楽天トラベルへの接続に失敗しました: {exc}") from exc

        if response.status_code >= 400:
            raise FetchError(f"楽天トラベルがHTTP {response.status_code} を返しました。")

        response.encoding = response.apparent_encoding or "utf-8"
        return self.parse(response.text)

    @classmethod
    def parse(cls, html: str) -> FetchResult:
        count = cls._parse_count(html)
        hotels = cls._parse_hotels(html)

        if count is None:
            if hotels:
                count = len(hotels)
            elif cls._looks_like_zero_result(html):
                count = 0
            else:
                raise FetchError(
                    "検索結果ページから件数を読み取れませんでした。"
                    "楽天トラベル側のページ構造が変わった可能性があります。"
                )
        return FetchResult(count=count, hotels=hotels, source=cls.name)

    @staticmethod
    def _parse_count(html: str) -> int | None:
        match = _RE_TOTAL.search(html)
        if not match:
            return None
        return int(match.group(1).replace(",", ""))

    @staticmethod
    def _looks_like_zero_result(html: str) -> bool:
        markers = ("条件に一致する", "見つかりませんでした", "該当する宿泊施設")
        return any(marker in html for marker in markers)

    @classmethod
    def _parse_hotels(cls, html: str) -> list[Hotel]:
        names = [_clean_hotel_name(_strip_tags(m)) for m in _RE_NAME.findall(html)]
        hotel_nos: list[str] = []
        for no in _RE_HOTEL_NO.findall(html):
            if no not in hotel_nos:
                hotel_nos.append(no)
        prices = [int(p.replace(",", "")) for p in _RE_PRICE.findall(html)]

        reviews: dict[str, float] = {}
        for hotel_no, score in _RE_REVIEW.findall(html):
            try:
                reviews.setdefault(hotel_no, float(score))
            except ValueError:
                continue

        hotels: list[Hotel] = []
        for index, name in enumerate(names):
            hotel_no = hotel_nos[index] if index < len(hotel_nos) else f"unknown-{index}"
            price = prices[index] if index < len(prices) else None
            url = (
                f"https://travel.rakuten.co.jp/HOTEL/{hotel_no}/{hotel_no}.html"
                if hotel_no.isdigit()
                else ""
            )
            hotels.append(
                Hotel(
                    hotel_no=hotel_no,
                    name=name,
                    price=price,
                    url=url,
                    review_average=reviews.get(hotel_no),
                )
            )
        return hotels


# --------------------------------------------------------------------------
# 経路の選択とリトライ
# --------------------------------------------------------------------------
def build_fetchers(application_id: str | None) -> list:
    """使う取得経路を優先順に並べて返す。

    アプリIDがあれば API → HTML の順、無ければ HTML のみ。
    """
    session = requests.Session()
    if application_id:
        return [RakutenApiFetcher(application_id, session), HtmlFetcher(session)]
    return [HtmlFetcher(session)]


def fetch_with_retry(
    fetchers: list,
    watch: Watch,
    max_attempts: int = 3,
    sleeper: Callable[[float], None] | None = None,
) -> FetchResult:
    """指数バックオフでリトライしつつ、取得経路を順に試す。"""
    # 既定値をここで解決する。引数の既定値にすると time.sleep が定義時に
    # 束縛されてしまい、テストから差し替えられなくなる。
    sleeper = sleeper or time.sleep
    last_error: Exception | None = None

    for fetcher in fetchers:
        for attempt in range(1, max_attempts + 1):
            try:
                result = fetcher.fetch(watch)
                logger.info(
                    "取得成功（経路=%s, 件数=%d, 宿一覧=%d件）",
                    result.source,
                    result.count,
                    len(result.hotels),
                )
                return result
            except FetchError as exc:
                last_error = exc
                if attempt < max_attempts:
                    wait = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                    logger.warning(
                        "取得失敗（経路=%s, %d回目）: %s / %.1f秒後に再試行",
                        fetcher.name,
                        attempt,
                        exc,
                        wait,
                    )
                    sleeper(wait)
                else:
                    logger.warning(
                        "経路=%s は %d回試して失敗しました: %s", fetcher.name, max_attempts, exc
                    )

    raise FetchError(f"すべての取得経路が失敗しました: {last_error}")
