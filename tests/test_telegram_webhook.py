import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as db_module


def test_telegram_webhook_records_actual_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "webhook.db"))
    monkeypatch.setattr(db_module, "DATABASE_URL", "")

    import app as app_module

    importlib.reload(app_module)
    app_module.TELEGRAM_ALLOWED_CHAT_ID = "12345"
    app_module.TELEGRAM_WEBHOOK_SECRET = "webhook-secret"
    app_module.TELEGRAM_BOT_TOKEN = ""
    client = app_module.app.test_client()

    payload = {
        "update_id": 9001,
        "message": {
            "message_id": 55,
            "chat": {"id": 12345},
            "text": "BUDGET|Marketing|2026|09|25000",
        },
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"}

    response = client.post("/telegram/webhook", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "recorded": True}

    with db_module.get_db() as conn:
        actual = conn.execute(
            "SELECT actual_amount FROM budget_actuals_cache WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?",
            (2026, 9, "Marketing"),
        ).fetchone()
        assert actual["actual_amount"] == 25000.0

    duplicate = client.post("/telegram/webhook", json=payload, headers=headers)
    assert duplicate.status_code == 200
    assert duplicate.get_json() == {"ok": True, "recorded": False}


def test_telegram_webhook_rejects_wrong_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "unauthorized.db"))
    monkeypatch.setattr(db_module, "DATABASE_URL", "")

    import app as app_module

    importlib.reload(app_module)
    app_module.TELEGRAM_ALLOWED_CHAT_ID = "12345"
    app_module.TELEGRAM_WEBHOOK_SECRET = "webhook-secret"
    client = app_module.app.test_client()

    response = client.post(
        "/telegram/webhook",
        json={"message": {"chat": {"id": 999}, "text": "BUDGET|Marketing|2026|09|25000"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
    )

    assert response.status_code == 403
