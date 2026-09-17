"""End-to-end tests for the Telegram inline-keyboard expense flow.

Drives the real webhook with the Telegram API stubbed, so the whole path is
covered: callback_query routing, draft persistence across steps, incremental
actual updates, the ledger, idempotency and the voucher upload.
"""

import importlib
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as db_module

CHAT_ID = "12345"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"}


def send_text(client, text, *, update_id):
    return client.post(
        "/telegram/webhook",
        json={
            "update_id": update_id,
            "message": {"message_id": update_id, "chat": {"id": CHAT_ID}, "text": text},
        },
        headers=HEADERS,
    )


def send_photo(client, *, update_id):
    return client.post(
        "/telegram/webhook",
        json={
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "chat": {"id": CHAT_ID},
                "photo": [{"file_id": "small"}, {"file_id": "large"}],
            },
        },
        headers=HEADERS,
    )


def press(client, data, *, update_id):
    """Simulate tapping an inline button."""
    return client.post(
        "/telegram/webhook",
        json={
            "update_id": update_id,
            "callback_query": {
                "id": f"cb-{update_id}",
                "data": data,
                "message": {"message_id": 500, "chat": {"id": CHAT_ID}},
            },
        },
        headers=HEADERS,
    )


@pytest.fixture
def telegram_app(tmp_path, monkeypatch):
    """A reloaded app on a temp SQLite database with the Telegram API stubbed."""
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "ui.db"))
    monkeypatch.setattr(db_module, "DATABASE_URL", "")

    import app as app_module

    importlib.reload(app_module)

    calls = []

    def fake_api(method, payload, timeout=10):
        calls.append((method, payload))
        if method in {"sendMessage", "editMessageText"}:
            return {"ok": True, "result": {"message_id": 1000 + len(calls)}}
        return {"ok": True, "result": True}

    monkeypatch.setattr(app_module, "_telegram_api", fake_api)
    monkeypatch.setattr(app_module, "_download_telegram_file", lambda file_id: b"jpeg-bytes")
    monkeypatch.setattr(
        app_module.storage, "upload_voucher",
        lambda data, *, chat_id, **kw: f"vouchers/2026/09/{chat_id}.jpg",
    )

    app_module.TELEGRAM_ALLOWED_CHAT_ID = CHAT_ID
    app_module.TELEGRAM_WEBHOOK_SECRET = "webhook-secret"
    app_module.TELEGRAM_BOT_TOKEN = "test-token"

    return app_module, app_module.app.test_client(), calls


def completed_texts(calls):
    """All message bodies the bot produced, newest last."""
    texts = []
    for method, payload in calls:
        if method in {"sendMessage", "editMessageText"}:
            texts.append(payload.get("text", ""))
    return texts


def keyboard_rows(calls, *, last=True):
    """The inline keyboard from the first/last rendered message."""
    markups = [
        payload["reply_markup"]
        for method, payload in calls
        if method in {"sendMessage", "editMessageText"} and "reply_markup" in payload
    ]
    assert markups, "no keyboard was rendered"
    return markups[-1 if last else 0]["inline_keyboard"]


def actual_for(app_module, year, month, item):
    with db_module.get_db() as db:
        row = db.execute(
            """SELECT actual_amount FROM budget_actuals_cache
               WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?""",
            (year, month, item),
        ).fetchone()
    return float(row["actual_amount"]) if row else None


def ledger_rows(app_module):
    with db_module.get_db() as db:
        return db.execute("SELECT * FROM expense_transactions ORDER BY id").fetchall()


