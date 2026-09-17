"""Tests for the Telegram inline-keyboard UI definitions."""

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_structure import FINANCIAL_STRUCTURE, SHARED_LINE_ITEMS
from telegram_ui import (
    ACTION_AMOUNT,
    ACTION_CANCEL,
    ACTION_CATEGORY,
    ACTION_CORRECTION,
    ACTION_ITEM,
    ACTION_KEEP,
    ACTION_PERIOD,
    ACTION_SAVE,
    ACTION_SKIP,
    ACTION_YEAR,
    MAX_CALLBACK_BYTES,
    NAV_MENU,
    NAV_NEW,
    NAV_SUMMARY,
    Keyboard,
    all_line_items,
    build_category_menu,
    build_confirm_menu,
    build_item_menu,
    build_main_menu,
    build_period_menu,
    build_saved_menu,
    build_voucher_menu,
    encode_callback,
    parse_callback,
    render_inline_keyboard,
    resolve_category,
    resolve_item,
    slugify,
    validate_keyboard,
)


def all_keyboards() -> list[Keyboard]:
    keyboards = [
        build_main_menu(),
        build_category_menu(FINANCIAL_STRUCTURE),
        build_period_menu(2026, today=date(2026, 9, 17)),
        build_voucher_menu(),
        build_confirm_menu(),
        build_saved_menu(),
    ]
    for category in FINANCIAL_STRUCTURE:
        menu = build_item_menu(FINANCIAL_STRUCTURE, slugify(category))
        assert menu is not None
        keyboards.append(menu)
    return keyboards


# ------------------------------------------------------------------ slugify ----


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Service/Maintenance", "service_maintenance"),
        ("Printing/Advertising", "printing_advertising"),
        ("Payroll & Pilotage", "payroll_pilotage"),
        ("Other Expenses", "other_expenses"),
        ("IT", "it"),
        ("Misc", "misc"),
        ("  Spaced  Name  ", "spaced_name"),
    ],
)
def test_slugify(value, expected):
    assert slugify(value) == expected


def test_slugify_is_stable_and_unique_per_structure():
    slugs = [slugify(item) for item in all_line_items(FINANCIAL_STRUCTURE)]
    assert len(slugs) == len(set(slugs)), "line item slugs collide"


# --------------------------------------------------------------- encoding ----


def test_encode_callback_accepts_values_at_the_limit():
    payload = "a" * MAX_CALLBACK_BYTES
    assert encode_callback(payload) == payload


def test_encode_callback_rejects_values_over_the_limit():
    with pytest.raises(ValueError, match="64 bytes"):
        encode_callback("a" * (MAX_CALLBACK_BYTES + 1))


# --------------------------------------------------------------- parsing ----


def test_parse_recognises_every_action():
    cases = {
        encode_callback(ACTION_CATEGORY, "fixed_costs"): (ACTION_CATEGORY, "fixed_costs", "", ""),
        encode_callback(ACTION_ITEM, "fixed_costs", "rent"): (ACTION_ITEM, "fixed_costs", "rent", ""),
        encode_callback(ACTION_PERIOD, 2026, "09"): (ACTION_PERIOD, "", "", "2026-09"),
        encode_callback(ACTION_YEAR, 2025): (ACTION_YEAR, "", "", "2025"),
        encode_callback(ACTION_SAVE): (ACTION_SAVE, "", "", "save"),
        encode_callback(ACTION_SKIP): (ACTION_SKIP, "", "", ""),
        encode_callback(ACTION_KEEP): (ACTION_KEEP, "", "", ""),
        encode_callback(ACTION_AMOUNT): (ACTION_AMOUNT, "", "", ""),
        encode_callback(ACTION_CANCEL): (ACTION_CANCEL, "", "", ""),
        encode_callback(ACTION_CORRECTION, "rent"): (ACTION_CORRECTION, "", "rent", ""),
        encode_callback("nav", NAV_MENU): ("nav", "", "", NAV_MENU),
        encode_callback("nav", NAV_SUMMARY): ("nav", "", "", NAV_SUMMARY),
        encode_callback("nav", NAV_NEW): ("nav", "", "", NAV_NEW),
    }
    for data, expected in cases.items():
        parsed = parse_callback(data)
        assert (parsed.action, parsed.category, parsed.item, parsed.value) == expected


