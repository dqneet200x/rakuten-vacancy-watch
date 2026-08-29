import json
from datetime import date

from rakuten_watch.state import StateStore, WatchState, touch_heartbeat


def test_round_trip(tmp_path, hotel_a):
    store = StateStore(tmp_path)
    store.save(
        WatchState(watch_id="aomori", last_count=2, hotels=[hotel_a], last_notified_hash="abc")
    )
    loaded = store.load("aomori")

    assert loaded.last_count == 2
    assert loaded.hotels[0].name == "スローハウス青森"
    assert loaded.last_notified_hash == "abc"
    assert loaded.is_baseline is False


def test_missing_file_is_baseline(tmp_path):
    assert StateStore(tmp_path).load("nothing").is_baseline is True


def test_saved_file_is_readable_json(tmp_path, hotel_a):
    store = StateStore(tmp_path)
    store.save(WatchState(watch_id="aomori", last_count=1, hotels=[hotel_a]))
    data = json.loads(store.path_for("aomori").read_text(encoding="utf-8"))
    assert data["last_count"] == 1
    assert data["hotels"][0]["hotel_no"] == "200696"


def test_state_never_contains_secrets(tmp_path, hotel_a):
    """公開リポジトリで運用するため、state に個人情報が混ざらないことを確かめる。"""
    store = StateStore(tmp_path)
    store.save(WatchState(watch_id="aomori", last_count=1, hotels=[hotel_a]))
    text = store.path_for("aomori").read_text(encoding="utf-8")
    for forbidden in ("@gmail.com", "@yahoo", "password", "applicationId"):
        assert forbidden not in text


def test_bom_file_is_readable(tmp_path, hotel_a):
    """メモ帳などで編集されて BOM が付いても読めること。"""
    store = StateStore(tmp_path)
    store.save(WatchState(watch_id="aomori", last_count=5, hotels=[hotel_a]))

    path = store.path_for("aomori")
    path.write_text("﻿" + path.read_text(encoding="utf-8"), encoding="utf-8")

    assert store.load("aomori").last_count == 5


def test_broken_file_falls_back_to_baseline(tmp_path):
    store = StateStore(tmp_path)
    store.path_for("aomori").write_text("{壊れたJSON", encoding="utf-8")
    assert store.load("aomori").is_baseline is True


def test_heartbeat_interval(tmp_path):
    path = tmp_path / "heartbeat.txt"
    assert touch_heartbeat(path, date(2026, 8, 30)) is True
    assert touch_heartbeat(path, date(2026, 9, 1)) is False   # 2日後 → まだ書かない
    assert touch_heartbeat(path, date(2026, 9, 6)) is True    # 7日後 → 書く