def session_for(app_module, chat_id=CHAT_ID):
    """The stored draft for a chat, or None."""
    with db_module.get_db() as db:
        row = db.execute(
            "SELECT * FROM telegram_sessions WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------- the happy path ----


def test_full_button_flow_logs_an_expense(telegram_app):
    app_module, client, calls = telegram_app
    year = date.today().year

    assert send_text(client, "/expense", update_id=1).status_code == 200
    assert "Step 1 of 4" in completed_texts(calls)[-1]
    assert [b["text"] for b in keyboard_rows(calls)[0]] == ["Other Expenses", "Promotion Expenses"]

    assert press(client, "cat:promotion_expenses", update_id=2).status_code == 200
    assert "Promotion Expenses" in completed_texts(calls)[-1]

    assert press(client, "item:promotion_expenses:marketing", update_id=3).status_code == 200
    assert "Step 3 of 4" in completed_texts(calls)[-1]

    assert press(client, f"per:{year}:09", update_id=4).status_code == 200
    assert "Send the amount" in completed_texts(calls)[-1]

    assert send_text(client, "25000", update_id=5).status_code == 200
    assert "voucher" in completed_texts(calls)[-1].lower()

    assert press(client, "skip", update_id=6).status_code == 200
    confirm = completed_texts(calls)[-1]
    assert "Confirm this expense" in confirm
    assert "25,000.00" in confirm
    assert "Marketing" in confirm

    assert press(client, "save", update_id=7).status_code == 200
    assert "Logged 25,000.00 for Marketing" in completed_texts(calls)[-1]

    rows = ledger_rows(app_module)
    assert len(rows) == 1
    assert rows[0]["line_item_name"] == "Marketing"
    assert rows[0]["category"] == "Promotion Expenses"
    assert rows[0]["amount"] == 25000.0
    assert rows[0]["month_index"] == 9
    assert rows[0]["fiscal_year"] == year
    assert rows[0]["status"] == "RECORDED"
    assert rows[0]["voucher_object"] == ""

    assert actual_for(app_module, year, 9, "Marketing") == 25000.0
    assert session_for(app_module) is None, "the draft should be cleared after saving"


def test_repeated_expenses_accumulate(telegram_app):
    """The button flow adds to the month's actual, unlike the absolute text format."""
    app_module, client, calls = telegram_app
    year = date.today().year

    def log(amount, base):
        press(client, "cat:fixed_costs", update_id=base)
        press(client, "item:fixed_costs:rent", update_id=base + 1)
        press(client, f"per:{year}:09", update_id=base + 2)
        send_text(client, amount, update_id=base + 3)
        press(client, "skip", update_id=base + 4)
        press(client, "save", update_id=base + 5)

    log("1000", 10)
    log("500.50", 20)

    assert actual_for(app_module, year, 9, "Rent") == 1500.50
    assert len(ledger_rows(app_module)) == 2
    assert "1,500.50" in completed_texts(calls)[-1]


def test_voucher_photo_is_stored_and_referenced(telegram_app):
    app_module, client, calls = telegram_app
    year = date.today().year

    press(client, "cat:other_expenses", update_id=1)
    press(client, "item:other_expenses:power", update_id=2)
    press(client, f"per:{year}:09", update_id=3)
    send_text(client, "777", update_id=4)
    send_photo(client, update_id=5)

    assert "Voucher attached" in completed_texts(calls)[-1]

    press(client, "save", update_id=6)

    rows = ledger_rows(app_module)
    assert rows[0]["voucher_object"] == f"vouchers/2026/09/{CHAT_ID}.jpg"


def test_cancelling_discards_the_draft(telegram_app):
    app_module, client, calls = telegram_app

    press(client, "cat:fixed_costs", update_id=1)
    press(client, "item:fixed_costs:tax", update_id=2)
    press(client, "cancel", update_id=3)

    assert "Draft discarded" in completed_texts(calls)[-1]
    assert session_for(app_module) is None
    assert ledger_rows(app_module) == []


def test_back_navigation_keeps_the_draft(telegram_app):
    app_module, client, calls = telegram_app

    press(client, "cat:fixed_costs", update_id=1)
    press(client, "item:fixed_costs:rent", update_id=2)
    press(client, "nav:new", update_id=3)

    assert "Step 1 of 4" in completed_texts(calls)[-1]

    draft = session_for(app_module)
    assert draft is not None
    assert draft["step"] == "category"
    assert draft["line_item_name"] == "Rent", "the chosen item should survive going back"


def test_save_is_idempotent_across_redelivery(telegram_app):
    """Telegram retries updates; the same update_id must not be counted twice."""
    app_module, client, calls = telegram_app
    year = date.today().year

    def record(update_id):
        return app_module._record_expense(
            chat_id=CHAT_ID,
            category="Fixed Costs",
            line_item_name="Rent",
            fiscal_year=year,
            month_index=9,
            amount=1000.0,
            voucher_object="",
            telegram_update_id=update_id,
        )

    first, total_after_first = record(7001)
    second, total_after_second = record(7001)

    assert first is True
    assert second is False, "the redelivery should be ignored"
    assert total_after_second == total_after_first == 1000.0
    assert len(ledger_rows(app_module)) == 1


def test_legacy_text_format_still_works(telegram_app):
    """The typed format must keep working alongside the buttons."""
    app_module, client, calls = telegram_app
    year = date.today().year

    response = send_text(client, f"BUDGET|Marketing|{year}|09|25000", update_id=1)

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "recorded": True}
    assert actual_for(app_module, year, 9, "Marketing") == 25000.0
    assert ledger_rows(app_module) == [], "the legacy path does not use the ledger"


