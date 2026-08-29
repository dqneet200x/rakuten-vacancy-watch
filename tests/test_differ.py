from rakuten_watch.differ import compute_diff, should_notify


def test_no_change(hotel_a):
    diff = compute_diff(1, [hotel_a], 1, [hotel_a])
    assert diff.changed is False
    assert diff.diff_text == "±0"
    assert should_notify(diff, "both", True) is False


def test_count_increase(hotel_a, hotel_b):
    diff = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    assert diff.changed is True
    assert diff.diff_value == 1
    assert diff.diff_text == "+1"
    assert diff.direction == "増加"
    assert diff.direction_mark == "▲"
    assert [h.hotel_no for h in diff.added] == ["123456"]
    assert diff.removed == []


def test_count_decrease(hotel_a, hotel_b):
    diff = compute_diff(2, [hotel_a, hotel_b], 1, [hotel_a])
    assert diff.diff_text == "-1"
    assert diff.direction == "減少"
    assert diff.direction_mark == "▼"
    assert [h.hotel_no for h in diff.removed] == ["123456"]


def test_same_count_but_hotels_swapped(hotel_a, hotel_b):
    diff = compute_diff(1, [hotel_a], 1, [hotel_b])
    assert diff.count_changed is False
    assert diff.hotels_changed is True
    assert diff.changed is True
    assert diff.direction == "入れ替わり"
    assert diff.direction_mark == "◆"


def test_notify_on_increase_only(hotel_a, hotel_b):
    increase = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    decrease = compute_diff(2, [hotel_a, hotel_b], 1, [hotel_a])
    assert should_notify(increase, "increase", True) is True
    assert should_notify(decrease, "increase", True) is False


def test_notify_on_decrease_only(hotel_a, hotel_b):
    increase = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    decrease = compute_diff(2, [hotel_a, hotel_b], 1, [hotel_a])
    assert should_notify(increase, "decrease", True) is False
    assert should_notify(decrease, "decrease", True) is True


def test_hotel_swap_can_be_ignored(hotel_a, hotel_b):
    diff = compute_diff(1, [hotel_a], 1, [hotel_b])
    assert should_notify(diff, "both", True) is True
    assert should_notify(diff, "both", False) is False


def test_sorted_by_price(hotel_a, hotel_b, hotel_c):
    diff = compute_diff(0, [], 3, [hotel_a, hotel_c, hotel_b])
    assert [h.price for h in diff.current] == [12800, 18500, 30160]
    assert diff.min_price == 12800
    assert diff.min_price_text == "12,800"


def test_content_hash_is_stable(hotel_a, hotel_b):
    first = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    second = compute_diff(1, [hotel_a], 2, [hotel_b, hotel_a])
    assert first.content_hash() == second.content_hash()


def test_content_hash_changes_with_content(hotel_a, hotel_b, hotel_c):
    first = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_b])
    second = compute_diff(1, [hotel_a], 2, [hotel_a, hotel_c])
    assert first.content_hash() != second.content_hash()