def test_parse_normalises_period_padding():
    assert parse_callback(encode_callback(ACTION_PERIOD, 2026, "9")).value == "2026-09"


@pytest.mark.parametrize(
    "data",
    [
        "",
        "cat",
        "cat:",
        "item",
        "item:fixed_costs",
        "item::rent",
        "per:2026",
        "per:abcd:09",
        "yr:abcd",
        "nav:bogus",
        "cor:",
        "bogus:1",
    ],
)
def test_parse_rejects_malformed_payloads(data):
    with pytest.raises(ValueError):
        parse_callback(data)


# ------------------------------------------------------- structure fidelity ----


def test_every_real_line_item_is_addressable_and_resolves_back():
    """The guarantee the old bot broke: every line item can be tapped by name."""
    for category, items in FINANCIAL_STRUCTURE.items():
        for item in items:
            data = encode_callback(ACTION_ITEM, slugify(category), slugify(item))
            parsed = parse_callback(data)

            assert parsed.action == ACTION_ITEM
            assert resolve_category(FINANCIAL_STRUCTURE, parsed.category) == category
            assert resolve_item(FINANCIAL_STRUCTURE, parsed.category, parsed.item) == item


def test_resolution_returns_none_for_unknown_names():
    assert resolve_category(FINANCIAL_STRUCTURE, "payroll_pilotage_fee") is None
    assert resolve_item(FINANCIAL_STRUCTURE, "other_expenses", "maintainance") is None
    assert resolve_item(FINANCIAL_STRUCTURE, "nope", "rent") is None


def test_wrong_spellings_from_the_old_bot_are_not_resolvable():
    """Regression guard for the drift that made old actuals invisible."""
    assert resolve_item(FINANCIAL_STRUCTURE, "other_expenses", "service_maintainance") is None
    assert resolve_item(FINANCIAL_STRUCTURE, "promotion_expenses", "colletrals") is None


def test_shared_line_items_are_detected():
    assert SHARED_LINE_ITEMS == {"Misc", "Other"}


# --------------------------------------------------------------- keyboards ----


def test_all_keyboards_withstand_telegram_limits():
    for keyboard in all_keyboards():
        validate_keyboard(keyboard)
        assert keyboard.buttons(), "keyboard has no buttons"
        for row in keyboard.rows:
            assert 1 <= len(row) <= 3


def test_item_menu_returns_none_for_unknown_category():
    assert build_item_menu(FINANCIAL_STRUCTURE, "not_a_category") is None


def test_item_menu_covers_every_item_in_its_category():
    for category, items in FINANCIAL_STRUCTURE.items():
        menu = build_item_menu(FINANCIAL_STRUCTURE, slugify(category))

        for item in items:
            assert item in menu.labels()
        assert "⬅ Back" in menu.labels()


def test_category_menu_lists_every_category():
    labels = build_category_menu(FINANCIAL_STRUCTURE).labels()

    for category in FINANCIAL_STRUCTURE:
        assert category in labels
    assert "⬅ Back" in labels


def test_period_menu_marks_the_current_month_and_offers_neighbouring_years():
    menu = build_period_menu(2026, today=date(2026, 9, 17))

    assert "• Sep •" in menu.labels(), "current month is not marked"
    assert "2025" in menu.labels() and "2027" in menu.labels()

    data = [button.data for button in menu.buttons()]
    assert encode_callback(ACTION_PERIOD, 2026, "09") in data
    assert encode_callback(ACTION_YEAR, 2025) in data


def test_period_menu_does_not_mark_a_month_in_another_year():
    menu = build_period_menu(2025, today=date(2026, 9, 17))

    assert "• Sep •" not in menu.labels()
    assert "Sep 2025" in menu.labels()


def test_confirm_and_saved_menus_expose_their_actions():
    confirm = [button.data for button in build_confirm_menu().buttons()]

    assert encode_callback(ACTION_SAVE) in confirm
    assert encode_callback(ACTION_CANCEL) in confirm
    assert encode_callback(ACTION_SKIP) in [b.data for b in build_voucher_menu().buttons()]


def test_render_inline_keyboard_matches_telegram_shape():
    payload = render_inline_keyboard(build_main_menu())

    assert set(payload) == {"inline_keyboard"}
    for row in payload["inline_keyboard"]:
        for button in row:
            assert set(button) == {"text", "callback_data"}
            assert button["text"]
            assert button["callback_data"]
