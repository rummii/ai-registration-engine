import sys
sys.path.insert(0, '/home/vsmwrurd/ai_registration_engine')
import os
import json
import traceback
import html
import sqlite3
import hashlib
import hmac
from urllib.parse import parse_qs
from datetime import datetime, timedelta

BASE_DIR = "/home/vsmwrurd/ai_registration_engine"
DB_FILE = os.path.join(BASE_DIR, "booking_storage.db")
CRASH_LOG = os.path.join(BASE_DIR, "crash_log.txt")

# Cryptographic Keys (Hardened)
COOKIE_SECRET = b"ai_center_2026_secure_hmac_signature_core_key"
MAX_CONTENT_LENGTH = 10 * 1024 * 1024
BRUTE_FORCE_LIMIT = 5
LOCKOUT_MINUTES = 15

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pass(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def sign_cookie_value(username):
    """Generates a cryptographically secure signed cookie string."""
    timestamp = str(int(datetime.utcnow().timestamp()))
    payload = f"{username}|{timestamp}".encode('utf-8')
    sig = hmac.new(COOKIE_SECRET, payload, hashlib.sha256).hexdigest()
    return f"{username}|{timestamp}|{sig}"

def verify_signed_cookie(cookie_value):
    """Verifies that the incoming cookie signature is legitimate and not altered."""
    if not cookie_value:
        return None
    try:
        parts = cookie_value.split('|')
        if len(parts) != 3:
            return None
        username, timestamp, sig = parts
        payload = f"{username}|{timestamp}".encode('utf-8')
        expected_sig = hmac.new(COOKIE_SECRET, payload, hashlib.sha256).hexdigest()
        
        if hmac.compare_digest(sig, expected_sig):
            # Session expiration safety check (Valid for 24 hours)
            if datetime.utcnow().timestamp() - float(timestamp) < 86400:
                return username
    except Exception:
        pass
    return None

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT,
            role TEXT DEFAULT 'MANAGER',
            failed_attempts INTEGER DEFAULT 0,
            lockout_until TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS program_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, description TEXT, expectations TEXT,
            header_img TEXT, q1_label TEXT, q2_label TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cohort_dates (
            date_key TEXT PRIMARY KEY,
            label TEXT, open INTEGER, cap INTEGER, booked INTEGER,
            venue TEXT, time_window TEXT, map_address TEXT, itinerary TEXT,
            lab TEXT DEFAULT '', custom_title TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS participant_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, email TEXT, phone TEXT,
            a1 TEXT, a2 TEXT, date_key TEXT,
            status TEXT DEFAULT 'PENDING',
            rec_label TEXT, rec_reason TEXT,
            FOREIGN KEY(date_key) REFERENCES cohort_dates(date_key)
        )
    """)
    
    # Structural safety assertions for existing DB files
    try:
        cursor.execute("ALTER TABLE cohort_dates ADD COLUMN lab TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE cohort_dates ADD COLUMN custom_title TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE system_users ADD COLUMN failed_attempts INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE system_users ADD COLUMN lockout_until TEXT")
    except sqlite3.OperationalError:
        pass
    
    cursor.execute("SELECT COUNT(*) FROM system_users")
    if cursor.fetchone()[0] == 0:
        root_hash = hash_pass("MonitorGear2026")
        cursor.execute("INSERT INTO system_users (username, password_hash, role, failed_attempts) VALUES (?, ?, ?, 0)", ("admin", root_hash, "SUPERADMIN"))
        
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

def clean_input(val):
    if not val: return ""
    return html.escape(val.strip())

def run_screener_assessment(a1, a2):
    combined = (a1 + " " + a2).lower()
    score = 0
    if len(a1) > 15: score += 2
    if len(a2) > 10: score += 1
    if len(a1) > 40: score += 2
    keywords = ["business", "freelance", "client", "agency", "marketing", "student", "shop", "store", "crm", "funnel", "sale", "lead", "workflow", "process", "service"]
    found_keywords = [kw for kw in keywords if kw in combined]
    score += len(found_keywords) * 2
    if len(a1) < 6 or "test" in combined or "dont know" in combined or "na" == a1.strip().lower():
        return "REJECT RECOMMENDATION", "Answers contain insufficient operational substance or placeholder text patterns."
    if score >= 5:
        return "ACCEPT RECOMMENDATION", f"Strong use-case profile match. Found targeted framework concepts: {', '.join(found_keywords[:3])}."
    else:
        return "REJECT RECOMMENDATION", "Low actionable use-case mapping. Content seems general or passive."

THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght=400;500;600;700&family=Syne:wght=700;800&display=swap');
:root {
    --bg: #090d16; --card: #111827; --fg: #f3f4f6; --muted: #9ca3af;
    --border: rgba(255,255,255,0.08); --teal: #2dd4bf; --cyan: #38bdf8; --red: #f43f5e; --amber: #f59e0b;
    --font-heading: 'Syne', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-body: 'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
}

.top-nav { position: fixed; top: 0; right: 0; left: 0; background: rgba(9,13,22,0.98); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: flex-end; align-items: center; gap: 1.5rem; z-index: 1000; }
.top-nav a { color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600; transition: color 0.2s; }
.top-nav a:hover { color: var(--teal); }
.top-nav a.amber { color: var(--amber); }
.top-nav a.red { color: var(--red); }

* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font-body); background: var(--bg); color: var(--fg); padding: 80px 1rem 2rem 1rem; max-width: 1200px; margin: 0 auto; line-height: 1.6; font-size: 16px; }
h1 { font-family: var(--font-heading); font-size: 2.2rem; font-weight: 800; color: #fff; margin-bottom: 1rem; letter-spacing: -0.03em; }
h2 { font-family: var(--font-heading); font-size: 1.6rem; font-weight: 700; color: #fff; margin-bottom: 1.2rem; }
h3 { font-family: var(--font-heading); font-size: 1.25rem; font-weight: 700; color: #fff; margin-bottom: 1rem; }
.card { background: var(--card); border: 1px solid var(--border); padding: 1.5rem 1.5rem 0.5rem 1.5rem; border-radius: 8px; margin-bottom: 1.5rem; }
.form-group { margin-bottom: 1.25rem; }
label { display: block; font-size: 0.85rem; font-weight: 700; margin-bottom: 0.5rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
input, select, textarea { font-family: var(--font-body); width: 100%; padding: 0.85rem; background: #0b0f19; border: 1px solid var(--border); color: #fff; border-radius: 6px; font-size: 1rem; }
input:focus, select:focus, textarea:focus { border-color: var(--teal); outline: none; }
button { font-family: var(--font-heading); width: 100%; padding: 1rem; background: linear-gradient(90deg, #0f766e, var(--teal)); border: none; color: #090d16; font-weight: 800; border-radius: 6px; cursor: pointer; text-transform: uppercase; letter-spacing: 0.05em; font-size: 1rem; }
button:hover { opacity: 0.9; }
.btn-small { padding: 0.5rem 1rem; font-size: 0.85rem; width: auto; display: inline-block; }
.btn-red { background: linear-gradient(90deg, #9f1239, var(--red)); color: #fff; }
.status-badge { display: inline-block; padding: 0.2rem 0.5rem; font-size: 0.75rem; font-weight: 800; border-radius: 4px; text-transform: uppercase; }
.status-open { background: rgba(45,212,191,0.1); color: var(--teal); }
.status-closed { background: rgba(244,63,94,0.1); color: var(--red); }
.nav-link { color: var(--muted); text-decoration: none; font-size: 0.95rem; }
.nav-link:hover { color: var(--teal); }

.split-layout { display: flex; flex-direction: row; gap: 2.5rem; margin-bottom: 1.5rem; align-items: flex-start; }
.left-content { flex: 1.3; min-width: 0; }
.right-sidebar { flex: 1; position: -webkit-sticky; position: sticky; top: 2rem; }

.meta-grid { display: grid; grid-template-columns: 1fr; gap: 0.75rem; margin: 1rem 0 1rem 0; background: rgba(255,255,255,0.02); padding: 1rem; border-radius: 6px; border: 1px solid var(--border); }
.meta-item { display: flex; font-size: 0.95rem; }
.meta-label { color: var(--teal); font-weight: 700; width: 120px; flex-shrink: 0; }
.itinerary-step { border-left: 2px solid var(--border); padding-left: 1rem; margin-bottom: 0.75rem; position: relative; font-size: 0.95rem; }
.itinerary-step::before { content: ""; position: absolute; left: -6px; top: 6px; width: 10px; height: 10px; background: var(--cyan); border-radius: 50%; }
.hero-banner { width: 100%; height: 240px; object-fit: cover; border-radius: 8px; margin-bottom: 1.5rem; border: 1px solid var(--border); }
.map-footer-container { width: 100%; height: 200px; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); background: #090d16; margin-top: 0.75rem; filter: grayscale(1) invert(0.92) contrast(1.25); }
.map-footer-container iframe { width: 100%; height: 100%; border: 0; }
.table-container { width: 100%; overflow-x: auto; margin-top: 1rem; border-radius: 6px; border: 1px solid var(--border); }
.table-bookings { width: 100%; border-collapse: collapse; text-align: left; background: var(--card); }
.table-bookings th, .table-bookings td { padding: 1rem; border-bottom: 1px solid var(--border); font-size: 0.95rem; }
.table-bookings th { background: rgba(255,255,255,0.03); color: #fff; font-weight: 700; }
.session-block-container { border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; margin-bottom: 1rem; }
.session-block-container:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
@media (max-width: 850px) {
    .split-layout { flex-direction: column; gap: 1.5rem; }
    .right-sidebar { position: static; width: 100%; }
    .hero-banner { height: 160px; }
}
"""

def safe_application(environ, start_response):
    if environ.get("PATH_INFO", "").startswith("/action-plan"):
        from action_plan_handler import action_plan_application
        return action_plan_application(environ, start_response)
    
    if environ.get("PATH_INFO", "").startswith("/budget-controller"):
        try:
            try:
                import budget_controller
            except Exception:
                pass
        except Exception as e:
            pass # Budget module failed to load
        return budget_controller.application(environ, start_response)
    init_db()
    method = environ.get('REQUEST_METHOD', 'GET')
    path_info = environ.get('PATH_INFO', '')
    query_string = environ.get('QUERY_STRING', '')
    query_params = parse_qs(query_string) if query_string else {}
    
    is_accounting_route = 'accounting-dashboard' in path_info or 'accounting-dashboard' in query_string
    is_backend = query_params.get('admin', ['false'])[0] == 'true' or is_accounting_route

    # Secure Signed Session Extraction
    cookie_str = environ.get('HTTP_COOKIE', '')
    auth_user = None
    if "auth_user=" in cookie_str:
        for cookie_part in cookie_str.split(';'):
            if "auth_user=" in cookie_part.strip():
                c_val = cookie_part.strip().split('=', 1)[1]
                auth_user = verify_signed_cookie(c_val)

    is_authenticated = auth_user is not None

    post_params = {}
    if method == 'POST':
        try:
            content_length = int(environ.get('CONTENT_LENGTH', 0) or 0)
            if content_length > MAX_CONTENT_LENGTH:
                start_response('413 Payload Too Large', [('Content-Type', 'text/plain')])
                return [b"Payload size limit exceeded."]
            request_body = environ['wsgi.input'].read(content_length).decode('utf-8')
            post_params = parse_qs(request_body)
        except Exception:
            pass

    action = post_params.get('action', [query_params.get('action', ['none'])[0]])[0]
    
    if is_accounting_route and is_authenticated:
        try:
            try:
                import accounting
            except Exception:
                pass
        except Exception as e:
            pass # Accounting module failed to load
        return accounting.application(environ, start_response)

    response_headers = [('Content-Type', 'text/html; charset=utf-8')]
    status = '200 OK'
    html_output = ""

    conn = get_db()
    cursor = conn.cursor()

    current_user_role = "MANAGER"
    if is_authenticated:
        cursor.execute("SELECT role FROM system_users WHERE username = ?", (auth_user,))
        role_row = cursor.fetchone()
        if role_row:
            current_user_role = role_row['role']

    is_superadmin = (current_user_role == "SUPERADMIN")

    if method == 'POST':
        if action == 'login':
            user_input = post_params.get("username", [""])[0]
            pass_input = post_params.get("password", [""])[0]
            
            cursor.execute("SELECT failed_attempts, lockout_until, password_hash FROM system_users WHERE username = ?", (user_input,))
            user_record = cursor.fetchone()
            
            now_str = datetime.utcnow().isoformat()
            
            if user_record:
                if user_record['lockout_until'] and user_record['lockout_until'] > now_str:
                    html_output = f"<html><head><style>{THEME_CSS}</style></head><body><div class='card' style='max-width:400px; margin:10% auto; text-align:center;'><h2>Console Brute-Force Lockout</h2><p style='color:var(--red);'>Too many failed entry metrics. Account locked out.</p></div></body></html>"
                else:
                    if user_record['password_hash'] == hash_pass(pass_input):
                        cursor.execute("UPDATE system_users SET failed_attempts = 0, lockout_until = NULL WHERE username = ?", (user_input,))
                        conn.commit()
                        
                        status = '302 Found'
                        target_redirect = '/book-now?admin=true' if not is_accounting_route else '/book-now?accounting-dashboard=true'
                        secure_token = sign_cookie_value(user_input)
                        response_headers = [
                            ('Location', target_redirect), 
                            ('Set-Cookie', f"auth_user={secure_token}; Path=/; HttpOnly; Secure; SameSite=Lax")
                        ]
                        conn.close()
                        start_response(status, response_headers)
                        return [b""]
                    else:
                        new_failures = (user_record['failed_attempts'] or 0) + 1
                        lock_until_str = None
                        if new_failures >= BRUTE_FORCE_LIMIT:
                            lock_until_str = (datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                        
                        cursor.execute("UPDATE system_users SET failed_attempts = ?, lockout_until = ? WHERE username = ?", (new_failures, lock_until_str, user_input))
                        conn.commit()
                        html_output = "<html><head><style>" + THEME_CSS + "</style></head><body><div class='card' style='max-width:400px; margin:10% auto; text-align:center;'><h2>Invalid Credentials</h2><a href='/book-now?admin=true' style='color:var(--teal);'>Retry Access Platform</a></div></body></html>"
            else:
                html_output = "<html><head><style>" + THEME_CSS + "</style></head><body><div class='card' style='max-width:400px; margin:10% auto; text-align:center;'><h2>Invalid Credentials</h2><a href='/book-now?admin=true' style='color:var(--teal);'>Retry Access Platform</a></div></body></html>"

        elif action == 'add-user' and is_authenticated and is_superadmin:
            new_username = clean_input(post_params.get("new_username", [""])[0])
            new_password = post_params.get("new_password", [""])[0]
            new_role = post_params.get("new_role", ["MANAGER"])[0]
            if new_username and new_password:
                try:
                    cursor.execute("INSERT INTO system_users (username, password_hash, role, failed_attempts) VALUES (?, ?, ?, 0)", 
                                   (new_username, hash_pass(new_password), new_role))
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
            status = '302 Found'
            response_headers = [('Location', '/book-now?admin=true')]
            conn.close()
            start_response(status, response_headers)
            return [b""]

        elif action == 'update-program' and is_authenticated and is_superadmin:
            cursor.execute("""
                UPDATE program_config 
                SET title = ?, description = ?, header_img = ?, expectations = ?, q1_label = ?, q2_label = ?
                WHERE id = (SELECT id FROM program_config ORDER BY id DESC LIMIT 1)
            """, (
                post_params.get("title", [""])[0], post_params.get("description", [""])[0],
                post_params.get("header_img", [""])[0], post_params.get("expectations", [""])[0],
                post_params.get("q1_label", [""])[0], post_params.get("q2_label", [""])[0]
            ))
            conn.commit()
            status = '302 Found'
            response_headers = [('Location', '/book-now?admin=true')]
            conn.close()
            start_response(status, response_headers)
            return [b""]

        elif action == 'add-date' and is_authenticated and is_superadmin:
            raw_date = post_params.get("new_date", [""])[0]
            new_cap = post_params.get("new_cap", ["15"])[0]
            new_price = post_params.get("new_price", ["0.00"])[0]
            lab_input = clean_input(post_params.get("lab", [""])[0])
            title_input = clean_input(post_params.get("custom_title", [""])[0])
            
            if raw_date:
                try:
                    dt = datetime.strptime(raw_date, "%Y-%m-%d")
                    final_title = title_input if title_input else dt.strftime("%b %d (%a) - Live Production Session")
                    
                    cursor.execute("""
                        INSERT INTO cohort_dates (date_key, label, open, cap, booked, venue, time_window, map_address, itinerary, lab, custom_title)
                        VALUES (?, ?, 1, ?, 0, ?, ?, ?, ?, ?, ?)
                    """, (raw_date, final_title, int(new_cap), "AI Experience Center Main Lab", f"09:00 AM - 04:00 PM PHT||{new_price}", "", "", lab_input, title_input))
                    conn.commit()
                except Exception:
                    pass
            status = '302 Found'
            response_headers = [('Location', '/book-now?admin=true')]
            conn.close()
            start_response(status, response_headers)
            return [b""]

        elif action == 'update-date' and is_authenticated and is_superadmin:
            key = post_params.get("date_key", [""])[0]
            open_param = 1 if post_params.get("open", ["false"])[0] == "true" else 0
            cap_param = int(post_params.get("cap", ["15"])[0])
            venue_param = clean_input(post_params.get("venue", [""])[0])
            submitted_time = clean_input(post_params.get("time_window", [""])[0])
            submitted_price = clean_input(post_params.get("session_price", ["0.00"])[0])
            time_window_param = f"{submitted_time}||{submitted_price}"
            map_param = clean_input(post_params.get("map_address", [""])[0])
            iti_param = clean_input(post_params.get("itinerary", [""])[0])
            lab_param = clean_input(post_params.get("lab", [""])[0])
            title_param = clean_input(post_params.get("custom_title", [""])[0])
            
            if not title_param:
                try:
                    dt = datetime.strptime(key, "%Y-%m-%d")
                    label_param = dt.strftime("%b %d (%a) - Live Production Session")
                except Exception:
                    label_param = key
            else:
                label_param = title_param

            cursor.execute("""
                UPDATE cohort_dates 
                SET open = ?, cap = ?, venue = ?, time_window = ?, map_address = ?, itinerary = ?, label = ?, lab = ?, custom_title = ?
                WHERE date_key = ?
            """, (open_param, cap_param, venue_param, time_window_param, map_param, iti_param, label_param, lab_param, title_param, key))
            conn.commit()
            status = '302 Found'
            response_headers = [('Location', '/book-now?admin=true')]
            conn.close()
            start_response(status, response_headers)
            return [b""]

        elif action in ['approve-seat', 'reject-seat', 'delete-date', 'complete-date'] and is_authenticated:
            if action in ['delete-date', 'complete-date'] and not is_superadmin:
                html_output = "Unprivileged Operation Context Blocked."
            elif action == 'approve-seat':
                b_id = post_params.get("booking_idx", ["-1"])[0]
                cursor.execute("SELECT * FROM participant_bookings WHERE id = ?", (b_id,))
                b = cursor.fetchone()
                if b and b['status'] == "PENDING":
                    cursor.execute("UPDATE cohort_dates SET booked = booked + 1 WHERE date_key = ?", (b['date_key'],))
                    cursor.execute("UPDATE participant_bookings SET status = 'APPROVED' WHERE id = ?", (b_id,))
            elif action == 'reject-seat':
                b_id = post_params.get("booking_idx", ["-1"])[0]
                cursor.execute("UPDATE participant_bookings SET status = 'REJECTED' WHERE id = ?", (b_id,))
            elif action == 'delete-date':
                key = post_params.get("date_key", [""])[0]
                cursor.execute("DELETE FROM participant_bookings WHERE date_key = ?", (key,))
                cursor.execute("DELETE FROM cohort_dates WHERE date_key = ?", (key,))
            elif action == 'complete-date':
                key = post_params.get("date_key", [""])[0]
                cursor.execute("UPDATE participant_bookings SET status = 'COMPLETED' WHERE date_key = ? AND status = 'APPROVED'", (key,))
                cursor.execute("UPDATE cohort_dates SET open = 0 WHERE date_key = ?", (key,))
            
            if not html_output:
                conn.commit()
                status = '302 Found'
                response_headers = [('Location', '/book-now?admin=true')]
                conn.close()
                start_response(status, response_headers)
                return [b""]

        elif action == 'book':
            name = clean_input(post_params.get("name", [""])[0])
            email = clean_input(post_params.get("email", [""])[0]).lower()
            phone = clean_input(post_params.get("phone", [""])[0])
            a1 = clean_input(post_params.get("a1", [""])[0])
            a2 = clean_input(post_params.get("a2", [""])[0])
            chosen_date = post_params.get("date", [""])[0]
            
            cursor.execute("SELECT * FROM cohort_dates WHERE date_key = ? AND open = 1", (chosen_date,))
            v = cursor.fetchone()
            if v and v['booked'] < v['cap']:
                rec_lbl, rec_reason = run_screener_assessment(a1, a2)
                cursor.execute("""
                    INSERT INTO participant_bookings (name, email, phone, a1, a2, date_key, status, rec_label, rec_reason)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """, (name, email, phone, a1, a2, chosen_date, rec_lbl, rec_reason))
                conn.commit()
                html_output = "<html><head><style>" + THEME_CSS + "</style></head><body><div class='card' style='max-width:500px; margin:10% auto; text-align:center;'><h2>Application Submitted Successfully</h2><p style='color:var(--teal); margin-top:1rem;'>Our engineering panel is assessing your framework entry metrics.</p></div></body></html>"
            else:
                html_output = "Allocation Error: Target session invalid or closed."

    if not html_output:
        if is_backend:
            if action == 'logout':
                status = '302 Found'
                response_headers = [('Location', '/book-now?admin=true'), ('Set-Cookie', "auth_user=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT")]
                conn.close()
                start_response(status, response_headers)
                return [b""]

            if not is_authenticated:
                html_output = f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{THEME_CSS}</style></head><body>
                    <div class="card" style="max-width:450px; margin: 15% auto;">
                        <h2>Central Gateway Sign-In</h2>
                        <form method="POST" action="{environ.get('REQUEST_URI', '/book-now?admin=true')}">
                            <input type="hidden" name="action" value="login">
                            <div class="form-group"><label>Username ID</label><input type="text" name="username" required></div>
                            <div class="form-group"><label>Password Token</label><input type="password" name="password" required></div>
                            <button type="submit">Unlock System Command</button>
                        </form>
                    </div></body></html>"""
            else:
                cursor.execute("SELECT * FROM program_config ORDER BY id DESC LIMIT 1")
                prog = cursor.fetchone()
                
                date_rows = ""
                cursor.execute("SELECT * FROM cohort_dates ORDER BY date_key ASC")
                for v in cursor.fetchall():
                    is_open_bool = int(v['open']) == 1
                    status_lbl = "OPEN" if is_open_bool else "CLOSED"
                    badge_class = "status-open" if is_open_bool else "status-closed"
                    
                    raw_time = v['time_window'] or ''
                    if '||' in raw_time:
                        time_display, extracted_price = raw_time.split('||', 1)
                    else:
                        time_display = raw_time
                        extracted_price = '0.00'
                    
                    admin_actions_html = ""
                    if is_superadmin:
                        admin_actions_html = f"""
                        <form method="POST" action="/book-now?admin=true" style="margin:0;" onsubmit="return confirm('Archive registrations and complete session?');">
                            <input type="hidden" name="action" value="complete-date">
                            <input type="hidden" name="date_key" value="{html.escape(v['date_key'])}">
                            <button type="submit" class="btn-small" style="background:var(--cyan); color:#090d16;">Archive/Complete</button>
                        </form>
                        <form method="POST" action="/book-now?admin=true" style="margin:0;" onsubmit="return confirm('Are you sure you want to completely erase this schedule?');">
                            <input type="hidden" name="action" value="delete-date">
                            <input type="hidden" name="date_key" value="{html.escape(v['date_key'])}">
                            <button type="submit" class="btn-small btn-red">Remove</button>
                        </form>"""

                    date_rows += f"""
                    <div class="card" style="padding:1.25rem; margin-bottom:1rem;">
                        <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:0.5rem; margin-bottom:1rem;">
                            <div style="font-weight:700; font-size:1.1rem;">{html.escape(v['label'] or '')} <span class="status-badge {badge_class}">{status_lbl}</span></div>
                            <div style="display:flex; gap:0.5rem;">
                                {admin_actions_html}
                            </div>
                        </div>
                        <form method="POST" action="/book-now?admin=true" style="margin:0;">
                            <input type="hidden" name="action" value="update-date">
                            <input type="hidden" name="date_key" value="{html.escape(v['date_key'])}">
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:1rem; margin-bottom:1rem;">
                                <div><label>Custom Session Title</label><input type="text" name="custom_title" value="{html.escape(v['custom_title'] or '')}" {"" if is_superadmin else "disabled"}></div>
                                <div><label>LAB Identifier</label><input type="text" name="lab" value="{html.escape(v['lab'] or '')}" {"" if is_superadmin else "disabled"}></div>
                                <div>
                                    <label>Status</label>
                                    <select name="open" {"" if is_superadmin else "disabled"}>
                                        <option value="true" {"selected" if is_open_bool else ""}>Open Slots</option>
                                        <option value="false" {"selected" if not is_open_bool else ""}>Close Slots</option>
                                    </select>
                                </div>
                            </div>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:1rem; margin-bottom:1rem;">
                                <div><label>Seat Capacity</label><input type="number" name="cap" value="{v['cap']}" {"" if is_superadmin else "disabled"}></div>
                                <div><label>Venue Title Label</label><input type="text" name="venue" value="{html.escape(v['venue'] or '')}" {"" if is_superadmin else "disabled"}></div>
                                <div><label>Time Window</label><input type="text" name="time_window" value="{html.escape(time_display)}" {"" if is_superadmin else "disabled"}></div>
                                <div><label>Session Price (₱)</label><input type="number" name="session_price" value="{html.escape(extracted_price)}" step="0.01" {"" if is_superadmin else "disabled"}></div>
                            </div>
                            <div class="form-group">
                                <label>Google Maps Target Address</label>
                                <input type="text" name="map_address" value="{html.escape(v['map_address'] or '')}" {"" if is_superadmin else "disabled"}>
                            </div>
                            <div class="form-group">
                                <label>Itinerary Breakdown (One step per line)</label>
                                <textarea name="itinerary" rows="3" {"" if is_superadmin else "disabled"}>{html.escape(v['itinerary'] or '')}</textarea>
                            </div>
                            {"<button type='submit' class='btn-small'>Save Session Settings</button>" if is_superadmin else ""}
                        </form>
                    </div>"""

                user_management_section = ""
                global_config_section = ""
                create_cohort_section = ""

                if is_superadmin:
                    user_rows = ""
                    cursor.execute("SELECT username, role FROM system_users ORDER BY username ASC")
                    for u in cursor.fetchall():
                        user_rows += f"<tr><td><strong>{html.escape(u['username'])}</strong></td><td>{html.escape(u['role'])}</td></tr>"

                    user_management_section = f"""
                    <div class="card">
                        <h3>Centralized User Access Management</h3>
                        <form method="POST" action="/book-now?admin=true" style="margin-bottom:1.5rem;">
                            <input type="hidden" name="action" value="add-user">
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:1rem; margin-bottom:1rem;">
                                <div><label>New Username</label><input type="text" name="new_username" required></div>
                                <div><label>Temporary Password</label><input type="password" name="new_password" required></div>
                                <div>
                                    <label>Access Level Role</label>
                                    <select name="new_role">
                                        <option value="SUPERADMIN">Superadmin (All Privileges)</option>
                                        <option value="MANAGER">Manager (Auditor Status)</option>
                                    </select>
                                </div>
                            </div>
                            <button type="submit" class="btn-small">Provision System Account</button>
                        </form>
                        <div class="table-container">
                            <table class="table-bookings">
                                <thead><tr><th>User Scope ID</th><th>Assigned Authorization Role</th></tr></thead>
                                <tbody>{user_rows}</tbody>
                            </table>
                        </div>
                    </div>"""

                    global_config_section = f"""
                    <div class="card">
                        <h3>Global Configuration</h3>
                        <form method="POST" action="/book-now?admin=true">
                            <input type="hidden" name="action" value="update-program">
                            <div class="form-group"><label>Program Title</label><input type="text" name="title" value="{html.escape(prog['title'] or '')}"></div>
                            <div class="form-group"><label>Description</label><textarea name="description" rows="3">{html.escape(prog['description'] or '')}</textarea></div>
                            <div class="form-group"><label>Header Image URL</label><input type="text" name="header_img" value="{html.escape(prog['header_img'] or '')}"></div>
                            <div class="form-group"><label>Expectations</label><textarea name="expectations" rows="2">{html.escape(prog['expectations'] or '')}</textarea></div>
                            <div class="form-group"><label>Question 1 Label</label><input type="text" name="q1_label" value="{html.escape(prog['q1_label'] or '')}"></div>
                            <div class="form-group"><label>Question 2 Label</label><input type="text" name="q2_label" value="{html.escape(prog['q2_label'] or '')}"></div>
                            <button type="submit" class="btn-small">Update Dynamic Platform Content</button>
                        </form>
                    </div>"""

                    create_cohort_section = f"""
                    <div class="card">
                        <h3>Create New Cohort Window</h3>
                        <form method="POST" action="/book-now?admin=true">
                            <input type="hidden" name="action" value="add-date">
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:1rem; margin-bottom:1rem;">
                                <div><label>Custom Session Title</label><input type="text" name="custom_title" placeholder="e.g. LLM Finetuning Deep Dive"></div>
                                <div><label>LAB Identifier</label><input type="text" name="lab" placeholder="e.g. Lab Alpha"></div>
                            </div>
                            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:1rem; margin-bottom:1rem;">
                                <div><label>Select Calendar Date</label><input type="date" name="new_date" required></div>
                                <div><label>Seat Limit Capacity</label><input type="number" name="new_cap" value="15" min="1" required></div>
                                <div><label>Base Session Price (₱)</label><input type="number" name="new_price" value="0.00" step="0.01" required></div>
                            </div>
                            <button type="submit" class="btn-small">Instantiate Live Session Date</button>
                        </form>
                    </div>"""

                booking_rows = ""
                cursor.execute("""
                    SELECT b.id, b.name, b.email, b.phone, b.status, b.rec_label, b.date_key, c.label as date_label 
                    FROM participant_bookings b
                    LEFT JOIN cohort_dates c ON b.date_key = c.date_key
                    WHERE b.status != 'COMPLETED'
                    ORDER BY b.id DESC
                """)
                for b in cursor.fetchall():
                    current_status = b['status']
                    if current_status == "PENDING":
                        rec_lbl = b['rec_label'] or "UNASSESSED"
                        rec_color = "var(--teal)" if "ACCEPT" in rec_lbl else "var(--red)"
                        rec_badge = f"""<br><span style="font-size:0.75rem; color:{rec_color}; font-weight:700;">🤖 SYSTEM: {rec_lbl}</span>"""
                        action_buttons = f"""
                        <div style="display:flex; gap:0.5rem;">
                            <form method="POST" action="/book-now?admin=true" style="margin:0;">
                                <input type="hidden" name="action" value="approve-seat">
                                <input type="hidden" name="booking_idx" value="{b['id']}">
                                <button type="submit" class="btn-small" style="padding:0.4rem;">Approve</button>
                            </form>
                            <form method="POST" action="/book-now?admin=true" style="margin:0;">
                                <input type="hidden" name="action" value="reject-seat">
                                <input type="hidden" name="booking_idx" value="{b['id']}">
                                <button type="submit" class="btn-small btn-red" style="padding:0.4rem;">Reject</button>
                            </form>
                        </div>"""
                    else:
                        action_buttons = f"<span>{current_status}</span>"
                        rec_badge = ""

                    booking_rows += f"""
                    <tr>
                        <td><strong>{html.escape(b['name'] or '')}</strong>{rec_badge}</td>
                        <td>{html.escape(b['email'] or '')}</td>
                        <td>{html.escape(b['phone'] or '')}</td>
                        <td>{html.escape(b['date_label'] or b['date_key'] or '')}</td>
                        <td>{action_buttons}</td>
                    </tr>"""

                html_output = f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{THEME_CSS}</style></head><body>
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:2rem; border-bottom:1px solid var(--border); padding-bottom:1rem;">
                        <div>
                            <h2>Control Console</h2>
                            <span style="font-size:0.8rem; color:var(--muted)">Signed in as: <strong>{html.escape(auth_user)}</strong> ({current_user_role})</span>
                        </div>
                        <div style="display:flex; gap:1rem; align-items:center;">
                            <a href="/action-plan" class="nav-link" style="color:var(--cyan); font-weight:700;">Action Plan</a>
                         <a href="/book-now?accounting-dashboard=true" class="nav-link" style="color:var(--amber); font-weight:700;">Accounting Ledger →</a>
                            <a href="/book-now?admin=true&action=logout" class="nav-link" style="color:var(--red);">Log Out</a>
                        </div>
                    </div>
                    
                    {user_management_section}
                    {global_config_section}
                    {create_cohort_section}

                    <h2>Active Production Sessions</h2>{date_rows}
                    <h2>Live Rosters</h2>
                    <div class="table-container"><table class='table-bookings'><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Date</th><th>Action</th></tr></thead><tbody>{booking_rows}</tbody></table></div></body></html>"""
        else:
            cursor.execute("SELECT * FROM program_config ORDER BY id DESC LIMIT 1")
            prog = cursor.fetchone()
            
            expectations_html = ""
            if prog['expectations']:
                expectations_html = "".join(f"<li style='margin-bottom:0.5rem;'>{html.escape(item.strip())}</li>" for item in prog['expectations'].split(";") if item.strip())
            
            options = ""
            cursor.execute("SELECT * FROM cohort_dates WHERE open = 1 ORDER BY date_key ASC")
            active_cohorts = cursor.fetchall()
            
            for v in active_cohorts:
                if v['booked'] < v['cap']:
                    options += f'<option value="{html.escape(v["date_key"])}">{html.escape(v["label"] or "")}</option>'

            sessions_overview_html = ""
            if active_cohorts:
                sessions_overview_html += '<h2 style="margin-top:2rem; border-top:1px solid var(--border); padding-top:1.5rem;">Available Session Timetables</h2>'
                for idx, cohort in enumerate(active_cohorts):
                    raw_time = cohort['time_window'] or ''
                    if '||' in raw_time:
                        time_display, extracted_price = raw_time.split('||', 1)
                    else:
                        time_display = raw_time
                        extracted_price = '0.00'
                    
                    cohort_itinerary = ""
                    if cohort['itinerary']:
                        for step in cohort['itinerary'].split('\n'):
                            if step.strip():
                                cohort_itinerary += f"<div class='itinerary-step'>{html.escape(step.strip())}</div>"
                    
                    cohort_map = ""
                    if cohort['map_address']:
                        cohort_map = f"""<div class="map-footer-container"><iframe src="https://maps.google.com/maps?q={html.escape(cohort['map_address'])}&t=&z=13&ie=UTF8&iwloc=&output=embed"></iframe></div>"""

                    lab_meta_item = ""
                    if cohort['lab']:
                        lab_meta_item = f"""<div class="meta-item"><span class="meta-label">Lab Focus:</span><span style="color:var(--cyan);">{html.escape(cohort['lab'])}</span></div>"""

                    sessions_overview_html += f"""
                    <div class="session-block-container">
                        <h3 style="color:var(--cyan); margin-bottom:0.25rem;">{html.escape(cohort['label'] or '')}</h3>
                        <div class="meta-grid">
                            {lab_meta_item}
                            <div class="meta-item"><span class="meta-label">Venue:</span><span>{html.escape(cohort['venue'] or '')}</span></div>
                            <div class="meta-item"><span class="meta-label">Schedule:</span><span>{html.escape(time_display)}</span></div>
                            <div class="meta-item"><span class="meta-label">Session Fee:</span><span style="color:var(--teal); font-weight:700;">₱{float(extracted_price):,.2f}</span></div>
                            <div class="meta-item"><span class="meta-label">Availability:</span><span>{cohort['cap'] - cohort['booked']} seats remaining / {cohort['cap']} limit</span></div>
                        </div>
                        {cohort_itinerary}
                        {cohort_map}
                    </div>"""
            else:
                sessions_overview_html = "<p style='color:var(--muted); margin-top:2rem;'>No active engineering sessions scheduled at this time.</p>"

            html_output = f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><style>{THEME_CSS}</style></head><body>
                
<div class="top-nav">
    <a href="/book-now?admin=true">Admin Login</a>
</div>

             <div class="split-layout">
                    <div class="left-content">
                        {f'<img class="hero-banner" src="{html.escape(prog["header_img"])}">' if prog['header_img'] else ''}
                        <h1>{html.escape(prog['title'] or '')}</h1>
                        <p style="margin-bottom:1.5rem; color:var(--muted);">{html.escape(prog['description'] or '')}</p>
                        
                        {f'<h3>What You Will Architect</h3><ul style="padding-left:1.25rem; margin-bottom:1.5rem; color:var(--fg);">{expectations_html}</ul>' if expectations_html else ''}
                        
                        {sessions_overview_html}
                    </div>
                    <div class="right-sidebar">
                        <div class="card">
                            <h2>Pre-Register</h2>
                            <form method="POST" action="/book-now">
                                <input type="hidden" name="action" value="book">
                                <div class="form-group"><label>Target Session Date</label><select name="date">{options}</select></div>
                                <div class="form-group"><label>Full Name</label><input type="text" name="name" required></div>
                                <div class="form-group"><label>Email Address</label><input type="email" name="email" required></div>
                                <div class="form-group"><label>Phone Contact</label><input type="text" name="phone" required></div>
                                <div class="form-group"><label>{html.escape(prog['q1_label'] or '')}</label><textarea name="a1" required></textarea></div>
                                <div class="form-group"><label>{html.escape(prog['q2_label'] or '')}</label><textarea name="a2" required></textarea></div>
                                <button type="submit">Submit Application</button>
                            </form>
                        </div>
                    </div>
                </div></body></html>"""

    conn.close()
    start_response(status, response_headers)
    return [html_output.encode('utf-8')]

def application(environ, start_response):
    try:
        return safe_application(environ, start_response)
    except Exception as e:
        with open(CRASH_LOG, "w") as f:
            f.write(traceback.format_exc())
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [b"Internal Server Error."]
