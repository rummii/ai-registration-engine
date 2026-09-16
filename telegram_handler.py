"""Parsing and validation for Telegram budget actual messages."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


MESSAGE_PREFIX = "BUDGET"


class BudgetMessageError(ValueError):
    """Raised when a Telegram budget message is invalid."""


@dataclass(frozen=True)
class BudgetActualMessage:
    line_item_name: str
    fiscal_year: int
    month_index: int
    amount: Decimal


def parse_budget_message(text: str, allowed_items: set[str]) -> BudgetActualMessage:
    """Parse ``BUDGET|LineItem|YYYY|MM|Amount`` into a validated message."""
    if not isinstance(text, str):
        raise BudgetMessageError("Message text is required.")

    parts = [part.strip() for part in text.split("|")]
    if len(parts) != 5 or parts[0].upper() != MESSAGE_PREFIX:
        raise BudgetMessageError("Expected BUDGET|LineItem|YYYY|MM|Amount.")

    line_item_name = parts[1]
    if line_item_name not in allowed_items:
        raise BudgetMessageError(f"Unknown budget line item: {line_item_name}.")

    try:
        fiscal_year = int(parts[2])
        month_index = int(parts[3])
    except ValueError as exc:
        raise BudgetMessageError("Year and month must be numeric.") from exc

    if fiscal_year < 2000 or fiscal_year > 2100:
        raise BudgetMessageError("Fiscal year must be between 2000 and 2100.")
    if month_index < 1 or month_index > 12:
        raise BudgetMessageError("Month must be between 1 and 12.")

    try:
        amount = Decimal(parts[4])
    except InvalidOperation as exc:
        raise BudgetMessageError("Amount must be numeric.") from exc

    if not amount.is_finite() or amount < 0:
        raise BudgetMessageError("Amount must be a finite, non-negative number.")

    return BudgetActualMessage(
        line_item_name=line_item_name,
        fiscal_year=fiscal_year,
        month_index=month_index,
        amount=amount,
    )