def test_a_budget_message_is_not_parsed_as_an_amount(telegram_app):
    """A BUDGET message arriving mid-draft must not be eaten as a number."""
    app_module, client, calls = telegram_app
    year = date.today().year

    press(client, "cat:fixed_costs", update_id=1)
    press(client, "item:fixed_costs:rent", update_id=2)
    press(client, f"per:{year}:09", update_id=3)

    response = send_text(client, f"BUDGET|Marketing|{year}|09|25000", update_id=4)

    assert response.get_json() == {"ok": True, "recorded": True}
    assert session_for(app_module)["step"] == "amount", "the draft should be untouched"


# ------------------------------------------------------------ invalid input ----


def test_non_numeric_amount_is_rejected_without_advancing(telegram_app):
    app_module, client, calls = telegram_app
    year = date.today().year

    press(client, "cat:fixed_costs", update_id=1)
    press(client, "item:fixed_costs:rent", update_id=2)
    press(client, f"per:{year}:09", update_id=3)
    send_text(client, "not a number", update_id=4)

    assert "not a number" in completed_texts(calls)[-1]
    assert session_for(app_module)["step"] == "amount"
    assert ledger_rows(app_module) == []


def test_negative_and_zero_amounts_are_rejected(telegram_app):
    app_module, client, calls = telegram_app
    year = date.today().year

    press(client, "cat:fixed_costs", update_id=1)
    press(client, "item:fixed_costs:rent", update_id=2)
    press(client, f"per:{year}:09", update_id=3)

    send_text(client, "-5", update_id=4)
    assert "positive number" in completed_texts(calls)[-1]

    send_text(client, "0", update_id=5)
    assert "positive number" in completed_texts(calls)[-1]

    assert ledger_rows(app_module) == []


def test_amount_accepts_commas_and_currency_symbol(telegram_app):
    app_module, client, calls = telegram_app
    year = date.today().year

    press(client, "cat:fixed_costs", update_id=1)
    press(client, "item:fixed_costs:rent", update_id=2)
    press(client, f"per:{year}:09", update_id=3)
    send_text(client, "1,250.75", update_id=4)
    press(client, "skip", update_id=5)
    press(client, "save", update_id=6)

    assert actual_for(app_module, year, 9, "Rent") == 1250.75


def test_wrong_chat_is_rejected_for_callbacks(telegram_app):
    app_module, client, calls = telegram_app

    response = client.post(
        "/telegram/webhook",
        json={
            "update_id": 99,
            "callback_query": {
                "id": "cb-99",
                "data": "cat:fixed_costs",
                "message": {"message_id": 1, "chat": {"id": 999}},
            },
        },
        headers=HEADERS,
    )

    assert response.status_code == 403


def test_unknown_callback_data_does_not_error(telegram_app):
    app_module, client, calls = telegram_app

    response = press(client, "totally:bogus", update_id=1)

    assert response.status_code == 200
    assert "AIEX budget bot" in completed_texts(calls)[-1]


# ------------------------------------------------------------- admin views ----


