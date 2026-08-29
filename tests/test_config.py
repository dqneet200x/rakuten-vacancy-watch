from datetime import date
from pathlib import Path

import pytest

from rakuten_watch.config import ConfigError, load_config

REAL_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"

BASE = """
mail:
  from_name: "テスト送信"
  send_html: false
defaults:
  adult_num: 2
  room_num: 1
  notify_on: both
watches:
  - id: aomori
    name: "青森市周辺"
    middle_class_code: aomori
    small_class_code: aomori
    checkin: "2026-09-20"
    checkout: "2026-09-21"
"""


def write(tmp_path, text, bom=False):
    path = tmp_path / "config.yaml"
    path.write_text(("﻿" if bom else "") + text, encoding="utf-8")
    return path


def test_real_config_loads():
    config = load_config(REAL_CONFIG)
    watch = config.enabled_watches[0]
    assert watch.checkin == date(2026, 9, 20)
    assert watch.checkout == date(2026, 9, 21)
    assert watch.adult_num == 2
    assert watch.room_num == 1
    assert watch.nights == 1
    assert watch.stay_label == "9/20-21"


def test_defaults_are_merged(tmp_path):
    config = load_config(write(tmp_path, BASE))
    watch = config.enabled_watches[0]
    assert watch.adult_num == 2
    assert watch.notify_on == "both"
    assert config.mail.send_html is False
    assert config.mail.from_name == "テスト送信"


def test_bom_config_loads(tmp_path):
    config = load_config(write(tmp_path, BASE, bom=True))
    assert config.enabled_watches[0].name == "青森市周辺"


def test_disabled_watch_is_skipped(tmp_path):
    config = load_config(write(tmp_path, BASE + "    enabled: false\n"))
    assert config.watches and config.enabled_watches == []


def test_invalid_date_rejected(tmp_path):
    text = BASE.replace('checkin: "2026-09-20"', 'checkin: "2026/09/20"')
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_checkout_must_be_after_checkin(tmp_path):
    text = BASE.replace('checkout: "2026-09-21"', 'checkout: "2026-09-19"')
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_invalid_notify_on_rejected(tmp_path):
    text = BASE.replace("notify_on: both", "notify_on: sometimes")
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_duplicate_ids_rejected(tmp_path):
    text = BASE + """
  - id: aomori
    name: "重複"
    checkin: "2026-09-20"
    checkout: "2026-09-21"
"""
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "no-such-file.yaml")


def test_stay_label_across_months(tmp_path):
    text = BASE.replace('checkout: "2026-09-21"', 'checkout: "2026-10-01"').replace(
        'checkin: "2026-09-20"', 'checkin: "2026-09-30"'
    )
    watch = load_config(write(tmp_path, text)).enabled_watches[0]
    assert watch.stay_label == "9/30-10/1"
