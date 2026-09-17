"""Inline-keyboard UI for the Telegram budget actuals bot.

Deliberately free of Flask, database and network imports so the keyboard layout
and the callback parsing can be unit-tested directly. ``app.py`` renders these
structures into Telegram ``reply_markup`` payloads and executes the actions.

State is never held in memory: Cloud Run runs several stateless instances with no
sticky routing, so a request can land on a different instance than the one that
built the keyboard. The pending draft lives in the ``telegram_sessions`` table
and only ``chat_id`` is needed to resume it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

# Telegram rejects callback_data longer than 64 bytes.
MAX_CALLBACK_BYTES = 64
_CALLBACK_ENCODING = "utf-8"

# Session steps. The stored step tells the webhook how to interpret the next
# plain-text message or photo from that chat. There is deliberately no MENU step:
# the resting state is simply "no row in telegram_sessions", so the menu cannot
# leave stale state behind.
STEP_CATEGORY = "category"
STEP_ITEM = "item"
STEP_PERIOD = "period"
STEP_AMOUNT = "amount"
STEP_VOUCHER = "voucher"
STEP_CONFIRM = "confirm"

# Actions carried in callback_data. Kept short because the 64-byte budget is
# shared with the slugs that follow them.
ACTION_NAV = "nav"
ACTION_CATEGORY = "cat"
ACTION_ITEM = "item"
ACTION_PERIOD = "per"
ACTION_YEAR = "yr"
ACTION_SAVE = "save"
ACTION_SKIP = "skip"
ACTION_KEEP = "keep"
ACTION_AMOUNT = "amt"
ACTION_CANCEL = "cancel"
ACTION_CORRECTION = "cor"

NAV_MENU = "menu"
NAV_SUMMARY = "summary"
NAV_HELP = "help"
NAV_NEW = "new"


def slugify(value: str) -> str:
    """Map a display name to a stable, callback-safe token.

    ``Service/Maintenance`` -> ``service_maintenance``. Slugs keep the keyboard
    resilient to the structure being reordered, which positional indices would
    not be.
    """
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def encode_callback(*parts: object) -> str:
    """Join callback parts, refusing to exceed Telegram's 64-byte limit."""
    data = ":".join(str(part) for part in parts)
    if len(data.encode(_CALLBACK_ENCODING)) > MAX_CALLBACK_BYTES:
        raise ValueError(
            f"callback_data exceeds {MAX_CALLBACK_BYTES} bytes: {data!r}"
        )
    return data


@dataclass(frozen=True)
class Button:
    text: str
    data: str


@dataclass(frozen=True)
class Keyboard:
    """Rows of buttons, ready to be rendered into an inline keyboard."""

    rows: tuple[tuple[Button, ...], ...]

    def buttons(self) -> tuple[Button, ...]:
        return tuple(button for row in self.rows for button in row)

    def labels(self) -> tuple[str, ...]:
        return tuple(button.text for button in self.buttons())

    def find(self, data: str) -> Button | None:
        for button in self.buttons():
            if button.data == data:
                return button
        return None


@dataclass(frozen=True)
class Callback:
    """A parsed callback_data payload."""

    action: str
    category: str = ""
    item: str = ""
    value: str = ""


def parse_callback(data: str) -> Callback:
    """Parse callback_data, raising ValueError when it is not recognised."""
    if not data:
        raise ValueError("Empty callback data.")

    action, _, rest = data.partition(":")
    if not action:
        raise ValueError(f"Malformed callback data: {data!r}")

    if action == ACTION_NAV:
        if rest not in {NAV_MENU, NAV_SUMMARY, NAV_HELP, NAV_NEW}:
            raise ValueError(f"Unknown navigation target: {rest!r}")
        return Callback(action=action, value=rest)

    if action == ACTION_CATEGORY:
        if not rest:
            raise ValueError("Category callback is missing its slug.")
        return Callback(action=action, category=rest)

    if action == ACTION_ITEM:
        category, _, item = rest.partition(":")
        if not category or not item:
            raise ValueError(f"Item callback needs a category and an item: {data!r}")
        return Callback(action=action, category=category, item=item)

    if action == ACTION_PERIOD:
        year, _, month = rest.partition(":")
        if not year.isdigit() or not month.isdigit():
            raise ValueError(f"Period callback needs a year and a month: {data!r}")
        return Callback(action=action, value=f"{int(year):04d}-{int(month):02d}")

    if action == ACTION_YEAR:
        if not rest.isdigit():
            raise ValueError(f"Year callback needs a numeric year: {data!r}")
        return Callback(action=action, value=str(int(rest)))

    if action == ACTION_CORRECTION:
        if not rest:
            raise ValueError("Correction callback is missing its item slug.")
        return Callback(action=action, item=rest)

    if action == ACTION_SAVE:
        return Callback(action=action, value=rest or "save")

    if action in {ACTION_SKIP, ACTION_KEEP, ACTION_AMOUNT, ACTION_CANCEL}:
        return Callback(action=action, value=rest)

    raise ValueError(f"Unknown callback action: {action!r}")


# ----------------------------------------------------------------- lookups ----


def resolve_category(structure: dict, category_slug: str) -> str | None:
    """Return the display name of a category slug, or None when unknown."""
    for name in structure:
        if slugify(name) == category_slug:
            return name
    return None


