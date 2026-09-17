import os
import hmac
import html
import hashlib
import json
from urllib import request as url_request
from urllib.error import URLError
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from flask import Flask, request, redirect, url_for, render_template, session, flash, g, jsonify, abort, Response
from functools import wraps
from config import (
    SECRET_KEY,
    COOKIE_SECRET,
    IS_PRODUCTION,
    MAX_CONTENT_LENGTH,
    BRUTE_FORCE_LIMIT,
    LOCKOUT_MINUTES,
    SESSION_HOURS,
    TELEGRAM_ALLOWED_CHAT_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_WEBHOOK_SECRET,
    MAX_VOUCHER_BYTES,
)
from db import get_db, hash_password, init_db, migrate_price_data
from telegram_handler import BudgetMessageError, parse_budget_message
from budget_structure import FINANCIAL_STRUCTURE, MONTHS
import storage
from telegram_ui import (
    ACTION_AMOUNT,
    ACTION_CANCEL,
    ACTION_CATEGORY,
    ACTION_CORRECTION,
    ACTION_ITEM,
    ACTION_KEEP,
    ACTION_NAV,
    ACTION_PERIOD,
    ACTION_SAVE,
    ACTION_SKIP,
    ACTION_YEAR,
    NAV_HELP,
    NAV_MENU,
    NAV_NEW,
    NAV_SUMMARY,
    STEP_AMOUNT,
    STEP_CATEGORY,
    STEP_CONFIRM,
    STEP_ITEM,
    STEP_PERIOD,
    STEP_VOUCHER,
    build_category_menu,
    build_confirm_menu,
    build_item_menu,
    build_main_menu,
    build_period_menu,
    build_saved_menu,
    build_voucher_menu,
    parse_callback,
    render_inline_keyboard,
    resolve_category,
    resolve_item,
    slugify,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"), static_folder=os.path.join(BASE_DIR, "static"))
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Initialize database
with app.app_context():
    init_db()
    migrate_price_data()

# --- Authentication Helpers ---

def sign_cookie(username: str) -> str:
    """Create HMAC-signed session cookie"""
    timestamp = str(int(datetime.utcnow().timestamp()))
    payload = f"{username}|{timestamp}".encode('utf-8')
    sig = hmac.new(COOKIE_SECRET.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return f"{username}|{timestamp}|{sig}"

def verify_cookie(cookie_value: str) -> str:
    """Verify HMAC-signed cookie and return username if valid"""
    if not cookie_value:
        return None
    try:
        parts = cookie_value.split('|')
        if len(parts) != 3:
            return None
        username, timestamp, sig = parts
        payload = f"{username}|{timestamp}".encode('utf-8')
        expected_sig = hmac.new(COOKIE_SECRET.encode('utf-8'), payload, hashlib.sha256).hexdigest()

        if hmac.compare_digest(sig, expected_sig):
            age = datetime.utcnow().timestamp() - float(timestamp)
            if age < (SESSION_HOURS * 3600):
                return username
    except Exception:
        pass
    return None

def get_current_user():
    """Get current authenticated user from session cookie"""
    cookie = request.cookies.get('auth_user')
    username = verify_cookie(cookie)
    if not username:
        return None
    
    db = get_db()
    user = db.execute("SELECT username, role FROM system_users WHERE username = ?", (username,)).fetchone()
    db.close()
    return user

def login_required(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def superadmin_required(f):
    """Decorator to require SUPERADMIN role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or user['role'] != 'SUPERADMIN':
            flash('Access denied. SUPERADMIN privileges required.', 'error')
            return redirect(url_for('admin_dashboard'))
        return f(*args, **kwargs)
    return decorated

# --- Screener Logic ---

def run_screener_assessment(a1: str, a2: str):
    """Assess application quality based on answers"""
    combined = (a1 + " " + a2).lower()
    score = 0
    
    if len(a1) > 15: score += 2
    if len(a2) > 10: score += 1
    if len(a1) > 40: score += 2
    
    keywords = ["business", "freelance", "client", "agency", "marketing", "student", 
                "shop", "store", "crm", "funnel", "sale", "lead", "workflow", "process", "service"]
    found_keywords = [kw for kw in keywords if kw in combined]
    score += len(found_keywords) * 2
    
    if len(a1) < 6 or "test" in combined or "dont know" in combined or a1.strip().lower() == "na":
        return "REJECT RECOMMENDATION", "Answers contain insufficient operational substance or placeholder text patterns."
    
    if score >= 5:
        return "ACCEPT RECOMMENDATION", f"Strong use-case profile match. Found targeted framework concepts: {', '.join(found_keywords[:3])}."
    
    return "REJECT RECOMMENDATION", "Low actionable use-case mapping. Content seems general or passive."

# --- Health and Public Routes ---

@app.route('/health')
def health_check():
    return jsonify({"status": "ok", "service": "ai-registration-engine"})


def _telegram_api(method, payload, *, timeout=10):
    """POST to the Telegram Bot API, returning the decoded body or None."""
    if not TELEGRAM_BOT_TOKEN:
        return None

    body = json.dumps(payload).encode("utf-8")
    telegram_request = url_request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with url_request.urlopen(telegram_request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError):
        app.logger.exception("Telegram API call %s failed", method)
        return None


def _send_telegram_message(chat_id, text, reply_markup=None):
    """Send a message, optionally with an inline keyboard.

    Returns the new message id so flows can edit it in place later.
    """
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    result = _telegram_api("sendMessage", payload)
    if result and result.get("ok"):
        return result["result"].get("message_id")
    return None


def _edit_telegram_message(chat_id, message_id, text, reply_markup=None):
    """Replace a message in place so keyboards update instead of stacking up."""
    if not message_id:
        return _send_telegram_message(chat_id, text, reply_markup)

    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _telegram_api("editMessageText", payload)


def _answer_callback_query(callback_id, text=None):
    """Acknowledge a button press.

    Telegram shows a spinner on the button until this is called, and retries the
    delivery if the webhook is slow, so it runs before any real work.
    """
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    _telegram_api("answerCallbackQuery", payload)


def _download_telegram_file(file_id):
    """Fetch a Telegram file into memory, or None when unavailable."""
    if not TELEGRAM_BOT_TOKEN:
        return None

    info = _telegram_api("getFile", {"file_id": file_id})
    if not info or not info.get("ok"):
        return None

    file_path = (info.get("result") or {}).get("file_path")
    if not file_path:
        return None

    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    try:
        with url_request.urlopen(url, timeout=30) as response:
            data = response.read(MAX_VOUCHER_BYTES + 1)
    except (OSError, URLError):
        app.logger.exception("Unable to download the Telegram voucher")
        return None

    if len(data) > MAX_VOUCHER_BYTES:
        app.logger.warning("Telegram voucher exceeded the size limit")
        return None
    return data


def _budget_line_items():
    return {
        item
        for items in FINANCIAL_STRUCTURE.values()
        for item in items
    }


# --- Telegram interactive UI state ---
#
# Cloud Run runs several stateless instances with no sticky routing, so a button
# press can land on a different instance than the one that drew the keyboard. The
# in-progress draft therefore lives in telegram_sessions, keyed by chat_id;
# keeping it in memory would lose the user's place between taps.


def _load_session(db, chat_id):
    """Return the pending draft for a chat, or None."""
    row = db.execute(
        "SELECT * FROM telegram_sessions WHERE chat_id = ?", (str(chat_id),)
    ).fetchone()
    return dict(row) if row else None


def _save_session(db, chat_id, step, *, category="", line_item_name="",
                  fiscal_year=None, month_index=None, amount=None,
                  voucher_object="", prompt_message_id=None):
    """Replace the draft for a chat.

    Delete-then-insert keeps this portable: SQLite and PostgreSQL disagree on
    UPSERT syntax and the DBAdapter only translates the common cases.
    """
    db.execute("DELETE FROM telegram_sessions WHERE chat_id = ?", (str(chat_id),))
    db.execute(
        """INSERT INTO telegram_sessions
           (chat_id, step, category, line_item_name, fiscal_year, month_index,
            amount, voucher_object, prompt_message_id, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(chat_id), step, category or "", line_item_name or "",
            fiscal_year, month_index, amount, voucher_object or "",
            str(prompt_message_id) if prompt_message_id else None,
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()


def _clear_session(db, chat_id):
    db.execute("DELETE FROM telegram_sessions WHERE chat_id = ?", (str(chat_id),))
    db.commit()


def _show(chat_id, message_id, text, keyboard):
    """Render a screen, editing the existing message when we have its id."""
    markup = render_inline_keyboard(keyboard)
    if message_id:
        return _edit_telegram_message(chat_id, message_id, text, markup)
    return _send_telegram_message(chat_id, text, markup)


def _increment_actual(db, fiscal_year, month_index, line_item_name, amount):
    """Add to the cached monthly actual, creating the row when it is missing.

    Upsert rather than insert-then-update: the budget page only seeds rows for
    the year being viewed, so a month in any other year has no row yet. The two
    backends need different conflict syntax, hence the branch.
    """
    if getattr(db, "postgres", False):
        db.execute(
            """INSERT INTO budget_actuals_cache
               (fiscal_year, month_index, line_item_name, actual_amount)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (fiscal_year, month_index, line_item_name)
               DO UPDATE SET actual_amount =
                   budget_actuals_cache.actual_amount + EXCLUDED.actual_amount""",
            (fiscal_year, month_index, line_item_name, amount),
        )
    else:
        db.execute(
            """INSERT INTO budget_actuals_cache
               (fiscal_year, month_index, line_item_name, actual_amount)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (fiscal_year, month_index, line_item_name)
               DO UPDATE SET actual_amount = actual_amount + excluded.actual_amount""",
            (fiscal_year, month_index, line_item_name, amount),
        )


def _current_actual(db, fiscal_year, month_index, line_item_name):
    row = db.execute(
        """SELECT actual_amount FROM budget_actuals_cache
           WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?""",
        (fiscal_year, month_index, line_item_name),
    ).fetchone()
    return float(row["actual_amount"]) if row else 0.0


def _record_expense(*, chat_id, category, line_item_name, fiscal_year, month_index,
                    amount, voucher_object, telegram_update_id):
    """Log an expense and add it to the month's actual.

    Returns (recorded, running_total). recorded is False when Telegram redelivered
    an update that was already applied, which is what the unique
    telegram_update_id on the ledger is for.
    """
    db = get_db()
    try:
        if telegram_update_id:
            duplicate = db.execute(
                "SELECT id FROM expense_transactions WHERE telegram_update_id = ?",
                (telegram_update_id,),
            ).fetchone()
            if duplicate:
                return False, _current_actual(
                    db, fiscal_year, month_index, line_item_name
                )

        _increment_actual(db, fiscal_year, month_index, line_item_name, amount)
        running_total = _current_actual(db, fiscal_year, month_index, line_item_name)
        now = datetime.utcnow().isoformat()
        detail = f"Expense logged from the Telegram UI ({category or 'uncategorised'})."

        db.execute(
            """INSERT INTO expense_transactions
               (telegram_update_id, timestamp, chat_id, category, line_item_name,
                fiscal_year, month_index, amount, running_total, voucher_object,
                status, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                telegram_update_id, now, str(chat_id), category or "",
                line_item_name, fiscal_year, month_index, amount, running_total,
                voucher_object or "", "RECORDED", detail,
            ),
        )
        # Mirror into the budget audit trail so the budget page reports Telegram
        # activity and its "actuals live" badge stays accurate.
        db.execute(
            """INSERT INTO budget_actuals_audit_log
               (telegram_update_id, timestamp, chat_id, message_id, fiscal_year,
                month_index, line_item_name, amount, status, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                telegram_update_id, now, str(chat_id), None, fiscal_year,
                month_index, line_item_name, amount, "RECORDED", detail,
            ),
        )
        db.commit()
        return True, running_total
    finally:
        db.close()


def _month_expense_total(db, fiscal_year, month_index):
    """Sum the ledger for a month so the summary reflects what was logged."""
    row = db.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total FROM expense_transactions
           WHERE fiscal_year = ? AND month_index = ? AND status = 'RECORDED'""",
        (fiscal_year, month_index),
    ).fetchone()
    return float(row["total"]) if row and row["total"] is not None else 0.0


def _record_budget_actual(message, *, chat_id, telegram_update_id, telegram_message_id):
    db = get_db()
    try:
        if telegram_update_id:
            duplicate = db.execute(
                "SELECT id FROM budget_actuals_audit_log WHERE telegram_update_id = ?",
                (telegram_update_id,),
            ).fetchone()
            if duplicate:
                return False

        update_cursor = db.execute(
            "UPDATE budget_actuals_cache SET actual_amount = ? WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?",
            (float(message.amount), message.fiscal_year, message.month_index, message.line_item_name),
        )
        if update_cursor.rowcount == 0:
            db.execute(
                "INSERT INTO budget_actuals_cache (fiscal_year, month_index, line_item_name, actual_amount) VALUES (?, ?, ?, ?)",
                (message.fiscal_year, message.month_index, message.line_item_name, float(message.amount)),
            )

        db.execute(
            "INSERT INTO budget_actuals_audit_log (telegram_update_id, timestamp, chat_id, message_id, fiscal_year, month_index, line_item_name, amount, status, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                telegram_update_id,
                datetime.utcnow().isoformat(),
                str(chat_id),
                str(telegram_message_id) if telegram_message_id else None,
                message.fiscal_year,
                message.month_index,
                message.line_item_name,
                float(message.amount),
                "RECORDED",
                "Budget actual recorded from Telegram.",
            ),
        )
        db.commit()
        return True
    finally:
        db.close()


# --- Telegram UI screens ---


def _set_step(chat_id, step, *, message_id=None, **overrides):
    """Advance the draft to a new step, carrying existing fields forward.

    Every screen goes through here so a partially filled draft is never lost when
    the user jumps back or re-enters an amount.
    """
    db = get_db()
    try:
        current = _load_session(db, chat_id) or {}
        fields = {
            "category": current.get("category") or "",
            "line_item_name": current.get("line_item_name") or "",
            "fiscal_year": current.get("fiscal_year"),
            "month_index": current.get("month_index"),
            "amount": current.get("amount"),
            "voucher_object": current.get("voucher_object") or "",
            "prompt_message_id": current.get("prompt_message_id"),
        }
        fields.update(overrides)
        if message_id:
            fields["prompt_message_id"] = str(message_id)
        _save_session(db, chat_id, step, **fields)
    finally:
        db.close()


def _ui_menu(chat_id, *, message_id=None, text=None):
    # No session write: the menu is the resting state, and persisting it would
    # mean cancelling recreated a row instead of discarding the draft.
    _show(
        chat_id,
        message_id,
        text or (
            "🏠 AIEX budget bot\n\n"
            "Log an expense using the buttons below — you never have to type a "
            "line item name."
        ),
        build_main_menu(),
    )


def _ui_categories(chat_id, *, message_id=None):
    _set_step(chat_id, STEP_CATEGORY, message_id=message_id)
    _show(
        chat_id,
        message_id,
        "Step 1 of 4 · Select a category:",
        build_category_menu(FINANCIAL_STRUCTURE),
    )


def _ui_items(chat_id, category_slug, *, message_id=None):
    keyboard = build_item_menu(FINANCIAL_STRUCTURE, category_slug)
    category = resolve_category(FINANCIAL_STRUCTURE, category_slug)

    if keyboard is None or category is None:
        # The structure changed under a stale keyboard; recover instead of erroring.
        _ui_categories(chat_id, message_id=message_id)
        return

    _set_step(chat_id, STEP_ITEM, message_id=message_id, category=category)
    _show(
        chat_id,
        message_id,
        f"Step 2 of 4 · {category}\n\nSelect the line item:",
        keyboard,
    )


def _ui_periods(chat_id, *, year=None, message_id=None):
    db = get_db()
    try:
        session = _load_session(db, chat_id) or {}
    finally:
        db.close()

    category = session.get("category") or ""
    item = session.get("line_item_name") or ""
    if not category or not item:
        _ui_categories(chat_id, message_id=message_id)
        return

    year = year or session.get("fiscal_year") or datetime.now().year
    _set_step(chat_id, STEP_PERIOD, message_id=message_id, fiscal_year=year)
    _show(
        chat_id,
        message_id,
        f"Step 3 of 4 · {item} ({category})\n\nSelect the month:",
        build_period_menu(year),
    )


def _session(chat_id):
    """Load the current draft as a plain dict."""
    db = get_db()
    try:
        return _load_session(db, chat_id) or {}
    finally:
        db.close()


def _describe_draft(session):
    """One-line description of a draft, used in prompts and the confirmation."""
    item = session.get("line_item_name") or "?"
    category = session.get("category") or ""
    year = session.get("fiscal_year")
    month = session.get("month_index")
    period = f"{MONTHS[int(month) - 1]} {year}" if month and year else "?"
    return f"{item} · {period}" + (f"  ({category})" if category else "")


def _ui_prompt_amount(chat_id, *, note=None):
    session = _session(chat_id)
    if not session.get("line_item_name") or not session.get("month_index"):
        _ui_categories(chat_id)
        return

    prefix = f"{note}\n\n" if note else ""
    sent = _send_telegram_message(
        chat_id,
        f"{prefix}Step 4 of 4 · {_describe_draft(session)}\n\n"
        "Send the amount as a plain number, for example 25000 or 1500.50.",
    )
    _set_step(chat_id, STEP_AMOUNT, message_id=sent)


def _ui_prompt_voucher(chat_id, *, note=None):
    session = _session(chat_id)
    prefix = f"{note}\n\n" if note else ""
    sent = _send_telegram_message(
        chat_id,
        f"{prefix}📸 Send the receipt or voucher photo for {_describe_draft(session)}, "
        "or tap Skip.",
        render_inline_keyboard(build_voucher_menu()),
    )
    _set_step(chat_id, STEP_VOUCHER, message_id=sent)


def _ui_confirm(chat_id, *, note=None):
    session = _session(chat_id)
    amount = session.get("amount")
    if amount is None:
        _ui_prompt_amount(chat_id)
        return

    voucher = session.get("voucher_object") or ""
    prefix = f"{note}\n\n" if note else ""
    sent = _send_telegram_message(
        chat_id,
        f"{prefix}Confirm this expense:\n\n"
        f"  Line item: {session.get('line_item_name') or '?'}\n"
        f"  Category:  {session.get('category') or '-'}\n"
        f"  Period:    {_describe_draft(session).split('· ')[-1].split('  ')[0]}\n"
        f"  Amount:    {float(amount):,.2f}\n"
        f"  Voucher:   {'attached' if voucher else 'none'}\n\n"
        "Saving adds this amount to the month's actual.",
        render_inline_keyboard(build_confirm_menu()),
    )
    _set_step(chat_id, STEP_CONFIRM, message_id=sent)


def _ui_help(chat_id, *, message_id=None):
    _show(
        chat_id,
        message_id,
        "❓ How this works\n\n"
        "➕ Log expense — pick a category, a line item and a month, then send the "
        "amount and optionally a voucher photo. Each entry is added to that "
        "month's actual total.\n\n"
        "Text shortcuts still work if you prefer typing:\n"
        "  BUDGET|LineItem|YYYY|MM|Amount  (sets the actual)\n"
        "  /expense  open the button flow\n"
        "  /summary  this month's totals\n"
        "  /cancel   discard the current draft\n\n"
        "Commands: /start  /expense  /summary  /help  /cancel",
        build_main_menu(),
    )


def _ui_cancel(chat_id, *, message_id=None):
    db = get_db()
    try:
        _clear_session(db, chat_id)
    finally:
        db.close()
    _ui_menu(chat_id, message_id=message_id, text="Draft discarded. Nothing was saved.")


def _ui_summary(chat_id, *, message_id=None):
    now = datetime.now()
    year, month = now.year, now.month
    db = get_db()
    try:
        total = _month_expense_total(db, year, month)
        rows = db.execute(
            """SELECT line_item_name, COALESCE(SUM(amount), 0) AS total
               FROM expense_transactions
               WHERE fiscal_year = ? AND month_index = ? AND status = 'RECORDED'
               GROUP BY line_item_name
               ORDER BY line_item_name""",
            (year, month),
        ).fetchall()
    finally:
        db.close()

    label = f"{MONTHS[month - 1]} {year}"
    if not rows:
        body = f"📊 {label}\n\nNo expenses logged this month yet."
    else:
        lines = [f"  {row['line_item_name']}: {float(row['total']):,.2f}" for row in rows]
        body = f"📊 {label}\n\n" + "\n".join(lines) + f"\n\nTotal: {total:,.2f}"

    _show(chat_id, message_id, body, build_main_menu())


# --- Telegram UI input handlers ---


def _ui_save(chat_id, *, update_id):
    """Commit the draft, add it to the month's actual, and show a receipt."""
    session = _session(chat_id)
    item = session.get("line_item_name")
    year = session.get("fiscal_year")
    month = session.get("month_index")
    amount = session.get("amount")

    if not item or not year or not month or amount is None:
        _clear_session_safe(chat_id)
        _ui_menu(chat_id, text="That draft was incomplete, so nothing was saved.")
        return

    recorded, running_total = _record_expense(
        chat_id=chat_id,
        category=session.get("category") or "",
        line_item_name=item,
        fiscal_year=int(year),
        month_index=int(month),
        amount=float(amount),
        voucher_object=session.get("voucher_object") or "",
        telegram_update_id=update_id,
    )
    _clear_session_safe(chat_id)

    if recorded:
        body = (
            f"✅ Logged {float(amount):,.2f} for {item}\n"
            f"{MONTHS[int(month) - 1]} {year} total is now {running_total:,.2f}."
        )
    else:
        body = (
            "ℹ️ Telegram redelivered that update and it was already saved, "
            "so nothing was added twice."
        )

    _send_telegram_message(chat_id, body, render_inline_keyboard(build_saved_menu()))


def _clear_session_safe(chat_id):
    db = get_db()
    try:
        _clear_session(db, chat_id)
    finally:
        db.close()


def _handle_amount(chat_id, text):
    """Treat a plain-text message as the amount for the current draft."""
    try:
        amount = Decimal(text.replace(",", "").replace("₱", "").strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        _ui_prompt_amount(chat_id, note="That is not a number. Try 25000 or 1500.50.")
        return

    if not amount.is_finite() or amount <= 0:
        _ui_prompt_amount(chat_id, note="The amount must be a positive number.")
        return

    _set_step(chat_id, STEP_AMOUNT, amount=float(amount))
    _ui_prompt_voucher(chat_id)


def _handle_photo(chat_id, telegram_message):
    """Store an uploaded voucher photo and move on to confirmation."""
    session = _session(chat_id)
    if session.get("step") != STEP_VOUCHER:
        _ui_menu(chat_id, text="Tap ➕ Log expense first, then send the voucher.")
        return

    photos = telegram_message.get("photo") or []
    if not photos:
        _ui_prompt_voucher(chat_id, note="That was not a photo. Try again, or tap Skip.")
        return

    # The last entry is Telegram's largest rendition, which is what we want to keep.
    data = _download_telegram_file(photos[-1].get("file_id"))
    if data is None:
        _ui_confirm(chat_id, note="⚠️ Could not download that photo. Saving without a voucher.")
        return

    try:
        object_name = storage.upload_voucher(data, chat_id=chat_id)
    except storage.VoucherError as exc:
        app.logger.warning("Voucher upload failed: %s", exc)
        _ui_confirm(chat_id, note=f"⚠️ Voucher not stored ({exc}) Saving without it.")
        return

    _set_step(chat_id, STEP_VOUCHER, voucher_object=object_name)
    _ui_confirm(chat_id, note="📸 Voucher attached.")


def _chat_is_allowed(chat_id):
    return bool(TELEGRAM_ALLOWED_CHAT_ID) and str(chat_id) == str(TELEGRAM_ALLOWED_CHAT_ID)


def _handle_command(chat_id, text):
    command = text.split()[0].lower().lstrip('/').split('@')[0]

    if command in {"start", "menu"}:
        _ui_menu(chat_id)
    elif command in {"expense", "log", "add"}:
        _ui_categories(chat_id)
    elif command in {"summary", "month"}:
        _ui_summary(chat_id)
    elif command in {"cancel", "stop"}:
        _ui_cancel(chat_id)
    elif command == "skip":
        # /skip only means "no voucher" while we are actually asking for one.
        if _session(chat_id).get("step") == STEP_VOUCHER:
            _ui_confirm(chat_id, note="No voucher attached.")
        else:
            _ui_cancel(chat_id)
    else:
        _ui_help(chat_id)


def _handle_callback(chat_id, callback, update_id):
    """Dispatch a button press, editing the keyboard message in place."""
    # Acknowledge first: Telegram keeps a spinner on the button until this is
    # called and retries the delivery when we are slow.
    _answer_callback_query(callback.get("id"))

    message_id = (callback.get("message") or {}).get("message_id")
    try:
        parsed = parse_callback(callback.get("data") or "")
    except ValueError:
        app.logger.warning("Unhandled callback data: %r", callback.get("data"))
        _ui_menu(chat_id, message_id=message_id)
        return

    if parsed.action == ACTION_NAV:
        if parsed.value == NAV_NEW:
            _ui_categories(chat_id, message_id=message_id)
        elif parsed.value == NAV_SUMMARY:
            _ui_summary(chat_id, message_id=message_id)
        elif parsed.value == NAV_HELP:
            _ui_help(chat_id, message_id=message_id)
        else:
            _ui_menu(chat_id, message_id=message_id)
        return

    if parsed.action == ACTION_CATEGORY:
        _ui_items(chat_id, parsed.category, message_id=message_id)
        return

    if parsed.action == ACTION_ITEM:
        category = resolve_category(FINANCIAL_STRUCTURE, parsed.category)
        item = resolve_item(FINANCIAL_STRUCTURE, parsed.category, parsed.item)
        if category is None or item is None:
            # A keyboard built before the structure changed; restart the flow.
            _ui_categories(chat_id, message_id=message_id)
            return
        _set_step(chat_id, STEP_ITEM, message_id=message_id,
                  category=category, line_item_name=item)
        _ui_periods(chat_id, message_id=message_id)
        return

    if parsed.action == ACTION_YEAR:
        _ui_periods(chat_id, year=int(parsed.value), message_id=message_id)
        return

    if parsed.action == ACTION_PERIOD:
        year_text, _, month_text = parsed.value.partition("-")
        _set_step(chat_id, STEP_PERIOD, message_id=message_id,
                  fiscal_year=int(year_text), month_index=int(month_text))
        _ui_prompt_amount(chat_id)
        return

    if parsed.action == ACTION_AMOUNT:
        _ui_prompt_amount(chat_id, note="Send the corrected amount.")
        return

    if parsed.action == ACTION_SKIP:
        _ui_confirm(chat_id, note="No voucher attached.")
        return

    if parsed.action == ACTION_KEEP:
        _ui_prompt_voucher(chat_id, note="Send the replacement photo.")
        return

    if parsed.action == ACTION_SAVE:
        _ui_save(chat_id, update_id=update_id)
        return

    if parsed.action == ACTION_CANCEL:
        _ui_cancel(chat_id, message_id=message_id)
        return

    _ui_menu(chat_id, message_id=message_id)


def _handle_legacy_budget(chat_id, telegram_message, text, update_id):
    """Handle the typed BUDGET|LineItem|YYYY|MM|Amount format.

    This path *sets* the month's actual, matching its documented behaviour, while
    the button flow *adds* to it. Kept for scripting and for anyone who prefers
    typing; the button flow is the primary interface.
    """
    try:
        message = parse_budget_message(text, _budget_line_items())
    except BudgetMessageError as exc:
        _send_telegram_message(chat_id, f"Budget update rejected: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 200

    recorded = _record_budget_actual(
        message,
        chat_id=chat_id,
        telegram_update_id=update_id,
        telegram_message_id=telegram_message.get('message_id'),
    )
    if recorded:
        _send_telegram_message(
            chat_id,
            f"Budget update recorded: {message.line_item_name}, "
            f"{message.month_index:02d}/{message.fiscal_year} = {message.amount:,.2f}",
        )

    return jsonify({"ok": True, "recorded": recorded}), 200


def _route_message(chat_id, telegram_message, update_id):
    """Dispatch a message: command, legacy format, voucher photo, or amount."""
    text = (telegram_message.get('text') or '').strip()

    if text.startswith('/'):
        _handle_command(chat_id, text)
        return jsonify({"ok": True}), 200

    # Checked before the amount step so a literal BUDGET message is never parsed
    # as a number just because a draft happens to be awaiting its amount.
    if text.upper().startswith('BUDGET'):
        return _handle_legacy_budget(chat_id, telegram_message, text, update_id)

    if telegram_message.get('photo'):
        _handle_photo(chat_id, telegram_message)
        return jsonify({"ok": True}), 200

    if _session(chat_id).get("step") == STEP_AMOUNT:
        _handle_amount(chat_id, text)
        return jsonify({"ok": True}), 200

    if text:
        _ui_menu(
            chat_id,
            text=(
                "I did not understand that.\n\n"
                "Tap ➕ Log expense to use the buttons, or send "
                "BUDGET|LineItem|YYYY|MM|Amount."
            ),
        )
    else:
        _ui_menu(chat_id)

    return jsonify({"ok": True}), 200


@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    if not TELEGRAM_WEBHOOK_SECRET:
        # Fail closed in production: never accept unauthenticated updates.
        if IS_PRODUCTION:
            return jsonify({"error": "Webhook secret is not configured."}), 403
    else:
        supplied_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not hmac.compare_digest(supplied_secret, TELEGRAM_WEBHOOK_SECRET):
            return jsonify({"error": "Unauthorized webhook request."}), 403

    update = request.get_json(silent=True) or {}
    update_id = update.get('update_id')

    # Inline keyboard presses arrive as callback_query, not message.
    callback = update.get('callback_query')
    if callback:
        chat_id = str(((callback.get('message') or {}).get('chat') or {}).get('id', ''))
        if not _chat_is_allowed(chat_id):
            return jsonify({"error": "Unauthorized Telegram chat."}), 403
        _handle_callback(chat_id, callback, update_id)
        return jsonify({"ok": True}), 200

    telegram_message = update.get('message') or update.get('edited_message') or {}
    chat_id = str((telegram_message.get('chat') or {}).get('id', ''))
    if not _chat_is_allowed(chat_id):
        return jsonify({"error": "Unauthorized Telegram chat."}), 403

    return _route_message(chat_id, telegram_message, update_id)

@app.route('/')
@app.route('/book-now', methods=['GET', 'POST'])
def book_now():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        a1 = request.form.get('a1', '').strip()
        a2 = request.form.get('a2', '').strip()
        chosen_date = request.form.get('date', '')
        
        db = get_db()
        date_row = db.execute("SELECT * FROM cohort_dates WHERE date_key = ? AND open = 1", (chosen_date,)).fetchone()
        
        if not date_row or date_row['booked'] >= date_row['cap']:
            flash("Allocation Error: Target session invalid or closed.", "error")
            db.close()
            return redirect(url_for('book_now'))
        
        existing = db.execute("SELECT id FROM participant_bookings WHERE email = ? AND date_key = ?", (email, chosen_date)).fetchone()
        if existing:
            db.close()
            return render_template('success.html', name=name, status="duplicate")
        
        rec_lbl, rec_reason = run_screener_assessment(a1, a2)
        db.execute("""
            INSERT INTO participant_bookings (name, email, phone, a1, a2, date_key, status, rec_label, rec_reason)
            VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """, (name, email, phone, a1, a2, chosen_date, rec_lbl, rec_reason))
        db.commit()
        db.close()
        
        return render_template('success.html', name=name, status="success")
    
    db = get_db()
    program = db.execute("SELECT * FROM program_config ORDER BY id DESC LIMIT 1").fetchone()
    dates = db.execute("SELECT * FROM cohort_dates WHERE open = 1 ORDER BY date_key ASC").fetchall()
    db.close()
    
    return render_template('public.html', program=program, dates=dates)

# --- Admin Routes ---

@app.route('/admin')
def admin_login():
    user = get_current_user()
    if user:
        return redirect(url_for('admin_dashboard'))
    return render_template('login.html')

@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    db = get_db()
    user = db.execute("SELECT * FROM system_users WHERE username = ?", (username,)).fetchone()
    
    if not user:
        db.close()
        flash('Invalid credentials.', 'error')
        return redirect(url_for('admin_login'))
    
    now = datetime.utcnow().isoformat()
    if user['lockout_until'] and user['lockout_until'] > now:
        db.close()
        flash('Account locked due to too many failed attempts.', 'error')
        return redirect(url_for('admin_login'))
    
    if user['password_hash'] != hash_password(password):
        new_failures = (user['failed_attempts'] or 0) + 1
        lock_until = None
        if new_failures >= BRUTE_FORCE_LIMIT:
            lock_until = (datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        
        db.execute("UPDATE system_users SET failed_attempts = ?, lockout_until = ? WHERE username = ?",
                   (new_failures, lock_until, username))
        db.commit()
        db.close()
        
        flash('Invalid credentials.', 'error')
        return redirect(url_for('admin_login'))
    
    db.execute("UPDATE system_users SET failed_attempts = 0, lockout_until = NULL WHERE username = ?", (username,))
    db.commit()
    db.close()
    
    response = redirect(url_for('admin_dashboard'))
    response.set_cookie('auth_user', sign_cookie(username), httponly=True, samesite='Lax')
    return response

@app.route('/admin/logout')
def admin_logout():
    response = redirect(url_for('admin_login'))
    response.set_cookie('auth_user', '', expires=0)
    return response

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    user = get_current_user()
    db = get_db()
    
    program = db.execute("SELECT * FROM program_config ORDER BY id DESC LIMIT 1").fetchone()
    dates = db.execute("SELECT * FROM cohort_dates ORDER BY date_key ASC").fetchall()
    bookings = db.execute("""
        SELECT b.*, c.label as date_label 
        FROM participant_bookings b
        LEFT JOIN cohort_dates c ON b.date_key = c.date_key
        WHERE b.status != 'COMPLETED'
        ORDER BY b.id DESC
    """).fetchall()
    
    users = []
    if user['role'] == 'SUPERADMIN':
        users = db.execute("SELECT username, role FROM system_users ORDER BY username").fetchall()
    
    db.close()
    
    return render_template('admin_dashboard.html', 
                         user=user, 
                         program=program, 
                         dates=dates, 
                         bookings=bookings,
                         users=users)

@app.route('/admin/update-program', methods=['POST'])
@superadmin_required
def update_program():
    db = get_db()
    db.execute("""
        UPDATE program_config 
        SET title = ?, description = ?, header_img = ?, expectations = ?, q1_label = ?, q2_label = ?
        WHERE id = (SELECT id FROM program_config ORDER BY id DESC LIMIT 1)
    """, (
        request.form.get('title', ''),
        request.form.get('description', ''),
        request.form.get('header_img', ''),
        request.form.get('expectations', ''),
        request.form.get('q1_label', ''),
        request.form.get('q2_label', '')
    ))
    db.commit()
    db.close()
    
    flash('Program configuration updated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add-user', methods=['POST'])
@superadmin_required
def add_user():
    username = request.form.get('new_username', '').strip()
    password = request.form.get('new_password', '')
    role = request.form.get('new_role', 'MANAGER')
    
    if username and password:
        db = get_db()
        try:
            db.execute("INSERT INTO system_users (username, password_hash, role, failed_attempts) VALUES (?, ?, ?, 0)",
                      (username, hash_password(password), role))
            db.commit()
            flash(f'User {username} created.', 'success')
        except Exception:
            flash('Username already exists.', 'error')
        db.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add-date', methods=['POST'])
@superadmin_required
def add_date():
    raw_date = request.form.get('new_date')
    capacity = int(request.form.get('new_cap', 15))
    price = float(request.form.get('new_price', 0))
    lab = request.form.get('lab', '').strip()
    custom_title = request.form.get('custom_title', '').strip()
    
    if raw_date:
        dt = datetime.strptime(raw_date, "%Y-%m-%d")
        label = custom_title if custom_title else dt.strftime("%b %d (%a) - Live Production Session")
        
        db = get_db()
        db.execute("""
            INSERT INTO cohort_dates (date_key, label, open, cap, booked, venue, time_window, price_cents, map_address, itinerary, lab, custom_title)
            VALUES (?, ?, 1, ?, 0, ?, ?, ?, ?, ?, ?, ?)
        """, (raw_date, label, capacity, "AI Experience Center Main Lab", "09:00 AM - 04:00 PM PHT", 
              int(price * 100), "", "", lab, custom_title))
        db.commit()
        db.close()
        
        flash('Session date created.', 'success')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/update-date', methods=['POST'])
@superadmin_required
def update_date():
    key = request.form.get('date_key')
    open_param = 1 if request.form.get('open') == 'true' else 0
    cap = int(request.form.get('cap', 15))
    venue = request.form.get('venue', '').strip()
    time_window = request.form.get('time_window', '').strip()
    price = float(request.form.get('session_price', 0))
    map_address = request.form.get('map_address', '').strip()
    itinerary = request.form.get('itinerary', '').strip()
    lab = request.form.get('lab', '').strip()
    custom_title = request.form.get('custom_title', '').strip()
    
    label = custom_title if custom_title else key
    
    db = get_db()
    db.execute("""
        UPDATE cohort_dates 
        SET open = ?, cap = ?, venue = ?, time_window = ?, price_cents = ?, map_address = ?, itinerary = ?, label = ?, lab = ?, custom_title = ?
        WHERE date_key = ?
    """, (open_param, cap, venue, time_window, int(price * 100), map_address, itinerary, label, lab, custom_title, key))
    db.commit()
    db.close()
    
    flash('Session updated.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-date', methods=['POST'])
@superadmin_required
def delete_date():
    key = request.form.get('date_key')
    db = get_db()
    db.execute("DELETE FROM participant_bookings WHERE date_key = ?", (key,))
    db.execute("DELETE FROM cohort_dates WHERE date_key = ?", (key,))
    db.commit()
    db.close()
    
    flash('Session deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/approve-seat', methods=['POST'])
@login_required
def approve_seat():
    booking_id = int(request.form.get('booking_idx'))
    db = get_db()
    booking = db.execute("SELECT * FROM participant_bookings WHERE id = ?", (booking_id,)).fetchone()

    if booking and booking['status'] == 'PENDING':
        cohort = db.execute(
            "SELECT cap, booked FROM cohort_dates WHERE date_key = ?",
            (booking['date_key'],),
        ).fetchone()

        if not cohort:
            flash('Session not found.', 'error')
        elif cohort['booked'] >= cohort['cap']:
            flash('This session is already at capacity. Booking cannot be approved.', 'error')
        else:
            db.execute(
                "UPDATE cohort_dates SET booked = booked + 1 WHERE date_key = ?",
                (booking['date_key'],),
            )
            db.execute(
                "UPDATE participant_bookings SET status = 'APPROVED' WHERE id = ?",
                (booking_id,),
            )
            db.commit()
            flash('Booking approved.', 'success')

    elif booking and booking['status'] != 'PENDING':
        flash('Booking is not awaiting approval.', 'error')

    db.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reject-seat', methods=['POST'])
@login_required
def reject_seat():
    booking_id = int(request.form.get('booking_idx'))
    db = get_db()
    db.execute("UPDATE participant_bookings SET status = 'REJECTED' WHERE id = ?", (booking_id,))
    db.commit()
    db.close()
    
    flash('Booking rejected.', 'success')
    return redirect(url_for('admin_dashboard'))

# --- Accounting Route ---

@app.route('/admin/accounting')
@login_required
def accounting_dashboard():
    db = get_db()
    
    # Build price map
    price_map = {}
    for row in db.execute("SELECT date_key, price_cents FROM cohort_dates").fetchall():
        price_map[row['date_key']] = row['price_cents'] / 100.0
    
    # Calculate metrics
    total_approved = 0.0
    total_pending = 0.0
    approved_count = 0
    pending_count = 0
    
    ledger = []
    for row in db.execute("""
        SELECT b.id, b.name, b.email, b.status, b.date_key, c.label as date_label
        FROM participant_bookings b
        LEFT JOIN cohort_dates c ON b.date_key = c.date_key
        ORDER BY b.id DESC
    """).fetchall():
        price = price_map.get(row['date_key'], 0.0)
        
        if row['status'] == 'APPROVED':
            total_approved += price
            approved_count += 1
        elif row['status'] == 'PENDING':
            total_pending += price
            pending_count += 1
        
        ledger.append({
            'id': row['id'],
            'name': row['name'],
            'email': row['email'],
            'date_label': row['date_label'] or row['date_key'],
            'status': row['status'],
            'price': price
        })
    
    db.close()
    
    return render_template('accounting.html',
                         ledger=ledger,
                         total_approved=total_approved,
                         total_pending=total_pending,
                         approved_count=approved_count,
                         pending_count=pending_count)

# --- Budget Controller Route ---

# FINANCIAL_STRUCTURE and MONTHS live in budget_structure.py so the web page, the
# Telegram keyboards and the text-format validator can never drift apart.


def calculate_budget_metrics(forecast_data, actual_data, monthly_revenue):
    """Calculate monthly expense totals and profitability from budget inputs."""
    operating_categories = {"Other Expenses", "Promotion Expenses", "Payroll & Pilotage"}
    operating_items = {
        item
        for category, items in FINANCIAL_STRUCTURE.items()
        if category in operating_categories
        for item in items
    }
    fixed_items = set(FINANCIAL_STRUCTURE["Fixed Costs"])

    forecast_total = [0.0] * 12
    actual_total = [0.0] * 12
    forecast_operating = [0.0] * 12
    actual_operating = [0.0] * 12
    forecast_fixed = [0.0] * 12
    actual_fixed = [0.0] * 12

    for item, values in forecast_data.items():
        for index, value in enumerate(values[:12]):
            amount = float(value or 0)
            forecast_total[index] += amount
            if item in operating_items:
                forecast_operating[index] += amount
            if item in fixed_items:
                forecast_fixed[index] += amount

    for item, values in actual_data.items():
        for index, value in enumerate(values[:12]):
            amount = float(value or 0)
            actual_total[index] += amount
            if item in operating_items:
                actual_operating[index] += amount
            if item in fixed_items:
                actual_fixed[index] += amount

    revenue = [float(value or 0) for value in monthly_revenue[:12]]
    forecast_gop = [revenue[index] - forecast_operating[index] for index in range(12)]
    actual_gop = [revenue[index] - actual_operating[index] for index in range(12)]
    forecast_net = [forecast_gop[index] - forecast_fixed[index] for index in range(12)]
    actual_net = [actual_gop[index] - actual_fixed[index] for index in range(12)]

    return {
        "forecast_total": forecast_total,
        "actual_total": actual_total,
        "forecast_gop": forecast_gop,
        "actual_gop": actual_gop,
        "forecast_net": forecast_net,
        "actual_net": actual_net,
        "revenue": revenue,
    }

@app.route('/admin/budget')
@login_required
def budget_controller():
    fiscal_year = int(request.args.get('year', datetime.now().year))
    
    db = get_db()
    
    # Initialize budget rows if needed
    budget_rows = [
        (fiscal_year, month_index, item, 0.0)
        for category_items in FINANCIAL_STRUCTURE.values()
        for item in category_items
        for month_index in range(1, 13)
    ]
    placeholders = ', '.join(['(%s, %s, %s, %s)'] * len(budget_rows))
    if getattr(db, 'postgres', False):
        db.execute(
            f"INSERT INTO budget_forecast (fiscal_year, month_index, line_item_name, target_amount) VALUES {placeholders} ON CONFLICT (fiscal_year, month_index, line_item_name) DO NOTHING",
            tuple(value for row in budget_rows for value in row),
        )
        db.execute(
            f"INSERT INTO budget_actuals_cache (fiscal_year, month_index, line_item_name, actual_amount) VALUES {placeholders} ON CONFLICT (fiscal_year, month_index, line_item_name) DO NOTHING",
            tuple(value for row in budget_rows for value in row),
        )
    else:
        sqlite_placeholders = placeholders.replace('%s', '?')
        db.execute(
            f"INSERT OR IGNORE INTO budget_forecast (fiscal_year, month_index, line_item_name, target_amount) VALUES {sqlite_placeholders}",
            tuple(value for row in budget_rows for value in row),
        )
        db.execute(
            f"INSERT OR IGNORE INTO budget_actuals_cache (fiscal_year, month_index, line_item_name, actual_amount) VALUES {sqlite_placeholders}",
            tuple(value for row in budget_rows for value in row),
        )
    
    # Load data
    forecast_data = {}
    actual_data = {}
    
    for row in db.execute("SELECT month_index, line_item_name, target_amount FROM budget_forecast WHERE fiscal_year = ?", (fiscal_year,)).fetchall():
        forecast_data.setdefault(row['line_item_name'], [0.0] * 12)
        forecast_data[row['line_item_name']][row['month_index'] - 1] = row['target_amount']
    
    for row in db.execute("SELECT month_index, line_item_name, actual_amount FROM budget_actuals_cache WHERE fiscal_year = ?", (fiscal_year,)).fetchall():
        actual_data.setdefault(row['line_item_name'], [0.0] * 12)
        actual_data[row['line_item_name']][row['month_index'] - 1] = row['actual_amount']

    monthly_revenue = [0.0] * 12
    for row in db.execute("""
        SELECT b.date_key, c.price_cents
        FROM participant_bookings b
        LEFT JOIN cohort_dates c ON b.date_key = c.date_key
        WHERE b.status = 'APPROVED'
    """).fetchall():
        try:
            booking_year, booking_month, _ = row['date_key'].split('-', 2)
            if int(booking_year) == fiscal_year:
                monthly_revenue[int(booking_month) - 1] += (row['price_cents'] or 0) / 100.0
        except (AttributeError, ValueError, IndexError):
            continue

    metrics = calculate_budget_metrics(forecast_data, actual_data, monthly_revenue)
    chart_max = max(metrics["forecast_total"] + metrics["actual_total"] + [1.0])
    last_actual = db.execute("""
        SELECT timestamp FROM budget_actuals_audit_log
        WHERE status = 'RECORDED' AND fiscal_year = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (fiscal_year,)).fetchone()
    
    # Get audit log
    audit_log = db.execute("""
        SELECT * FROM forecast_audit_log 
        WHERE fiscal_year = ?
        ORDER BY timestamp DESC
        LIMIT 50
    """, (fiscal_year,)).fetchall()

    # Expenses logged through the Telegram button flow, newest first, so the
    # uploaded vouchers are reachable from the budget page.
    recent_expenses = db.execute("""
        SELECT timestamp, line_item_name, category, amount, voucher_object
        FROM expense_transactions
        WHERE fiscal_year = ? AND status = 'RECORDED'
        ORDER BY id DESC
        LIMIT 25
    """, (fiscal_year,)).fetchall()
    
    db.close()
    
    user = get_current_user()
    is_superadmin = user['role'] == 'SUPERADMIN'
    
    return render_template('budget_controller.html',
                         fiscal_year=fiscal_year,
                         structure=FINANCIAL_STRUCTURE,
                         months=MONTHS,
                         forecast_data=forecast_data,
                         actual_data=actual_data,
                         audit_log=audit_log,
                         is_superadmin=is_superadmin,
                         metrics=metrics,
                         chart_max=chart_max,
                         recent_expenses=recent_expenses,
                         last_actual_timestamp=last_actual['timestamp'] if last_actual else None)

@app.route('/admin/voucher/<path:object_name>')
@login_required
def view_voucher(object_name):
    """Stream a Telegram voucher from Cloud Storage.

    Proxied rather than a signed URL so the bucket stays private and the runtime
    service account needs no token-signing permission. login_required keeps the
    receipts behind the admin session.
    """
    if not storage.is_valid_object_name(object_name):
        abort(404)

    try:
        data = storage.download_voucher(object_name)
    except storage.VoucherError as exc:
        app.logger.warning("Voucher download failed: %s", exc)
        abort(404)

    return Response(
        data,
        mimetype=storage.content_type_for(object_name),
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.route('/admin/budget/forecast/update', methods=['POST'])
@superadmin_required
def update_forecast():
    fiscal_year = int(request.form.get('fiscal_year'))
    changes = request.form.get('changes', '')
    
    db = get_db()
    username = get_current_user()['username']
    
    for change in changes.split(';'):
        if not change.strip():
            continue
        
        try:
            month_idx, item_name, new_value = change.split('|')
            month_idx = int(month_idx)
            new_value = float(new_value)
            
            # Get old value for audit
            old_row = db.execute("""
                SELECT target_amount FROM budget_forecast 
                WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?
            """, (fiscal_year, month_idx, item_name)).fetchone()
            
            old_value = old_row['target_amount'] if old_row else 0.0
            
            # Update forecast
            db.execute("""
                UPDATE budget_forecast 
                SET target_amount = ?
                WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?
            """, (new_value, fiscal_year, month_idx, item_name))
            
            # Log audit
            db.execute("""
                INSERT INTO forecast_audit_log (timestamp, username, fiscal_year, month_index, line_item_name, old_value, new_value)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (datetime.utcnow().isoformat(), username, fiscal_year, month_idx, item_name, old_value, new_value))
            
        except (ValueError, IndexError):
            continue
    
    db.commit()
    db.close()
    
    flash('Forecast updated successfully.', 'success')
    return redirect(url_for('budget_controller', year=fiscal_year))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
