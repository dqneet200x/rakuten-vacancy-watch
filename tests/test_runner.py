from pathlib import Path

import pytest

from rakuten_watch.config import AppConfig, MailConfig
from rakuten_watch.models import FetchError, FetchResult
from rakuten_watch.notifier import Notifier, NotifyError
from rakuten_watch.runner import ERROR_MAIL_THRESHOLD, WatchRunner
from rakuten_watch.state import StateStore
from rakuten_watch.templating import TemplateRenderer

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


class RecordingNotifier(Notifier):
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def send(self, subject, text_body, html_body=None):
        if self.fail:
            raise NotifyError("送信できません（テスト）")
        self.sent.append((subject, text_body))


class ScriptedFetcher:
    name = "test"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def fetch(self, watch):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_runner(tmp_path, watch, outcomes, notifier=None, dry_run=False):
    config = AppConfig(mail=MailConfig(send_html=False), watches=[watch])
    return WatchRunner(
        config=config,
        fetchers=[ScriptedFetcher(outcomes)],
        notifier=notifier or RecordingNotifier(),
        store=StateStore(tmp_path / "state"),
        renderer=TemplateRenderer(TEMPLATES),
        dry_run=dry_run,
    )


# --- 初回実行 --------------------------------------------------------------
def test_first_run_saves_baseline_without_mail(tmp_path, watch, hotel_a):
    notifier = RecordingNotifier()
    runner = make_runner(tmp_path, watch, [FetchResult(1, [hotel_a], "test")], notifier)
    summary = runner.run()

    assert summary.baselines == 1
    assert summary.notified == 0
    assert notifier.sent == []

    state = StateStore(tmp_path / "state").load(watch.id)
    assert state.last_count == 1
    assert [h.hotel_no for h in state.hotels] == ["200696"]


# --- 変化なし --------------------------------------------------------------
def test_no_change_sends_nothing(tmp_path, watch, hotel_a):
    notifier = RecordingNotifier()
    runner = make_runner(
        tmp_path,
        watch,
        [FetchResult(1, [hotel_a], "test"), FetchResult(1, [hotel_a], "test")],
        notifier,
    )
    runner.run()  # 初回（ベースライン）
    summary = runner.run()  # 2回目

    assert summary.changed == 0
    assert notifier.sent == []


# --- 変化あり --------------------------------------------------------------
def test_change_sends_mail(tmp_path, watch, hotel_a, hotel_b):
    notifier = RecordingNotifier()
    runner = make_runner(
        tmp_path,
        watch,
        [FetchResult(1, [hotel_a], "test"), FetchResult(2, [hotel_a, hotel_b], "test")],
        notifier,
    )
    runner.run()
    summary = runner.run()

    assert summary.notified == 1
    assert len(notifier.sent) == 1
    subject, body = notifier.sent[0]
    assert "1件" in subject and "2件" in subject
    assert "青森ベイサイドホテル" in body

    state = StateStore(tmp_path / "state").load(watch.id)
    assert state.last_count == 2
    assert state.last_notified_hash != ""


# --- 重複通知の抑制 --------------------------------------------------------
def test_duplicate_notification_is_suppressed(tmp_path, watch, hotel_a, hotel_b):
    notifier = RecordingNotifier()
    store = StateStore(tmp_path / "state")
    runner = make_runner(
        tmp_path,
        watch,
        [
            FetchResult(1, [hotel_a], "test"),
            FetchResult(2, [hotel_a, hotel_b], "test"),
        ],
        notifier,
    )
    runner.run()
    runner.run()
    assert len(notifier.sent) == 1

    # state を巻き戻して、まったく同じ変化がもう一度起きた状況を作る
    state = store.load(watch.id)
    state.last_count = 1
    state.hotels = [hotel_a]
    store.save(state)

    runner.fetchers = [ScriptedFetcher([FetchResult(2, [hotel_a, hotel_b], "test")])]
    runner.run()
    assert len(notifier.sent) == 1  # 増えていない


