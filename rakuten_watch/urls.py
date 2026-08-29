"""楽天トラベルの検索URLを組み立てる。"""

from __future__ import annotations

from urllib.parse import urlencode

from .config import Watch

SEARCH_ENDPOINT = "https://search.travel.rakuten.co.jp/ds/vacant/searchVacant"


def build_search_url(watch: Watch, page: int = 1) -> str:
    """監視条件から、人が見るための楽天トラベル検索URLを組み立てる。

    メール本文のリンクと、HTML取得方式の両方で使う。
    パラメータ名は楽天トラベルの検索画面のものに合わせている。
    """
    params = {
        "f_cd": "03",
        "f_dai": watch.large_class_code,
        "f_chu": watch.middle_class_code,
        "f_shou": watch.small_class_code,
        "f_sai": watch.detail_class_code,
        "f_nen1": watch.checkin.year,
        "f_tuki1": watch.checkin.month,
        "f_hi1": watch.checkin.day,
        "f_nen2": watch.checkout.year,
        "f_tuki2": watch.checkout.month,
        "f_hi2": watch.checkout.day,
        "f_otona_su": watch.adult_num,
        "f_s1": 0,
        "f_s2": 0,
        "f_y1": 0,
        "f_y2": 0,
        "f_y3": 0,
        "f_y4": 0,
        "f_heya_su": watch.room_num,
        "f_hyoji": 30,
        "f_teikei": "quick",
        "f_sort": "hotel",
        "f_tab": "hotel",
    }
    if page > 1:
        params["f_next"] = (page - 1) * 30
    return f"{SEARCH_ENDPOINT}?{urlencode(params)}"