def resolve_item(structure: dict, category_slug: str, item_slug: str) -> str | None:
    """Return the display name of an item slug within a category, or None."""
    category = resolve_category(structure, category_slug)
    if category is None:
        return None
    for item in structure[category]:
        if slugify(item) == item_slug:
            return item
    return None


def all_line_items(structure: dict) -> set[str]:
    """Flatten a category structure into the set of known line item names."""
    return {item for items in structure.values() for item in items}


# ---------------------------------------------------------------- keyboards ----


def build_main_menu() -> Keyboard:
    return Keyboard(
        rows=(
            (Button("➕ Log expense", encode_callback(ACTION_NAV, NAV_NEW)),),
            (
                Button("📊 This month", encode_callback(ACTION_NAV, NAV_SUMMARY)),
                Button("❓ Help", encode_callback(ACTION_NAV, NAV_HELP)),
            ),
        )
    )


def build_category_menu(structure: dict) -> Keyboard:
    """One button per category, two per row, plus a way back to the menu."""
    buttons = [
        Button(category, encode_callback(ACTION_CATEGORY, slugify(category)))
        for category in structure
    ]
    rows = [tuple(buttons[index : index + 2]) for index in range(0, len(buttons), 2)]
    rows.append((Button("⬅ Back", encode_callback(ACTION_NAV, NAV_MENU)),))
    return Keyboard(rows=tuple(rows))


def build_item_menu(structure: dict, category_slug: str) -> Keyboard | None:
    """One button per line item in a category, or None for an unknown category."""
    category = resolve_category(structure, category_slug)
    if category is None:
        return None

    buttons = [
        Button(item, encode_callback(ACTION_ITEM, category_slug, slugify(item)))
        for item in structure[category]
    ]
    rows = [tuple(buttons[index : index + 2]) for index in range(0, len(buttons), 2)]
    rows.append((Button("⬅ Back", encode_callback(ACTION_NAV, NAV_NEW)),))
    return Keyboard(rows=tuple(rows))


def _year_choices(today: date, span: int = 1) -> list[int]:
    return [today.year + offset for offset in range(-span, span + 1)]


MONTH_LABELS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def build_period_menu(year: int, today: date | None = None) -> Keyboard:
    """Year switcher plus a twelve-month grid, marking the current month."""
    today = today or date.today()
    rows: list[tuple[Button, ...]] = []

    year_buttons = []
    for candidate in _year_choices(today):
        label = f"· {candidate} ·" if candidate == year else str(candidate)
        year_buttons.append(Button(label, encode_callback(ACTION_YEAR, candidate)))
    rows.append(tuple(year_buttons))

    month_buttons = []
    for month in range(1, 13):
        label = f"{MONTH_LABELS[month - 1]} {year}"
        if year == today.year and month == today.month:
            label = f"• {MONTH_LABELS[month - 1]} •"
        month_buttons.append(
            Button(label, encode_callback(ACTION_PERIOD, year, f"{month:02d}"))
        )
    rows.extend(
        tuple(month_buttons[index : index + 3]) for index in range(0, 12, 3)
    )

    rows.append((Button("✖ Cancel", encode_callback(ACTION_CANCEL)),))
    return Keyboard(rows=tuple(rows))


def build_voucher_menu() -> Keyboard:
    return Keyboard(
        rows=(
            (
                Button("⏭ Skip voucher", encode_callback(ACTION_SKIP)),
                Button("✖ Cancel", encode_callback(ACTION_CANCEL)),
            ),
        )
    )


def build_confirm_menu() -> Keyboard:
    return Keyboard(
        rows=(
            (
                Button("✅ Save", encode_callback(ACTION_SAVE)),
                Button("✖ Cancel", encode_callback(ACTION_CANCEL)),
            ),
            (
                Button("💵 Change amount", encode_callback(ACTION_AMOUNT)),
                Button("📸 Replace voucher", encode_callback(ACTION_KEEP)),
            ),
        )
    )


def build_saved_menu() -> Keyboard:
    return Keyboard(
        rows=(
            (Button("➕ Log another", encode_callback(ACTION_NAV, NAV_NEW)),),
            (
                Button("📊 This month", encode_callback(ACTION_NAV, NAV_SUMMARY)),
                Button("🏠 Menu", encode_callback(ACTION_NAV, NAV_MENU)),
            ),
        )
    )


def render_inline_keyboard(keyboard: Keyboard) -> dict:
    """Render a Keyboard into the Telegram ``reply_markup`` payload."""
    return {
        "inline_keyboard": [
            [{"text": button.text, "callback_data": button.data} for button in row]
            for row in keyboard.rows
        ]
    }


def validate_keyboard(keyboard: Keyboard) -> None:
    """Raise when any callback_data would be rejected by Telegram.

    Used by tests to guarantee that every screen is sendable, including the
    longest slugs in the budget structure.
    """
    for button in keyboard.buttons():
        if len(button.data.encode(_CALLBACK_ENCODING)) > MAX_CALLBACK_BYTES:
            raise ValueError(
                f"Button {button.text!r} has oversized callback_data: {button.data!r}"
            )
        parse_callback(button.data)
