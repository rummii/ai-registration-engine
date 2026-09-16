import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as db_module


def test_approve_seat_respects_capacity(tmp_path, monkeypatch):
    db_path = tmp_path / "test_registration.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "DATABASE_URL", "")

    import app as app_module

    importlib.reload(app_module)
    app = app_module.app
    client = app.test_client()

    login = client.post(
        "/admin/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert login.status_code == 302

    with db_module.get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO cohort_dates
            (id, date_key, label, open, cap, booked, venue, time_window, price_cents, map_address, itinerary, lab, custom_title)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "2026-05-10",
                "Test Session",
                1,
                1,
                1,
                "Venue",
                "09:00-12:00",
                5000,
                "",
                "",
                "",
                "",
            ),
        )
        conn.execute(
            """
            INSERT INTO participant_bookings
            (id, name, email, phone, a1, a2, date_key, status, rec_label, rec_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Tester",
                "tester@example.com",
                "123",
                "Alpha",
                "Beta",
                "2026-05-10",
                "PENDING",
                "ACCEPT",
                "Reason",
            ),
        )
        conn.commit()

    response = client.post(
        "/admin/approve-seat",
        data={"booking_idx": 1},
        follow_redirects=False,
    )

    assert response.status_code == 302

    with db_module.get_db() as conn:
        cohort = conn.execute(
            "SELECT booked FROM cohort_dates WHERE date_key = ?",
            ("2026-05-10",),
        ).fetchone()
        booking = conn.execute(
            "SELECT status FROM participant_bookings WHERE id = ?",
            (1,),
        ).fetchone()

    assert cohort["booked"] == 1
    assert booking["status"] == "PENDING"