def log_expense_through_ui(client, *, update_id, amount, voucher=False):
    """Walk the whole button flow once, so admin tests have real rows to show."""
    year = date.today().year
    press(client, "cat:fixed_costs", update_id=update_id)
    press(client, "item:fixed_costs:rent", update_id=update_id + 1)
    press(client, f"per:{year}:09", update_id=update_id + 2)
    send_text(client, amount, update_id=update_id + 3)
    if voucher:
        send_photo(client, update_id=update_id + 4)
    else:
        press(client, "skip", update_id=update_id + 4)
    press(client, "save", update_id=update_id + 5)
    return year


def test_budget_page_lists_telegram_expenses(telegram_app):
    app_module, client, calls = telegram_app
    year = log_expense_through_ui(client, update_id=1, amount="1234.50")

    client.set_cookie("auth_user", app_module.sign_cookie("admin"))
    page = client.get(f"/admin/budget?year={year}")

    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Telegram expenses" in body
    assert "1234.50" in body
    assert "Fixed Costs" in body


def test_budget_page_links_to_the_stored_voucher(telegram_app):
    app_module, client, calls = telegram_app
    year = log_expense_through_ui(client, update_id=1, amount="10", voucher=True)

    client.set_cookie("auth_user", app_module.sign_cookie("admin"))
    body = client.get(f"/admin/budget?year={year}").get_data(as_text=True)

    assert "View receipt" in body
    assert f"/admin/voucher/vouchers/2026/09/{CHAT_ID}.jpg" in body


def test_voucher_route_streams_the_image(telegram_app, monkeypatch):
    app_module, client, calls = telegram_app
    monkeypatch.setattr(
        app_module.storage, "download_voucher", lambda name: b"fake-image-bytes"
    )
    client.set_cookie("auth_user", app_module.sign_cookie("admin"))

    response = client.get(f"/admin/voucher/vouchers/2026/09/{CHAT_ID}.jpg")

    assert response.status_code == 200
    assert response.data == b"fake-image-bytes"
    assert response.mimetype == "image/jpeg"


def test_voucher_route_rejects_unexpected_object_names(telegram_app):
    app_module, client, calls = telegram_app
    client.set_cookie("auth_user", app_module.sign_cookie("admin"))

    for name in ["vouchers/2026/09/../../../etc/passwd", "secrets/foo.jpg", "other.jpg"]:
        assert client.get(f"/admin/voucher/{name}").status_code == 404


def test_voucher_route_requires_login(telegram_app):
    app_module, client, calls = telegram_app

    response = client.get(f"/admin/voucher/vouchers/2026/09/{CHAT_ID}.jpg")

    assert response.status_code in {302, 401}, "vouchers must not be public"


# ------------------------------------------------- update kinds and routing ----


def post_update(client, payload):
    return client.post("/telegram/webhook", json=payload, headers=HEADERS)


def test_my_chat_member_is_acknowledged_not_rejected(telegram_app):
    """Telegram must get a 200, or it retries this update forever.

    A 403 here produced a retry loop that filled the logs and left updates stuck
    in the pending queue.
    """
    app_module, client, calls = telegram_app

    response = post_update(client, {
        "update_id": 1,
        "my_chat_member": {
            "chat": {"id": int(CHAT_ID)},
            "new_chat_member": {"status": "member"},
        },
    })

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "ignored": True}


def test_update_without_a_chat_id_is_acknowledged(telegram_app):
    app_module, client, calls = telegram_app

    response = post_update(client, {"update_id": 1, "inline_query": {"id": "q"}})

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "ignored": True}


def test_my_chat_member_from_another_chat_is_still_rejected(telegram_app):
    app_module, client, calls = telegram_app

    response = post_update(client, {
        "update_id": 1,
        "my_chat_member": {"chat": {"id": 999}},
    })

    assert response.status_code == 403


def test_callback_without_a_message_falls_back_to_the_sender(telegram_app):
    """Telegram omits callback.message for keyboards on very old messages."""
    app_module, client, calls = telegram_app

    response = post_update(client, {
        "update_id": 1,
        "callback_query": {
            "id": "cb-1",
            "data": "nav:menu",
            "from": {"id": int(CHAT_ID)},
        },
    })

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_callback_with_no_chat_information_is_ignored(telegram_app):
    app_module, client, calls = telegram_app

    response = post_update(client, {
        "update_id": 1,
        "callback_query": {"id": "cb-1", "data": "nav:menu"},
    })

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "ignored": True}


