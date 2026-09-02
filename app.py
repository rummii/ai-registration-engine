import os
import hmac
import html
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, redirect, url_for, render_template, session, flash, g, jsonify
from functools import wraps
from config import SECRET_KEY, COOKIE_SECRET, MAX_CONTENT_LENGTH, BRUTE_FORCE_LIMIT, LOCKOUT_MINUTES, SESSION_HOURS
from db import get_db, hash_password, init_db, migrate_price_data

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

# --- Public Routes ---

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
        db.execute("UPDATE cohort_dates SET booked = booked + 1 WHERE date_key = ?", (booking['date_key'],))
        db.execute("UPDATE participant_bookings SET status = 'APPROVED' WHERE id = ?", (booking_id,))
        db.commit()
        flash('Booking approved.', 'success')
    
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

FINANCIAL_STRUCTURE = {
    "Other Expenses": ["Power", "Water", "IT", "Communication", "Stationery", "Service/Maintenance", "Misc", "Other"],
    "Promotion Expenses": ["Marketing", "Promotions", "Collaterals", "Printing/Advertising", "Travel", "Transportation"],
    "Payroll & Pilotage": ["Pilotage", "Payroll", "Misc", "Other"],
    "Fixed Costs": ["Rent", "Tax"]
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

@app.route('/admin/budget')
@login_required
def budget_controller():
    fiscal_year = int(request.args.get('year', datetime.now().year))
    
    db = get_db()
    
    # Initialize budget rows if needed
    for category, items in FINANCIAL_STRUCTURE.items():
        for item in items:
            for m in range(1, 13):
                db.execute("""
                    INSERT OR IGNORE INTO budget_forecast (fiscal_year, month_index, line_item_name, target_amount)
                    VALUES (?, ?, ?, 0.0)
                """, (fiscal_year, m, item))
                db.execute("""
                    INSERT OR IGNORE INTO budget_actuals_cache (fiscal_year, month_index, line_item_name, actual_amount)
                    VALUES (?, ?, ?, 0.0)
                """, (fiscal_year, m, item))
    
    # Load data
    forecast_data = {}
    actual_data = {}
    
    for row in db.execute("SELECT month_index, line_item_name, target_amount FROM budget_forecast WHERE fiscal_year = ?", (fiscal_year,)).fetchall():
        forecast_data.setdefault(row['line_item_name'], [0.0] * 12)
        forecast_data[row['line_item_name']][row['month_index'] - 1] = row['target_amount']
    
    for row in db.execute("SELECT month_index, line_item_name, actual_amount FROM budget_actuals_cache WHERE fiscal_year = ?", (fiscal_year,)).fetchall():
        actual_data.setdefault(row['line_item_name'], [0.0] * 12)
        actual_data[row['line_item_name']][row['month_index'] - 1] = row['actual_amount']
    
    # Get audit log
    audit_log = db.execute("""
        SELECT * FROM forecast_audit_log 
        WHERE fiscal_year = ?
        ORDER BY timestamp DESC
        LIMIT 50
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
                         is_superadmin=is_superadmin)

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
    app.run(debug=True)
