from pathlib import Path

from rakuten_watch.differ import compute_diff
from rakuten_watch.templating import TemplateRenderer, build_context
from rakuten_watch.urls import build_search_url

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def render_all(watch, diff):
    renderer = TemplateRenderer(TEMPLATES)
    context = build_context(watch, diff, build_search_url(watch))
    subject = renderer.render_subject(context)
    text, html = renderer.render_bodies(context, send_html=True)
    return subject, text, html


def test_subject_contains_counts(watch, hotel_a, hotel_b):
    diff = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    subject, _, _ = render_all(watch, diff)
    assert "▲" in subject
    assert "1件" in subject and "2件" in subject
    assert "青森市周辺" in subject
    assert "\n" not in subject  # 件名は必ず1行


def test_subject_marks_decrease(watch, hotel_a, hotel_b):
    diff = compute_diff(2, [hotel_a, hotel_b], 1, [hotel_a])
    subject, _, _ = render_all(watch, diff)
    assert "▼" in subject


def test_text_body_lists_added_hotels(watch, hotel_a, hotel_b):
    diff = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    _, text, _ = render_all(watch, diff)
    assert "青森ベイサイドホテル" in text
    assert "12,800円" in text
    assert "2026-09-20" in text
    assert "本メールは自動送信です" in text
    assert "search.travel.rakuten.co.jp" in text


def test_text_body_lists_removed_hotels(watch, hotel_a, hotel_b):
    diff = compute_diff(2, [hotel_a, hotel_b], 1, [hotel_a])
    _, text, _ = render_all(watch, diff)
    assert "空室がなくなった宿" in text
    assert "青森ベイサイドホテル" in text


def test_html_body_is_produced(watch, hotel_a, hotel_b):
    diff = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    _, _, html = render_all(watch, diff)
    assert html is not None
    assert "<a href=" in html
    assert "青森ベイサイドホテル" in html


def test_zero_hotels_renders(watch, hotel_a):
    diff = compute_diff(1, [hotel_a], 0, [])
    _, text, _ = render_all(watch, diff)
    assert "現在空室のある宿はありません" in text


def test_broken_template_falls_back(tmp_path, watch, hotel_a, hotel_b):
    (tmp_path / "subject.txt").write_text("{{ 壊れた構文 {%", encoding="utf-8")
    renderer = TemplateRenderer(tmp_path)
    diff = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    context = build_context(watch, diff, build_search_url(watch))

    subject = renderer.render_subject(context)
    assert "青森市周辺" in subject  # 予備の文面で通知は成立する


def test_error_template(watch):
    renderer = TemplateRenderer(TEMPLATES)
    from rakuten_watch.templating import now_jst

    subject, body = renderer.render_error(
        {
            "area_name": watch.name,
            "watch_id": watch.id,
            "consecutive_failures": 6,
            "error_message": "接続がタイムアウトしました",
            "now": now_jst(),
        }
    )
    assert "青森市周辺" in subject
    assert "取得エラー" in subject
    assert "6" in body and "回連続" in body
    assert "接続がタイムアウトしました" in body
