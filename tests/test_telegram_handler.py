"""Tests for Telegram budget message parsing and its error diagnostics."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_handler import BudgetMessageError, parse_budget_message

ALLOWED = {"Marketing", "Rent", "Power"}


def test_valid_message_parses():
    message = parse_budget_message("BUDGET|Marketing|2026|09|25000", ALLOWED)

    assert message.line_item_name == "Marketing"
    assert message.fiscal_year == 2026
    assert message.month_index == 9
    assert message.amount == Decimal("25000")


def test_prefix_is_case_insensitive_and_fields_are_trimmed():
    message = parse_budget_message("  budget | Rent | 2026 | 10 | 1500.50 ", ALLOWED)

    assert message.line_item_name == "Rent"
    assert message.month_index == 10
    assert message.amount == Decimal("1500.50")


def test_wrong_field_count_reports_the_count_and_the_message():
    with pytest.raises(BudgetMessageError) as excinfo:
        parse_budget_message("BUDGET Marketing 2026 09 25000", ALLOWED)

    detail = str(excinfo.value)
    assert "found 1" in detail
    assert "BUDGET Marketing 2026 09 25000" in detail


def test_wrong_prefix_is_reported():
    with pytest.raises(BudgetMessageError) as excinfo:
        parse_budget_message("BUDGETS|Marketing|2026|09|25000", ALLOWED)

    detail = str(excinfo.value)
    assert "must start with 'BUDGET'" in detail
    assert "BUDGETS" in detail


def test_unknown_line_item_lists_the_valid_items():
    with pytest.raises(BudgetMessageError) as excinfo:
        parse_budget_message("BUDGET|Salaries|2026|09|25000", ALLOWED)

    detail = str(excinfo.value)
    assert "Unknown budget line item: 'Salaries'" in detail
    # Sorted so the hint is stable regardless of set ordering.
    assert "Marketing, Power, Rent" in detail


def test_literal_template_placeholders_are_rejected_with_guidance():
    with pytest.raises(BudgetMessageError) as excinfo:
        parse_budget_message("BUDGET|LineItem|YYYY|MM|Amount", ALLOWED)

    assert "Unknown budget line item: 'LineItem'" in str(excinfo.value)


@pytest.mark.parametrize(
    "text",
    [
        "BUDGET|Marketing|1999|09|25000",   # year below range
        "BUDGET|Marketing|2101|09|25000",   # year above range
        "BUDGET|Marketing|2026|00|25000",   # month below range
        "BUDGET|Marketing|2026|13|25000",   # month above range
        "BUDGET|Marketing|2026|09|-5",      # negative amount
        "BUDGET|Marketing|2026|09|abc",     # non-numeric amount
        "BUDGET|Marketing|2026|09|NaN",     # non-finite amount
        "BUDGET|Marketing|twenty26|09|1",   # non-numeric year
        "",                                  # empty message
    ],
)
def test_invalid_messages_are_rejected(text):
    with pytest.raises(BudgetMessageError):
        parse_budget_message(text, ALLOWED)


def test_empty_message_reports_empty_marker():
    with pytest.raises(BudgetMessageError) as excinfo:
        parse_budget_message("", ALLOWED)

    assert "<empty>" in str(excinfo.value)


def test_long_message_is_truncated_in_the_error():
    long_text = "BUDGET|" + ("x" * 200) + "|2026|09|1"

    with pytest.raises(BudgetMessageError) as excinfo:
        parse_budget_message(long_text, ALLOWED)

    detail = str(excinfo.value)
    assert "..." in detail
    assert len(detail) < 200
