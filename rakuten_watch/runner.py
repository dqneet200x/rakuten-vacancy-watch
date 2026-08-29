"""監視の本体。1回実行して、比較し、必要なら通知して終了する。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig, Watch
from .differ import compute_diff, should_notify
from .fetchers import fetch_with_retry
from .models import FetchError
from .notifier import Notifier, NotifyError
from .state import StateStore, WatchState, touch_heartbeat
from .templating import TemplateRenderer, build_context, now_jst
from .urls import build_search_url

logger = logging.getLogger(__name__)

# 連続でこの回数失敗したら、エラーメールを送る（5分間隔なら約1時間ぶん）。
# 一時的な通信エラーでメールが飛び続けないよう、ある程度の回数を待つ。
ERROR_MAIL_THRESHOLD = 12


@dataclass
class RunSummary:
    """実行結果のまとめ。CLI の終了コード判定に使う。"""

    checked: int = 0
    changed: int = 0
    notified: int = 0
    baselines: int = 0
    failures: int = 0
    messages: list[str] = field(default_factory=list)

    def log(self) -> None:
        logger.info(
            "実行完了: 確認=%d件 / 変化=%d件 / 通知=%d件 / 初回保存=%d件 / 失敗=%d件",
            self.checked,
            self.changed,
            self.notified,
            self.baselines,
            self.failures,
        )


class WatchRunner:
    def __init__(
        self,
        config: AppConfig,
        fetchers: list,
        notifier: Notifier,
        store: StateStore,
        renderer: TemplateRenderer,
        dry_run: bool = False,
    ):
        self.config = config
        self.fetchers = fetchers
        self.notifier = notifier
        self.store = store
        self.renderer = renderer
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    def run(self) -> RunSummary:
        summary = RunSummary()
        for watch in self.config.enabled_watches:
            logger.info("─" * 60)
            logger.info("監視条件「%s」（%s〜%s）を確認します", watch.name, watch.checkin_text, watch.checkout_text)
            self._run_one(watch, summary)
        summary.log()
        return summary

    # ------------------------------------------------------------------
    def _run_one(self, watch: Watch, summary: RunSummary) -> None:
        state = self.store.load(watch.id)
        summary.checked += 1

        try:
            result = fetch_with_retry(self.fetchers, watch)
        except FetchError as exc:
            summary.failures += 1
            self._handle_failure(watch, state, str(exc))
            return

        # 取得できたので失敗カウントをリセット
        recovered = state.consecutive_failures > 0
        state.consecutive_failures = 0
        state.last_error_mail_date = ""
        state.last_checked_at = now_jst().isoformat(timespec="seconds")
        state.source = result.source
        if recovered:
            logger.info("取得が復旧しました。")

        # 初回実行: 通知せずベースラインとして保存するだけ
        if state.is_baseline:
            state.last_count = result.count
            state.hotels = result.hotels
            state.last_change_at = state.last_checked_at
            self.store.save(state)
            summary.baselines += 1
            logger.info(
                "初回実行のため通知しません。現在の %d件 を基準として保存しました。", result.count
            )
            summary.messages.append(f"{watch.name}: 初回 {result.count}件を保存")
            return

        diff = compute_diff(state.last_count or 0, state.hotels, result.count, result.hotels)

        if not diff.changed:
            self.store.save(state)  # 最終確認日時だけ更新
            logger.info("変化なし（%d件のまま）。通知しません。", result.count)
            summary.messages.append(f"{watch.name}: 変化なし（{result.count}件）")
            return

        summary.changed += 1
        logger.info(
            "変化を検知しました: %d件 → %d件（新規%d件 / 消滅%d件）",
            diff.prev_count,
            diff.curr_count,
            len(diff.added),
            len(diff.removed),
        )

        if not should_notify(diff, watch.notify_on, watch.notify_on_hotel_change):
            state.last_count = result.count
            state.hotels = result.hotels
            state.last_change_at = state.last_checked_at
            self.store.save(state)
            logger.info("設定（notify_on=%s）により、この変化は通知しません。", watch.notify_on)
            summary.messages.append(f"{watch.name}: 変化あり（通知対象外）")
            return

        content_hash = diff.content_hash()
        if content_hash == state.last_notified_hash:
            state.last_count = result.count
            state.hotels = result.hotels
            self.store.save(state)
            logger.info("前回とまったく同じ内容のため、重複通知を抑制しました。")
            summary.messages.append(f"{watch.name}: 重複通知を抑制")
            return

        context = build_context(watch, diff, build_search_url(watch))
        subject = self.renderer.render_subject(context)
        text_body, html_body = self.renderer.render_bodies(context, self.config.mail.send_html)

        try:
            self.notifier.send(subject, text_body, html_body)
        except NotifyError as exc:
            # 送信に失敗したときは state を進めない。次回の実行で再通知される。
            summary.failures += 1
            logger.error("通知の送信に失敗しました: %s", exc)
            summary.messages.append(f"{watch.name}: 通知の送信に失敗")
            return

        state.last_count = result.count
        state.hotels = result.hotels
        state.last_notified_hash = content_hash
        state.last_change_at = state.last_checked_at
        self.store.save(state)
        summary.notified += 1
        summary.messages.append(
            f"{watch.name}: {diff.prev_count}件 → {diff.curr_count}件 を通知"
        )

    # ------------------------------------------------------------------
    def _handle_failure(self, watch: Watch, state: WatchState, message: str) -> None:
        """取得に失敗したときの処理。state（件数）は更新しない。"""
        state.consecutive_failures += 1
        state.last_checked_at = now_jst().isoformat(timespec="seconds")
        logger.error(
            "取得に失敗しました（連続%d回目）: %s", state.consecutive_failures, message
        )

        today = now_jst().date().isoformat()
        should_send = (
            state.consecutive_failures >= ERROR_MAIL_THRESHOLD
            and state.last_error_mail_date != today
        )

        if should_send:
            context = {
                "area_name": watch.name,
                "watch_id": watch.id,
                "consecutive_failures": state.consecutive_failures,
                "error_message": message,
                "now": now_jst(),
            }
            subject, body = self.renderer.render_error(context)
            try:
                self.notifier.send(subject, body)
                state.last_error_mail_date = today
            except NotifyError as exc:
                logger.error("エラー通知の送信にも失敗しました: %s", exc)
        else:
            logger.info(
                "エラーメールはまだ送りません（%d回連続で送信、1日1回まで）",
                ERROR_MAIL_THRESHOLD,
            )

        self.store.save(state)

    # ------------------------------------------------------------------
    def update_heartbeat(self, path: str | Path = "heartbeat.txt") -> bool:
        """GitHub のスケジュール自動停止（60日ルール）対策。"""
        if self.dry_run:
            return False
        updated = touch_heartbeat(path, now_jst().date())
        if updated:
            logger.info("heartbeat を更新しました（リポジトリの自動停止対策）。")
        return updated
