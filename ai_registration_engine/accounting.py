import os
import sqlite3
import html
import traceback

BASE_DIR = "/home/vsmwrurd/ai_registration_engine"
DB_FILE = os.path.join(BASE_DIR, "booking_storage.db")
CRASH_LOG = os.path.join(BASE_DIR, "accounting_crash_log.txt")

THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap');
:root {
    --bg: #090d16; --card: #111827; --fg: #f3f4f6; --muted: #9ca3af;
    --border: rgba(255,255,255,0.08); --teal: #2dd4bf; --cyan: #38bdf8; --amber: #f59e0b; --red: #f43f5e;
    --font-heading: 'Syne', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-body: 'Space Grotesk', -apple-system, BlinkMacSystemFont, sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font-body); background: var(--bg); color: var(--fg); padding: 80px 1rem 2rem 1rem; max-width: 1200px; margin: 0 auto; line-height: 1.6; }
h1 { font-family: var(--font-heading); font-size: 2.2rem; font-weight: 800; color: #fff; margin-bottom: 1.5rem; letter-spacing: -0.03em; }
h2 { font-family: var(--font-heading); font-size: 1.5rem; font-weight: 700; color: #fff; margin-bottom: 1rem; }
.nav-link { color: var(--muted); text-decoration: none; font-size: 0.95rem; font-family: var(--font-body); }
.nav-link:hover { color: var(--teal); }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.5rem; margin-bottom: 2.5rem; }
.metric-card { background: var(--card); border: 1px solid var(--border); padding: 1.5rem; border-radius: 8px; border-left: 4px solid var(--teal); }
.metric-card.amber { border-left-color: var(--amber); }
.metric-card.cyan { border-left-color: var(--cyan); }
.metric-label { font-size: 0.85rem; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem; font-family: var(--font-body); }
.metric-value { font-size: 2rem; font-weight: 800; color: #fff; font-family: var(--font-heading); }
.table-container { width: 100%; overflow-x: auto; border-radius: 6px; border: 1px solid var(--border); background: var(--card); }
.table-ledger { width: 100%; border-collapse: collapse; text-align: left; }
.table-ledger th, .table-ledger td { padding: 1rem; border-bottom: 1px solid var(--border); font-size: 0.95rem; font-family: var(--font-body); }
.table-ledger th { background: rgba(255,255,255,0.03); color: #fff; font-weight: 700; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.05em; font-family: var(--font-body); }
.top-nav { position: fixed; top: 0; right: 0; left: 0; background: rgba(9,13,22,0.98); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: flex-end; align-items: center; gap: 1.5rem; z-index: 1000; }
.top-nav a { color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600; font-family: var(--font-body); }
.top-nav a:hover { color: var(--teal); }
.top-nav a.amber { color: var(--amber); }
.top-nav a.red { color: var(--red); }
"""

NAV_HTML = """
<div class="top-nav">
    <a href="/book-now">Public View</a>
    <a href="/book-now?admin=true">Admin Console</a>
    <a href="/book-now?accounting-dashboard=true" class="amber">Accounting</a>
    <a href="/budget-controller">Budget</a>
    <a href="/book-now?admin=true&action=logout" class="red">Log Out</a>
</div>
"""

def safe_application(environ, start_response):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    price_map = {}
    cursor.execute("SELECT date_key, time_window FROM cohort_dates")
    for row in cursor.fetchall():
        raw_time = row['time_window'] or ''
        price_val = 0.0
        if '||' in raw_time:
            try:
                price_val = float(raw_time.split('||', 1)[1])
            except (ValueError, IndexError):
                price_val = 0.0
        price_map[row['date_key']] = price_val

    total_approved_revenue = 0.0
    total_pending_pipeline = 0.0
    approved_seats_count = 0
    pending_seats_count = 0

    ledger_rows = ""
    cursor.execute("""
        SELECT b.id, b.name, b.email, b.status, b.date_key, c.label as date_label
        FROM participant_bookings b
        LEFT JOIN cohort_dates c ON b.date_key = c.date_key
        ORDER BY b.id DESC
    """)
    
    for row in cursor.fetchall():
        status = row['status']
        date_key = row['date_key']
        seat_price = price_map.get(date_key, 0.0)

        if status == 'APPROVED':
            total_approved_revenue += seat_price
            approved_seats_count += 1
        elif status == 'PENDING':
            total_pending_pipeline += seat_price
            pending_seats_count += 1

        status_style = "color: var(--teal);" if status == 'APPROVED' else "color: var(--amber);" if status == 'PENDING' else "color: var(--muted);"
        
        ledger_rows += f"""
        <tr>
            <td>#{row['id']}</td>
            <td>{html.escape(row['name'] or '')}<br>{html.escape(row['email'] or '')}</td>
            <td>{html.escape(row['date_label'] or date_key or 'Unscheduled Frame')}</td>
            <td style="{status_style}">{status}</td>
            <td>${seat_price:,.2f}</td>
        </tr>
        """

    if not ledger_rows:
        ledger_rows = "<tr><td colspan='5' style='text-align:center; color:var(--muted);'>No operational ledger rows found.</td></tr>"

    html_output = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
        <style>{THEME_CSS}</style>
    </head>
    <body>
        {NAV_HTML}
        <h1>Accounting Ledger</h1>
        
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Realized Revenue</div>
                <div class="metric-value">${total_approved_revenue:,.2f}</div>
                <div style="font-size:0.85rem; color:var(--muted);">From {approved_seats_count} approved seats</div>
            </div>
            <div class="metric-card amber">
                <div class="metric-label">Pipeline</div>
                <div class="metric-value">${total_pending_pipeline:,.2f}</div>
                <div style="font-size:0.85rem; color:var(--muted);">From {pending_seats_count} pending reviews</div>
            </div>
            <div class="metric-card cyan">
                <div class="metric-label">Gross Bookings</div>
                <div class="metric-value">${(total_approved_revenue + total_pending_pipeline):,.2f}</div>
                <div style="font-size:0.85rem; color:var(--muted);">Total metric potential</div>
            </div>
        </div>
        
        <h2>Transaction Matrix Stream</h2>
        <div class="table-container">
            <table class="table-ledger">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Participant Profile</th>
                        <th>Target Frame Label</th>
                        <th>Review Status</th>
                        <th>Unit Pricing</th>
                    </tr>
                </thead>
                <tbody>
                    {ledger_rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """

    conn.close()
    start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8')])
    return [html_output.encode('utf-8')]

def application(environ, start_response):
    try:
        return safe_application(environ, start_response)
    except Exception as e:
        with open(CRASH_LOG, "w") as f:
            f.write(traceback.format_exc())
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [b"Internal Server Error in isolated metrics sub-module."]