def test_button_press_advances_the_flow(telegram_app):
    """Guard the exact regression that made the buttons do nothing: a callback must
    reach the handler, not just return 200."""
    app_module, client, calls = telegram_app

    press(client, "cat:promotion_expenses", update_id=1)

    assert "Promotion Expenses" in completed_texts(calls)[-1]
    assert session_for(app_module)["category"] == "Promotion Expenses"


# --------------------------------------------- update id typing (Postgres) ----
#
# Telegram sends update_id as a JSON number while the columns holding it are TEXT.
# SQLite coerces silently so these tests cannot reproduce the database error
# itself, but they do pin the normalisation that production depends on.


@pytest.mark.parametrize(
    "value,expected",
    [(12345, "12345"), ("12345", "12345"), (0, "0"), (None, None)],
)
def test_normalize_update_id(telegram_app, value, expected):
    app_module, client, calls = telegram_app

    assert app_module._normalize_update_id(value) == expected


def test_update_id_is_stored_as_text(telegram_app):
    """Regression: raw ints produced "operator does not exist: text = integer"."""
    app_module, client, calls = telegram_app

    recorded, _ = app_module._record_expense(
        chat_id=CHAT_ID,
        category="Fixed Costs",
        line_item_name="Rent",
        fiscal_year=2026,
        month_index=9,
        amount=1.0,
        voucher_object="",
        telegram_update_id=12345,  # int, exactly as Telegram delivers it
    )

    assert recorded is True
    with db_module.get_db() as db:
        row = db.execute(
            "SELECT telegram_update_id FROM expense_transactions"
        ).fetchone()
    assert row["telegram_update_id"] == "12345"


def test_int_and_text_update_ids_dedupe_identically(telegram_app):
    """A redelivery must be recognised whichever form the id arrives in."""
    app_module, client, calls = telegram_app

    def record(update_id):
        return app_module._record_expense(
            chat_id=CHAT_ID,
            category="Fixed Costs",
            line_item_name="Rent",
            fiscal_year=2026,
            month_index=9,
            amount=1.0,
            voucher_object="",
            telegram_update_id=update_id,
        )

    first, total_after_first = record(555)
    second, total_after_second = record("555")

    assert first is True
    assert second is False, "the text form of the same id must be seen as a duplicate"
    assert total_after_first == total_after_second == 1.0


def test_legacy_budget_path_also_normalises_update_ids(telegram_app):
    """The typed format shares the same id column and had the same defect."""
    app_module, client, calls = telegram_app

    response = send_text(client, "BUDGET|Marketing|2026|09|25000", update_id=4242)

    assert response.get_json() == {"ok": True, "recorded": True}
    with db_module.get_db() as db:
        row = db.execute(
            "SELECT telegram_update_id FROM budget_actuals_audit_log WHERE telegram_update_id IS NOT NULL"
        ).fetchone()
    assert row["telegram_update_id"] == "4242"


# ---------------------------------------------------- message edit fallback ----


def test_failed_edit_falls_back_to_a_new_message(telegram_app, monkeypatch):
    """Otherwise the screen silently does not change and the button looks broken."""
    app_module, client, calls = telegram_app
    calls.clear()

    def fake_api(method, payload, timeout=10):
        calls.append((method, payload))
        if method == "editMessageText":
            return {"ok": False, "description": "Bad Request: message to edit not found"}
        return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(app_module, "_telegram_api", fake_api)

    app_module._edit_telegram_message(CHAT_ID, 42, "hello", None)

    assert [method for method, _ in calls] == ["editMessageText", "sendMessage"]


def test_unmodified_edit_does_not_send_a_duplicate(telegram_app, monkeypatch):
    app_module, client, calls = telegram_app
    calls.clear()

    def fake_api(method, payload, timeout=10):
        calls.append((method, payload))
        if method == "editMessageText":
            return {"ok": False, "description": "Bad Request: message is not modified"}
        return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(app_module, "_telegram_api", fake_api)

    app_module._edit_telegram_message(CHAT_ID, 42, "hello", None)

    assert [method for method, _ in calls] == ["editMessageText"], "must not spam"
