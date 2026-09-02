import sqlite3
import hashlib
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "registration.db")


def init_db():
    """Initialize database schema."""
    db = get_db()
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS system_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'MANAGER',
            failed_attempts INTEGER DEFAULT 0,
            lockout_until TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    db.execute("""
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
    """)
    
    db.execute("""
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
    """)
    
    db.execute("""
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
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS budget_forecast (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fiscal_year INTEGER NOT NULL,
            month_index INTEGER NOT NULL,
            line_item_name TEXT NOT NULL,
            target_amount REAL DEFAULT 0.0,
            UNIQUE(fiscal_year, month_index, line_item_name)
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS budget_actuals_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fiscal_year INTEGER NOT NULL,
            month_index INTEGER NOT NULL,
            line_item_name TEXT NOT NULL,
            actual_amount REAL DEFAULT 0.0,
            UNIQUE(fiscal_year, month_index, line_item_name)
        )
    """)
    
    db.execute("""
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
    """)
    
    db.commit()
    
    # Create default admin user if no users exist
    user_count = db.execute("SELECT COUNT(*) as cnt FROM system_users").fetchone()['cnt']
    if user_count == 0:
        db.execute("""
            INSERT INTO system_users (username, password_hash, role, failed_attempts)
            VALUES (?, ?, 'SUPERADMIN', 0)
        """, ("admin", hash_password("admin123")))
        db.commit()
    
    # Create default program config if none exists
    config_count = db.execute("SELECT COUNT(*) as cnt FROM program_config").fetchone()['cnt']
    if config_count == 0:
        db.execute("""
            INSERT INTO program_config (title, description, header_img, expectations, q1_label, q2_label)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "AI Experience Center: Live Production Lab",
            "Step out of the sandboxes. Deploy, stress-test, and orchestrate production-grade AI systems alongside elite engineering peers in a hardened production environment.",
            "",
            "Production-grade AI system deployment;AI workflow orchestration;Real-time monitoring and alerting",
            "What is the single biggest operational bottleneck?",
            "Describe your current business model or profession."
        ))
        db.commit()
    
    db.close()

def migrate_price_data():
    """Placeholder for future price data migrations."""
    pass


def get_db():
    """Get a database connection with row factory."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def hash_password(password: str) -> str:
    """Hash password using SHA-256 with salt."""
    salt = "aiex_salt_v1_"
    return hashlib.sha256((salt + password).encode()).hexdigest()