# --- notify_on フィルタ ----------------------------------------------------
def test_decrease_is_skipped_when_increase_only(tmp_path, watch, hotel_a, hotel_b):
    watch.notify_on = "increase"
    notifier = RecordingNotifier()
    runner = make_runner(
        tmp_path,
        watch,
        [FetchResult(2, [hotel_a, hotel_b], "test"), FetchResult(1, [hotel_a], "test")],
        notifier,
    )
    runner.run()
    summary = runner.run()

    assert summary.changed == 1
    assert summary.notified == 0
    assert notifier.sent == []
    # 通知しなくても件数は更新しておく（次の増加を正しく検知するため）
    assert StateStore(tmp_path / "state").load(watch.id).last_count == 1


# --- 送信失敗時は state を進めない ----------------------------------------
def test_state_not_advanced_when_mail_fails(tmp_path, watch, hotel_a, hotel_b):
    ok_notifier = RecordingNotifier()
    runner = make_runner(tmp_path, watch, [FetchResult(1, [hotel_a], "test")], ok_notifier)
    runner.run()

    failing = RecordingNotifier(fail=True)
    runner.notifier = failing
    runner.fetchers = [ScriptedFetcher([FetchResult(2, [hotel_a, hotel_b], "test")])]
    runner.run()

    state = StateStore(tmp_path / "state").load(watch.id)
    assert state.last_count == 1  # まだ 1件のまま

    # 次の実行でちゃんと再通知される
    runner.notifier = ok_notifier
    runner.fetchers = [ScriptedFetcher([FetchResult(2, [hotel_a, hotel_b], "test")])]
    runner.run()
    assert len(ok_notifier.sent) == 1
    assert StateStore(tmp_path / "state").load(watch.id).last_count == 2


# --- 取得失敗 --------------------------------------------------------------
def test_single_failure_sends_no_mail(tmp_path, watch, hotel_a):
    notifier = RecordingNotifier()
    runner = make_runner(tmp_path, watch, [FetchResult(1, [hotel_a], "test")], notifier)
    runner.run()

    runner.fetchers = [ScriptedFetcher([FetchError("接続失敗")] * 3)]
    summary = runner.run()

    assert summary.failures == 1
    assert notifier.sent == []
    state = StateStore(tmp_path / "state").load(watch.id)
    assert state.consecutive_failures == 1
    assert state.last_count == 1  # 件数は保持されたまま


def test_error_mail_after_threshold(tmp_path, watch, hotel_a):
    notifier = RecordingNotifier()
    store = StateStore(tmp_path / "state")
    runner = make_runner(tmp_path, watch, [FetchResult(1, [hotel_a], "test")], notifier)
    runner.run()

    for _ in range(ERROR_MAIL_THRESHOLD):
        runner.fetchers = [ScriptedFetcher([FetchError("接続失敗")] * 3)]
        runner.run()

    assert len(notifier.sent) == 1
    assert "取得エラー" in notifier.sent[0][0]

    # 同じ日のうちは2通目を送らない
    runner.fetchers = [ScriptedFetcher([FetchError("接続失敗")] * 3)]
    runner.run()
    assert len(notifier.sent) == 1


def test_recovery_resets_failure_count(tmp_path, watch, hotel_a):
    store = StateStore(tmp_path / "state")
    runner = make_runner(tmp_path, watch, [FetchResult(1, [hotel_a], "test")])
    runner.run()

    runner.fetchers = [ScriptedFetcher([FetchError("失敗")] * 3)]
    runner.run()
    assert store.load(watch.id).consecutive_failures == 1

    runner.fetchers = [ScriptedFetcher([FetchResult(1, [hotel_a], "test")])]
    runner.run()
    assert store.load(watch.id).consecutive_failures == 0


# --- heartbeat -------------------------------------------------------------
def test_heartbeat_written_once_per_week(tmp_path, watch, hotel_a):
    runner = make_runner(tmp_path, watch, [FetchResult(1, [hotel_a], "test")])
    path = tmp_path / "heartbeat.txt"
    assert runner.update_heartbeat(path) is True
    assert runner.update_heartbeat(path) is False  # 同じ週は書き換えない
