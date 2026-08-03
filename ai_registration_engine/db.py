import sqlite3
import hashlib
from datetime import datetime
from config import DB_PATH

def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password: str) -> str:
    """Hash password with SHA-256"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def init_db():
    """Initialize database schema"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Core tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'MANAGER',
            failed_attempts INTEGER DEFAULT 0,
            lockout_until TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS program_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            expectations TEXT,
            header_img TEXT,
            q1_label TEXT,
            q2_label TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cohort_dates (
            date_key TEXT PRIMARY KEY,
            label TEXT,
            open INTEGER DEFAULT 1,
            cap INTEGER DEFAULT 15,
            booked INTEGER DEFAULT 0,
            venue TEXT,
            time_window TEXT,
            price_cents INTEGER DEFAULT 0,
            map_address TEXT,
            itinerary TEXT,
            lab TEXT DEFAULT '',
            custom_title TEXT DEFAULT ''
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS participant_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            a1 TEXT,
            a2 TEXT,
            date_key TEXT,
            status TEXT DEFAULT 'PENDING',
            rec_label TEXT,
            rec_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(date_key) REFERENCES cohort_dates(date_key)
        )
    """)
    
    # Budget tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budget_forecast (
            fiscal_year INTEGER,
            month_index INTEGER,
            line_item_name TEXT,
            target_amount REAL DEFAULT 0.0,
            PRIMARY KEY (fiscal_year, month_index, line_item_name)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budget_actuals_cache (
            fiscal_year INTEGER,
            month_index INTEGER,
            line_item_name TEXT,
            actual_amount REAL DEFAULT 0.0,
            PRIMARY KEY (fiscal_year, month_index, line_item_name)
        )
    """)
    
    # Audit trail for forecast changes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS forecast_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            username TEXT,
            fiscal_year INTEGER,
            month_index INTEGER,
            line_item_name TEXT,
            old_value REAL,
            new_value REAL
        )
    """)
    
    # Expense transactions (Telegram bot)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expense_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            fiscal_year INTEGER,
            month_index INTEGER,
            category TEXT,
            item TEXT,
            amount REAL,
            voucher_path TEXT,
            chat_id INTEGER
        )
    """)
    
    # Safe migrations for existing databases
    migrations = [
        "ALTER TABLE cohort_dates ADD COLUMN price_cents INTEGER DEFAULT 0",
        "ALTER TABLE cohort_dates ADD COLUMN lab TEXT DEFAULT ''",
        "ALTER TABLE cohort_dates ADD COLUMN custom_title TEXT DEFAULT ''",
        "ALTER TABLE system_users ADD COLUMN failed_attempts INTEGER DEFAULT 0",
        "ALTER TABLE system_users ADD COLUMN lockout_until TEXT"
    ]
    
    for migration in migrations:
        try:
            cursor.execute(migration)
        except sqlite3.OperationalError:
            pass  # Column already exists
    
    # Default admin user
    cursor.execute("SELECT COUNT(*) FROM system_users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO system_users (username, password_hash, role, failed_attempts)
            VALUES (?, ?, ?, 0)
        """, ("admin", hash_password("MonitorGear2026"), "SUPERADMIN"))
    
    # Default program config
    cursor.execute("SELECT COUNT(*) FROM program_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO program_config (title, description, expectations, header_img, q1_label, q2_label)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "AI Experience Center: Live Production Lab",
            "Step out of the sandboxes. Deploy, stress-test, and orchestrate production-grade AI systems alongside elite engineering peers in a hardened production environment.",
            "Architect multi-agent orchestration frameworks; Optimize system latency pipelines and vector search spaces; Troubleshoot model drift and high-throughput bottlenecks under real-world conditions.",
            "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=1200&auto=format&fit=crop",
            "What is the single biggest operational bottleneck in your current business, freelancing, or career that you intend to solve using AI?",
            "Briefly describe your current business model, profession, or target niche framework."
        ))
    
    conn.commit()
    conn.close()

def migrate_price_data():
    """Migrate old || price format to price_cents column"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT date_key, time_window FROM cohort_dates WHERE time_window LIKE '%||%'")
    for row in cursor.fetchall():
        try:
            time_part, price_str = row['time_window'].split('||', 1)
            price_cents = int(float(price_str) * 100)
            cursor.execute("""
                UPDATE cohort_dates 
                SET time_window = ?, price_cents = ?
                WHERE date_key = ?
            """, (time_part, price_cents, row['date_key']))
        except (ValueError, IndexError):
            pass
    
    conn.commit()
    conn.close()
