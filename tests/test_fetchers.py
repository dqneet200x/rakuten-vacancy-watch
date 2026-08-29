import pytest

from rakuten_watch.fetchers import HtmlFetcher, RakutenApiFetcher, fetch_with_retry
from rakuten_watch.models import FetchError
from rakuten_watch.urls import build_search_url


class DummyFetcher:
    def __init__(self, name, results):
        self.name = name
        self.results = list(results)
        self.calls = 0

    def fetch(self, watch):
        self.calls += 1
        outcome = self.results.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --- HTML 解析 -------------------------------------------------------------
def test_html_parses_real_page(search_html):
    result = HtmlFetcher.parse(search_html)
    assert result.count == 1
    assert result.source == "html"
    assert len(result.hotels) == 1

    hotel = result.hotels[0]
    assert hotel.hotel_no == "200696"
    # 末尾の装飾記号「＾」が取り除かれていること
    assert hotel.name == "スローハウス青森"
    assert hotel.price == 30160
    assert hotel.price_text == "30,160"
    assert hotel.url == "https://travel.rakuten.co.jp/HOTEL/200696/200696.html"
    assert hotel.review_average == 4.50
    assert hotel.review_text == "4.50"


def test_html_without_review_is_none(search_html):
    """レビューがまだ無い宿でも解析が壊れないこと。"""
    stripped = search_html.replace("review.travel.rakuten.co.jp", "example.invalid")
    hotel = HtmlFetcher.parse(stripped).hotels[0]
    assert hotel.review_average is None
    assert hotel.review_text == "―"
    assert hotel.price == 30160  # 他の項目は影響を受けない


def test_html_parses_larger_count():
    html = '<span class="pagination__info-text--total">1,234</span>件中'
    result = HtmlFetcher.parse(html)
    assert result.count == 1234


def test_html_zero_result_without_count():
    html = "<p>条件に一致する宿泊施設が見つかりませんでした。</p>"
    result = HtmlFetcher.parse(html)
    assert result.count == 0
    assert result.hotels == []


def test_html_unrecognised_page_raises():
    with pytest.raises(FetchError):
        HtmlFetcher.parse("<html><body>まったく別のページ</body></html>")


# --- API 応答の解析 --------------------------------------------------------
def test_api_parses_format_version_2():
    payload = {
        "pagingInfo": {"recordCount": 2, "pageCount": 1},
        "hotels": [
            [{"hotelBasicInfo": {"hotelNo": 200696, "hotelName": "スローハウス青森",
                                 "hotelMinCharge": 30160, "reviewAverage": 4.2,
                                 "hotelInformationUrl": "https://example.com/a"}}],
            [{"hotelBasicInfo": {"hotelNo": 123456, "hotelName": "青森ベイサイド",
                                 "hotelMinCharge": 12800}}],
        ],
    }
    hotels = RakutenApiFetcher._parse_hotels(payload)
    assert [h.hotel_no for h in hotels] == ["200696", "123456"]
    assert hotels[0].review_average == 4.2
    assert hotels[1].review_average is None


def test_api_parses_format_version_1():
    payload = {
        "hotels": [
            {"hotel": [{"hotelBasicInfo": {"hotelNo": 1, "hotelName": "宿A", "hotelMinCharge": 100}}]}
        ]
    }
    hotels = RakutenApiFetcher._parse_hotels(payload)
    assert hotels[0].name == "宿A"


# --- リトライと経路の切り替え ---------------------------------------------
def test_retry_then_success(watch):
    from rakuten_watch.models import FetchResult

    fetcher = DummyFetcher("api", [FetchError("一時エラー"), FetchResult(3, [], "api")])
    result = fetch_with_retry([fetcher], watch, max_attempts=3, sleeper=lambda _: None)
    assert result.count == 3
    assert fetcher.calls == 2


def test_falls_back_to_second_fetcher(watch):
    from rakuten_watch.models import FetchResult

    failing = DummyFetcher("api", [FetchError("x")] * 3)
    working = DummyFetcher("html", [FetchResult(1, [], "html")])
    result = fetch_with_retry([failing, working], watch, max_attempts=3, sleeper=lambda _: None)
    assert result.source == "html"
    assert failing.calls == 3


def test_all_fetchers_fail(watch):
    failing = DummyFetcher("html", [FetchError("x")] * 3)
    with pytest.raises(FetchError):
        fetch_with_retry([failing], watch, max_attempts=3, sleeper=lambda _: None)


# --- URL 組み立て ----------------------------------------------------------
def test_search_url_contains_watch_parameters(watch):
    url = build_search_url(watch)
    assert "f_chu=aomori" in url
    assert "f_nen1=2026" in url
    assert "f_tuki1=9" in url
    assert "f_hi1=20" in url
    assert "f_hi2=21" in url
    assert "f_otona_su=2" in url
    assert "f_heya_su=1" in url
