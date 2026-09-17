import sqlite3
import hashlib
import os
import re

from config import DATABASE_URL, IS_PRODUCTION

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "registration.db")


def is_postgres() -> bool:
    return bool(DATABASE_URL) and DATABASE_URL.startswith("postgres")


class DBAdapter:
    """Compatibility wrapper for SQLite and PostgreSQL connections."""

    def __init__(self, connection, *, postgres: bool):
        self.conn = connection
        self.postgres = postgres

    def execute(self, query, params=()):
        if self.postgres and query:
            query = self._translate_sqlite_to_postgres(query)
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor

    def _translate_placeholders(self, query):
        parsed_query = []
        in_single = False
        in_double = False
        escaped = False
        for ch in query:
            if escaped:
                parsed_query.append(ch)
                escaped = False
                continue
            if ch == "\\":
                parsed_query.append(ch)
                escaped = True
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                parsed_query.append(ch)
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                parsed_query.append(ch)
                continue
            if ch == "?" and not in_single and not in_double:
                parsed_query.append("%s")
                continue
            parsed_query.append(ch)
        return "".join(parsed_query)

    def _translate_sqlite_to_postgres(self, query):
        """Translate a few SQLite-specific statements into PostgreSQL equivalents."""
        normalized = query.strip()

        if re.match(r"^INSERT\s+OR\s+IGNORE\s+INTO\s+", normalized, re.IGNORECASE):
            match = re.match(r"^INSERT\s+OR\s+IGNORE\s+INTO\s+([A-Za-z_][\w]*)\s*\((.*?)\)\s*VALUES\s*(\(.*\))\s*;?\s*$",
                             normalized, re.IGNORECASE | re.DOTALL)
            if match:
                table, cols, values = match.groups()
                return self._translate_placeholders(f"INSERT INTO {table} ({cols}) VALUES {values} ON CONFLICT DO NOTHING")

        if re.match(r"^INSERT\s+OR\s+REPLACE\s+INTO\s+", normalized, re.IGNORECASE):
            match = re.match(r"^INSERT\s+OR\s+REPLACE\s+INTO\s+([A-Za-z_][\w]*)\s*\((.*?)\)\s*VALUES\s*(\(.*\))\s*;?\s*$",
                             normalized, re.IGNORECASE | re.DOTALL)
            if match:
                table, cols, values = match.groups()
                columns = [c.strip() for c in cols.split(',') if c.strip()]
                target = 'id' if 'id' in columns else columns[0] if columns else 'id'
                assignments = ', '.join(f"{column} = EXCLUDED.{column}" for column in columns)
                return self._translate_placeholders(f"INSERT INTO {table} ({cols}) VALUES {values} ON CONFLICT ({target}) DO UPDATE SET {assignments}")

        return self._translate_placeholders(query)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
        return False

    def __getattr__(self, attr):
        return getattr(self.conn, attr)


def get_db():
    """Get a database connection with row factory."""
    if is_postgres():
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise RuntimeError("psycopg2-binary is required for PostgreSQL connections.") from exc

        conn = psycopg2.connect(DATABASE_URL)
        conn.cursor_factory = RealDictCursor
        return DBAdapter(conn, postgres=True)

    if IS_PRODUCTION:
        raise RuntimeError(
            "DATABASE_URL must be a PostgreSQL connection string in production; "
            "refusing to fall back to a local SQLite file."
        )

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return DBAdapter(db, postgres=False)


