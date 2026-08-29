import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rakuten_watch.config import Watch  # noqa: E402
from rakuten_watch.models import Hotel  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """リトライの待ち時間はテストでは不要なので飛ばす。"""
    monkeypatch.setattr("rakuten_watch.fetchers.time.sleep", lambda _seconds: None)


@pytest.fixture
def watch() -> Watch:
    return Watch(
        id="aomori_test",
        name="青森市周辺",
        checkin=date(2026, 9, 20),
        checkout=date(2026, 9, 21),
        middle_class_code="aomori",
        small_class_code="aomori",
    )


@pytest.fixture
def hotel_a() -> Hotel:
    return Hotel(hotel_no="200696", name="スローハウス青森", price=30160)


@pytest.fixture
def hotel_b() -> Hotel:
    return Hotel(hotel_no="123456", name="青森ベイサイドホテル", price=12800)


@pytest.fixture
def hotel_c() -> Hotel:
    return Hotel(hotel_no="654321", name="ホテル青森駅前", price=18500)


@pytest.fixture
def search_html() -> str:
    return (FIXTURES / "search_result.html").read_text(encoding="utf-8")