def init_db():
    """Initialize database schema."""
    db = get_db()
    postgres = is_postgres()

    if postgres:
        system_users_sql = """
            CREATE TABLE IF NOT EXISTS system_users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'MANAGER',
                failed_attempts INTEGER DEFAULT 0,
                lockout_until TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        program_config_sql = """
            CREATE TABLE IF NOT EXISTS program_config (
                id SERIAL PRIMARY KEY,
                title TEXT DEFAULT 'AI Experience Center: Live Production Lab',
                description TEXT DEFAULT 'Step out of the sandboxes.',
                header_img TEXT DEFAULT '',
                expectations TEXT DEFAULT '',
                q1_label TEXT DEFAULT 'What is your biggest operational bottleneck?',
                q2_label TEXT DEFAULT 'Describe your business model or profession.',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        cohort_dates_sql = """
            CREATE TABLE IF NOT EXISTS cohort_dates (
                id SERIAL PRIMARY KEY,
                date_key TEXT UNIQUE NOT NULL,
                label TEXT DEFAULT '',
                open INTEGER DEFAULT 1,
                cap INTEGER DEFAULT 15,
                booked INTEGER DEFAULT 0,
                venue TEXT DEFAULT '',
                time_window TEXT DEFAULT '',
                price_cents INTEGER DEFAULT 0,
                map_address TEXT DEFAULT '',
                itinerary TEXT DEFAULT '',
                lab TEXT DEFAULT '',
                custom_title TEXT DEFAULT ''
            )
        """
        participant_bookings_sql = """
            CREATE TABLE IF NOT EXISTS participant_bookings (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT DEFAULT '',
                a1 TEXT DEFAULT '',
                a2 TEXT DEFAULT '',
                date_key TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                rec_label TEXT DEFAULT '',
                rec_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        budget_forecast_sql = """
            CREATE TABLE IF NOT EXISTS budget_forecast (
                id SERIAL PRIMARY KEY,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                target_amount REAL DEFAULT 0.0,
                UNIQUE(fiscal_year, month_index, line_item_name)
            )
        """
        budget_actuals_cache_sql = """
            CREATE TABLE IF NOT EXISTS budget_actuals_cache (
                id SERIAL PRIMARY KEY,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                actual_amount REAL DEFAULT 0.0,
                UNIQUE(fiscal_year, month_index, line_item_name)
            )
        """
        forecast_audit_log_sql = """
            CREATE TABLE IF NOT EXISTS forecast_audit_log (
                id SERIAL PRIMARY KEY,
                timestamp TEXT NOT NULL,
                username TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                old_value REAL NOT NULL,
                new_value REAL NOT NULL
            )
        """
        budget_actuals_audit_log_sql = """
            CREATE TABLE IF NOT EXISTS budget_actuals_audit_log (
                id SERIAL PRIMARY KEY,
                telegram_update_id TEXT UNIQUE,
                timestamp TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL
            )
        """
    else:
        system_users_sql = """
            CREATE TABLE IF NOT EXISTS system_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'MANAGER',
                failed_attempts INTEGER DEFAULT 0,
                lockout_until TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        program_config_sql = """
            CREATE TABLE IF NOT EXISTS program_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT DEFAULT 'AI Experience Center: Live Production Lab',
                description TEXT DEFAULT 'Step out of the sandboxes.',
                header_img TEXT DEFAULT '',
                expectations TEXT DEFAULT '',
                q1_label TEXT DEFAULT 'What is your biggest operational bottleneck?',
                q2_label TEXT DEFAULT 'Describe your business model or profession.',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        cohort_dates_sql = """
            CREATE TABLE IF NOT EXISTS cohort_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_key TEXT UNIQUE NOT NULL,
                label TEXT DEFAULT '',
                open INTEGER DEFAULT 1,
                cap INTEGER DEFAULT 15,
                booked INTEGER DEFAULT 0,
                venue TEXT DEFAULT '',
                time_window TEXT DEFAULT '',
                price_cents INTEGER DEFAULT 0,
                map_address TEXT DEFAULT '',
                itinerary TEXT DEFAULT '',
                lab TEXT DEFAULT '',
                custom_title TEXT DEFAULT ''
            )
        """
        participant_bookings_sql = """
            CREATE TABLE IF NOT EXISTS participant_bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT DEFAULT '',
                a1 TEXT DEFAULT '',
                a2 TEXT DEFAULT '',
                date_key TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                rec_label TEXT DEFAULT '',
                rec_reason TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        budget_forecast_sql = """
            CREATE TABLE IF NOT EXISTS budget_forecast (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                target_amount REAL DEFAULT 0.0,
                UNIQUE(fiscal_year, month_index, line_item_name)
            )
        """
        budget_actuals_cache_sql = """
            CREATE TABLE IF NOT EXISTS budget_actuals_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                actual_amount REAL DEFAULT 0.0,
                UNIQUE(fiscal_year, month_index, line_item_name)
            )
        """
        forecast_audit_log_sql = """
            CREATE TABLE IF NOT EXISTS forecast_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                username TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                old_value REAL NOT NULL,
                new_value REAL NOT NULL
            )
        """
        budget_actuals_audit_log_sql = """
            CREATE TABLE IF NOT EXISTS budget_actuals_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_update_id TEXT UNIQUE,
                timestamp TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT,
                fiscal_year INTEGER NOT NULL,
                month_index INTEGER NOT NULL,
                line_item_name TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL
            )
        """

    for statement in [
        system_users_sql,
        program_config_sql,
        cohort_dates_sql,
        participant_bookings_sql,
        budget_forecast_sql,
        budget_actuals_cache_sql,
        forecast_audit_log_sql,
        budget_actuals_audit_log_sql,
    ]:
        db.execute(statement)

    db.commit()

    # Create default admin user if no users exist
    user_count = db.execute("SELECT COUNT(*) as cnt FROM system_users").fetchone()['cnt']
    if user_count == 0:
        if postgres:
            db.execute(
                "INSERT INTO system_users (username, password_hash, role, failed_attempts) VALUES (%s, %s, 'SUPERADMIN', 0)",
                ("admin", hash_password("admin123")),
            )
        else:
            db.execute(
                "INSERT INTO system_users (username, password_hash, role, failed_attempts) VALUES (?, ?, 'SUPERADMIN', 0)",
                ("admin", hash_password("admin123")),
            )
        db.commit()

    # Create default program config if none exists
    config_count = db.execute("SELECT COUNT(*) as cnt FROM program_config").fetchone()['cnt']
    if config_count == 0:
        if postgres:
            db.execute(
                "INSERT INTO program_config (title, description, header_img, expectations, q1_label, q2_label) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    "AI Experience Center: Live Production Lab",
                    "Step out of the sandboxes. Deploy, stress-test, and orchestrate production-grade AI systems alongside elite engineering peers in a hardened production environment.",
                    "",
                    "Production-grade AI system deployment;AI workflow orchestration;Real-time monitoring and alerting",
                    "What is the single biggest operational bottleneck?",
                    "Describe your current business model or profession."
                ),
            )
        else:
            db.execute(
                "INSERT INTO program_config (title, description, header_img, expectations, q1_label, q2_label) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "AI Experience Center: Live Production Lab",
                    "Step out of the sandboxes. Deploy, stress-test, and orchestrate production-grade AI systems alongside elite engineering peers in a hardened production environment.",
                    "",
                    "Production-grade AI system deployment;AI workflow orchestration;Real-time monitoring and alerting",
                    "What is the single biggest operational bottleneck?",
                    "Describe your current business model or profession."
                ),
            )
        db.commit()

    db.close()

def migrate_price_data():
    """Placeholder for future price data migrations."""
    pass

def hash_password(password: str) -> str:
    """Hash password using SHA-256 with salt."""
    salt = "aiex_salt_v1_"
    return hashlib.sha256((salt + password).encode()).hexdigest()
