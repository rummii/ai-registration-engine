import os
import json
import sqlite3
import traceback
import html
from datetime import datetime

BASE_DIR = "/home/vsmwrurd/ai_registration_engine"
DB_FILE = os.path.join(BASE_DIR, "booking_storage.db")
CRASH_LOG = os.path.join(BASE_DIR, "budget_crash_log.txt")

FINANCIAL_STRUCTURE = {
    "Volume (Lbs)": ["Current Session Lbs", "Completed Session Lbs", "Total Operational Lbs"],
    "Other Revenue Dept": ["Retail", "Gear", "Transportation", "Events"],
    "Payroll & Pilotage fee": ["Pilotage", "Payroll", "Misc", "Other"],
    "Other Expenses": ["Power", "Water", "IT", "Communication", "Stationery", "Service/Maintainance", "Misc", "Other"],
    "Promotion Expenses": ["Marketing", "Promotions", "Colletrals", "Printing/Advertising", "Travel", "Transportation"],
    "Fixed Costs": ["Rent", "Tax"]
}

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

NAV_HTML = """
<div class="top-nav">
    <a href="/book-now">Public View</a>
    <a href="/book-now?admin=true">Admin Console</a>
    <a href="/book-now?accounting-dashboard=true" class="amber">Accounting</a>
    <a href="/budget-controller" class="amber">Budget</a>
    <a href="/action-plan" class="amber">Action Plan</a>
    <a href="/book-now?admin=true&action=logout" class="red">Log Out</a>
</div>
"""

def format_pesos(val):
    return f"₱{val:,.2f}"

def format_lbs(val):
    return f"{val:,.1f} Lbs"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_budget_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS budget_forecast (
        fiscal_year INTEGER, month_index INTEGER, line_item_name TEXT, target_amount REAL DEFAULT 0.0,
        PRIMARY KEY (fiscal_year, month_index, line_item_name))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS budget_actuals_cache (
        fiscal_year INTEGER, month_index INTEGER, line_item_name TEXT, actual_amount REAL DEFAULT 0.0,
        PRIMARY KEY (fiscal_year, month_index, line_item_name))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS forecast_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, username TEXT, fiscal_year INTEGER, month_index INTEGER,
        line_item_name TEXT, old_value REAL, new_value REAL
    )""")
    conn.commit()
    conn.close()

def sync_live_actuals(fiscal_year=2026):
    conn = get_db()
    cursor = conn.cursor()
    for category, items in FINANCIAL_STRUCTURE.items():
        for item in items:
            for m in range(1, 13):
                cursor.execute("INSERT OR IGNORE INTO budget_actuals_cache (fiscal_year, month_index, line_item_name, actual_amount) VALUES (?, ?, ?, 0.0)", (fiscal_year, m, item))
                cursor.execute("INSERT OR IGNORE INTO budget_forecast (fiscal_year, month_index, line_item_name, target_amount) VALUES (?, ?, ?, 0.0)", (fiscal_year, m, item))
    try:
        cursor.execute("SELECT strftime('%m', session_date) as m_idx, SUM(weight_lbs) as lbs_total FROM operational_sessions WHERE status='CURRENT' AND strftime('%Y', session_date) = ? GROUP BY m_idx", (str(fiscal_year),))
        for row in cursor.fetchall():
            if row['m_idx']:
                cursor.execute("UPDATE budget_actuals_cache SET actual_amount = ? WHERE fiscal_year = ? AND month_index = ? AND line_item_name = 'Current Session Lbs'", (float(row['lbs_total']), fiscal_year, int(row['m_idx'])))
        cursor.execute("SELECT strftime('%m', session_date) as m_idx, SUM(weight_lbs) as lbs_total FROM operational_sessions WHERE status='COMPLETED' AND strftime('%Y', session_date) = ? GROUP BY m_idx", (str(fiscal_year),))
        for row in cursor.fetchall():
            if row['m_idx']:
                cursor.execute("UPDATE budget_actuals_cache SET actual_amount = ? WHERE fiscal_year = ? AND month_index = ? AND line_item_name = 'Completed Session Lbs'", (float(row['lbs_total']), fiscal_year, int(row['m_idx'])))
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def compute_financial_matrices(fiscal_year=2026):
    conn = get_db()
    cursor = conn.cursor()
    data = {
        "forecast": {cat: {item: [0.0]*12 for item in items} for cat, items in FINANCIAL_STRUCTURE.items()},
        "actual": {cat: {item: [0.0]*12 for item in items} for cat, items in FINANCIAL_STRUCTURE.items()}
    }
    totals = {tk: {"Total Lbs Volume": [0.0]*12, "Total Other Revenue": [0.0]*12, "Total Operating Cost": [0.0]*12, "GOP": [0.0]*12} for tk in ["forecast", "actual"]}
    
    for tk, table in [("forecast", "budget_forecast"), ("actual", "budget_actuals_cache")]:
        cursor.execute(f"SELECT month_index, line_item_name, {'target_amount' if tk=='forecast' else 'actual_amount'} FROM {table} WHERE fiscal_year=?", (fiscal_year,))
        for row in cursor.fetchall():
            m = int(row['month_index']) - 1
            item = row['line_item_name']
            for cat, items in FINANCIAL_STRUCTURE.items():
                if item in items:
                    data[tk][cat][item][m] = float(row[2])
    conn.close()
    
    for tk in ["forecast", "actual"]:
        for m in range(12):
            current_lbs = data[tk]["Volume (Lbs)"]["Current Session Lbs"][m]
            completed_lbs = data[tk]["Volume (Lbs)"]["Completed Session Lbs"][m]
            total_lbs = current_lbs + completed_lbs
            data[tk]["Volume (Lbs)"]["Total Operational Lbs"][m] = total_lbs
            
            other_rev = sum(data[tk]["Other Revenue Dept"][item][m] for item in FINANCIAL_STRUCTURE["Other Revenue Dept"])
            payroll = sum(data[tk]["Payroll & Pilotage fee"][item][m] for item in FINANCIAL_STRUCTURE["Payroll & Pilotage fee"])
            expenses = sum(data[tk]["Other Expenses"][item][m] for item in FINANCIAL_STRUCTURE["Other Expenses"])
            promo = sum(data[tk]["Promotion Expenses"][item][m] for item in FINANCIAL_STRUCTURE["Promotion Expenses"])
            fixed = sum(data[tk]["Fixed Costs"][item][m] for item in FINANCIAL_STRUCTURE["Fixed Costs"])
            
            total_operating_cost = payroll + expenses + promo + fixed
            
            totals[tk]["Total Lbs Volume"][m] = total_lbs
            totals[tk]["Total Other Revenue"][m] = other_rev
            totals[tk]["Total Operating Cost"][m] = total_operating_cost
            totals[tk]["GOP"][m] = total_lbs - total_operating_cost
            
    return data, totals

def get_audit_log(fiscal_year=2026, limit=50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM forecast_audit_log WHERE fiscal_year = ? ORDER BY timestamp DESC LIMIT ?", (fiscal_year, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def save_forecast_changes(fiscal_year, changes, username="system"):
    conn = get_db()
    cursor = conn.cursor()
    for change in changes:
        try:
            month_idx = int(change['month'])
            item_name = change['item']
            new_value = float(change['value'])
            cursor.execute("SELECT target_amount FROM budget_forecast WHERE fiscal_year = ? AND month_index = ? AND line_item_name = ?", (fiscal_year, month_idx, item_name))
            row = cursor.fetchone()
            old_value = float(row['target_amount']) if row else 0.0
            cursor.execute("INSERT OR REPLACE INTO budget_forecast (fiscal_year, month_index, line_item_name, target_amount) VALUES (?, ?, ?, ?)", (fiscal_year, month_idx, item_name, new_value))
            if abs(old_value - new_value) > 0.001:
                cursor.execute("INSERT INTO forecast_audit_log (timestamp, username, fiscal_year, month_index, line_item_name, old_value, new_value) VALUES (?, ?, ?, ?, ?, ?, ?)", (datetime.utcnow().isoformat(), username, fiscal_year, month_idx, item_name, old_value, new_value))
        except Exception as e:
            with open(CRASH_LOG, "a") as f:
                f.write(f"Error saving forecast change: {str(e)}\n")
    conn.commit()
    conn.close()

def application(environ, start_response):
    init_budget_db()
    sync_live_actuals(2026)
    
    if environ.get("PATH_INFO", "") == "/budget-controller/api/data":
        fiscal_year = int(environ.get('QUERY_STRING', '').split('year=')[-1].split('&')[0]) if 'year=' in environ.get('QUERY_STRING', '') else 2026
        data, totals = compute_financial_matrices(fiscal_year)
        start_response('200 OK', [('Content-Type', 'application/json'), ('Access-Control-Allow-Origin', '*')])
        return [json.dumps({"breakdown": data, "aggregates": totals}).encode('utf-8')]
    
    if environ.get("REQUEST_METHOD") == "POST" and environ.get("PATH_INFO", "") == "/budget-controller/update":
        try:
            content_length = int(environ.get('CONTENT_LENGTH', 0))
            post_data = environ['wsgi.input'].read(content_length).decode('utf-8')
            from urllib.parse import parse_qs
            parsed = parse_qs(post_data)
            fiscal_year = int(parsed.get('fiscal_year', ['2026'])[0])
            changes_json = parsed.get('changes', ['[]'])[0]
            changes = json.loads(changes_json)
            username = parsed.get('username', ['system'])[0]
            save_forecast_changes(fiscal_year, changes, username)
            status = '302 Found'
            response_headers = [('Location', '/budget-controller?year=' + str(fiscal_year))]
            start_response(status, response_headers)
            return [b""]
        except Exception as e:
            with open(CRASH_LOG, "w") as f:
                f.write(traceback.format_exc())
            start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
            return [("Error: " + str(e)).encode('utf-8')]
    
    try:
        query_string = environ.get('QUERY_STRING', '')
        fiscal_year = 2026
        if 'year=' in query_string:
            try:
                fiscal_year = int(query_string.split('year=')[-1].split('&')[0])
            except:
                pass
        
        data, totals = compute_financial_matrices(fiscal_year)
        audit_log = get_audit_log(fiscal_year)
        
        style_block = """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap');
            :root { --bg: #090d16; --card: #111827; --fg: #f3f4f6; --muted: #9ca3af; --border: rgba(255,255,255,0.08); --teal: #2dd4bf; --cyan: #38bdf8; --amber: #f59e0b; --red: #f43f5e; --purple: #a855f7; --font-heading: 'Syne', sans-serif; --font-body: 'Space Grotesk', sans-serif; }
            .top-nav { position: fixed; top: 0; right: 0; left: 0; background: rgba(9,13,22,0.98); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: flex-end; align-items: center; gap: 1.5rem; z-index: 1000; }
            .top-nav a { color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600; }
            .top-nav a:hover { color: var(--teal); }
            .top-nav a.amber { color: var(--amber); }
            .top-nav a.red { color: var(--red); }
            body { font-family: var(--font-body); background: var(--bg); color: var(--fg); padding: 80px 1rem 2rem 1rem; }
            h2 { font-family: var(--font-heading); font-weight: 800; color: #fff; margin-bottom: 1.5rem; }
            .grid-container { width: 100%; overflow-x: auto; background: var(--card); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 2rem; }
            table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.85rem; }
            th, td { padding: 0.6rem 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.05); white-space: nowrap; }
            th { background: rgba(255,255,255,0.03); color: #fff; text-transform: uppercase; letter-spacing: 0.05em; font-size: 0.75rem; }
            .category-row { background: rgba(168, 85, 247, 0.05); font-weight: 700; color: #a855f7; }
            .sub-total-row { background: rgba(45, 212, 191, 0.04); font-weight: 700; color: var(--teal); }
            .pnl-header { background: rgba(168, 85, 247, 0.1); font-weight: 800; color: #fff; text-align: center; font-size: 1rem; padding: 1rem !important; }
            .pnl-row { font-weight: 600; }
            .pnl-gop { background: rgba(45, 212, 191, 0.1); font-weight: 800; color: var(--teal); border-top: 2px solid var(--teal) !important; }
            .pnl-gop.negative { background: rgba(244, 63, 94, 0.1); color: var(--red); border-top: 2px solid var(--red) !important; }
            .item-name { font-weight: 500; color: var(--muted); padding-left: 1.5rem; }
            .num { text-align: right; font-variant-numeric: tabular-nums; }
            .badge { display: inline-block; padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.7rem; font-weight: 700; }
            .badge-f { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
            .badge-a { background: rgba(45, 212, 191, 0.15); color: var(--teal); }
            .edit-input { width: 80px; padding: 0.25rem; background: rgba(168, 85, 247, 0.1); border: 1px solid var(--purple); color: #fff; text-align: right; border-radius: 4px; font-size: 0.8rem; }
            .edit-input:focus { outline: none; border-color: var(--teal); box-shadow: 0 0 0 2px rgba(45, 212, 191, 0.2); }
            .btn { padding: 0.5rem 1rem; border: none; border-radius: 6px; font-weight: 700; cursor: pointer; font-size: 0.9rem; }
            .btn-primary { background: var(--teal); color: #090d16; }
            .btn-primary:hover { background: #14b8a6; }
            .btn-secondary { background: var(--muted); color: #090d16; }
            .btn-secondary:hover { background: #6b7280; }
            .year-selector { background: var(--card); border: 1px solid var(--border); color: #fff; padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; }
            .edit-controls { display: flex; gap: 1rem; margin-bottom: 1rem; align-items: center; }
            .edit-mode-indicator { color: var(--amber); font-weight: 700; }
            
            /* Collapsible Audit Log Styles */
            .audit-container { background: var(--card); border: 1px solid var(--border); border-radius: 8px; margin-top: 2rem; overflow: hidden; }
            .audit-container summary { padding: 1rem 1.5rem; cursor: pointer; font-weight: 700; color: var(--muted); font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; list-style: none; display: flex; justify-content: space-between; align-items: center; user-select: none; }
            .audit-container summary:hover { background: rgba(255,255,255,0.02); color: var(--fg); }
            .audit-container summary::-webkit-details-marker { display: none; }
            .audit-container summary .arrow { transition: transform 0.2s ease; font-size: 0.8rem; }
            .audit-container[open] summary .arrow { transform: rotate(180deg); }
            .audit-content { padding: 0 1.5rem 1.5rem 1.5rem; max-height: 400px; overflow-y: auto; border-top: 1px solid var(--border); }
            .audit-entry { padding: 0.75rem 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.85rem; }
            .audit-entry:last-child { border-bottom: none; }
            .audit-entry .time { color: var(--muted); font-size: 0.75rem; }
            .audit-entry .change { color: var(--teal); font-weight: 600; }
        </style>
        """
        
        table_html = '<form id="budgetForm" method="POST" action="/budget-controller/update"><input type="hidden" name="fiscal_year" value="' + str(fiscal_year) + '"><input type="hidden" name="username" value="admin"><input type="hidden" name="changes" id="changesData" value="[]"><table id="budgetTable"><thead><tr><th>Operational Parameters</th><th>Metric</th>'
        for m in MONTHS:
            table_html += '<th class="num">' + m + '</th>'
        table_html += '</tr></thead><tbody>'
        
        for category, items in FINANCIAL_STRUCTURE.items():
            table_html += '<tr class="category-row"><td colspan="14">⚙️ ' + html.escape(category) + '</td></tr>'
            for item in items:
                table_html += '<tr><td class="item-name">' + html.escape(item) + '</td><td><span class="badge badge-f">FCST</span></td>'
                for m in range(12):
                    val = data['forecast'][category][item][m]
                    table_html += '<td class="num"><input type="number" class="edit-input forecast-input" data-month="' + str(m+1) + '" data-item="' + html.escape(item) + '" value="' + str(round(val, 2)) + '" step="0.01" disabled></td>'
                table_html += '</tr>'
                table_html += '<tr><td class="item-name" style="color:rgba(255,255,255,0.3);">  Actuals</td><td><span class="badge badge-a">ACT</span></td>'
                for m in range(12):
                    val = data['actual'][category][item][m]
                    if "Lbs" in category:
                        table_html += '<td class="num">' + format_lbs(val) + '</td>'
                    else:
                        table_html += '<td class="num">' + format_pesos(val) + '</td>'
                table_html += '</tr>'
        
        # --- P&L SUMMARY ---
        table_html += '<tr class="pnl-header"><td colspan="14"> PROJECTED vs ACTUAL P&L SUMMARY</td></tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:1.5rem;">📦 Total Operational Volume (Lbs)</td>'
        for m in range(12):
            table_html += '<td class="num">' + format_lbs(totals['forecast']['Total Lbs Volume'][m]) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:1.5rem;">📈 Total Revenue</td>'
        for m in range(12):
            table_html += '<td class="num">' + format_pesos(totals['forecast']['Total Other Revenue'][m]) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row" style="color: var(--muted);"><td colspan="14" style="padding: 0.5rem 1.5rem; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; background: rgba(255,255,255,0.02);">Expense Breakdown</td></tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:2.5rem; font-size: 0.85rem; color: var(--muted);">  ├─ Payroll & Pilotage</td>'
        for m in range(12):
            val = sum(data['forecast']["Payroll & Pilotage fee"][item][m] for item in FINANCIAL_STRUCTURE["Payroll & Pilotage fee"])
            table_html += '<td class="num">' + format_pesos(val) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:2.5rem; font-size: 0.85rem; color: var(--muted);">  ├─ Other Expenses</td>'
        for m in range(12):
            val = sum(data['forecast']["Other Expenses"][item][m] for item in FINANCIAL_STRUCTURE["Other Expenses"])
            table_html += '<td class="num">' + format_pesos(val) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:2.5rem; font-size: 0.85rem; color: var(--muted);">  ├─ Promotion Expenses</td>'
        for m in range(12):
            val = sum(data['forecast']["Promotion Expenses"][item][m] for item in FINANCIAL_STRUCTURE["Promotion Expenses"])
            table_html += '<td class="num">' + format_pesos(val) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:2.5rem; font-size: 0.85rem; color: var(--muted);">  └─ Fixed Costs</td>'
        for m in range(12):
            val = sum(data['forecast']["Fixed Costs"][item][m] for item in FINANCIAL_STRUCTURE["Fixed Costs"])
            table_html += '<td class="num">' + format_pesos(val) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row" style="border-top: 2px solid var(--border);"><td colspan="2" style="padding-left:1.5rem; font-weight: 800; color: var(--fg);"> TOTAL OPERATING EXPENSES</td>'
        for m in range(12):
            table_html += '<td class="num" style="font-weight: 800;">' + format_pesos(totals['forecast']['Total Operating Cost'][m]) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-gop"><td colspan="2" style="padding-left:1.5rem;">💰 Forecast GOP (Volume - Expenses)</td>'
        for m in range(12):
            val = totals['forecast']['GOP'][m]
            table_html += f'<td class="num">{format_pesos(val)}</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-header" style="background:rgba(45, 212, 191, 0.1);"><td colspan="14">📊 ACTUAL PERFORMANCE</td></tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:1.5rem;"> Total Operational Volume (Lbs)</td>'
        for m in range(12):
            table_html += '<td class="num">' + format_lbs(totals['actual']['Total Lbs Volume'][m]) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row"><td colspan="2" style="padding-left:1.5rem;"> Total Revenue</td>'
        for m in range(12):
            table_html += '<td class="num">' + format_pesos(totals['actual']['Total Other Revenue'][m]) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-row" style="border-top: 2px solid var(--border);"><td colspan="2" style="padding-left:1.5rem; font-weight: 800; color: var(--fg);">📉 TOTAL OPERATING EXPENSES</td>'
        for m in range(12):
            table_html += '<td class="num" style="font-weight: 800;">' + format_pesos(totals['actual']['Total Operating Cost'][m]) + '</td>'
        table_html += '</tr>'
        
        table_html += '<tr class="pnl-gop"><td colspan="2" style="padding-left:1.5rem;"> Actual GOP (Volume - Expenses)</td>'
        for m in range(12):
            val = totals['actual']['GOP'][m]
            table_html += f'<td class="num">{format_pesos(val)}</td>'
        table_html += '</tr>'

        table_html += '</tbody></table>'
        table_html += '<div class="edit-controls"><button type="button" class="btn btn-primary" id="editBtn" onclick="toggleEditMode()">✏️ Edit Forecast</button><button type="submit" class="btn btn-primary" id="saveBtn" style="display:none;" onclick="saveChanges()">💾 Save Changes</button><button type="button" class="btn btn-secondary" id="cancelBtn" style="display:none;" onclick="cancelChanges()">Cancel</button><span class="edit-mode-indicator" id="editIndicator" style="display:none;"> EDIT MODE ACTIVE</span></div></form>'
        
        # --- COLLAPSIBLE AUDIT LOG ---
        audit_html = '''
        <details class="audit-container">
            <summary>
                <span> Forecast Change Audit Log</span>
                <span class="arrow">▼</span>
            </summary>
            <div class="audit-content">
        '''
        if audit_log:
            for entry in audit_log:
                audit_html += f'''<div class="audit-entry">
                    <span class="time">{entry['timestamp']}</span> - 
                    <strong>{html.escape(entry['line_item_name'])}</strong> (Month {entry['month_index']}): 
                    <span class="change">{format_pesos(entry['old_value'])} → {format_pesos(entry['new_value'])}</span>
                    <span style="color:var(--muted); font-size:0.75rem; margin-left: 0.5rem;">by {html.escape(entry['username'] or 'system')}</span>
                </div>'''
        else:
            audit_html += '<div style="color:var(--muted); font-size:0.85rem; padding: 1rem 0;">No forecast changes recorded yet.</div>'
        
        audit_html += '</div></details>'
        
        year_selector = '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem;"><h2>Operational Weight & Expense Controller</h2><div><select class="year-selector" onchange="window.location.href=\'/budget-controller?year=\'+this.value">'
        for year in range(2024, 2030):
            selected = "selected" if year == fiscal_year else ""
            year_selector += '<option value="' + str(year) + '" ' + selected + '>' + str(year) + '</option>'
        year_selector += '</select></div></div>'
        
        html_output = '<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"><link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">' + style_block + '</head><body>' + NAV_HTML + year_selector + '<div class="grid-container">' + table_html + '</div>' + audit_html + '''
        <script>
        let editMode = false;
        let originalValues = new Map();
        
        function toggleEditMode() {
            editMode = !editMode;
            const inputs = document.querySelectorAll('.forecast-input');
            const editBtn = document.getElementById('editBtn');
            const saveBtn = document.getElementById('saveBtn');
            const cancelBtn = document.getElementById('cancelBtn');
            const editIndicator = document.getElementById('editIndicator');
            
            if (editMode) {
                inputs.forEach(input => {
                    input.disabled = false;
                    originalValues.set(input.dataset.item + '-' + input.dataset.month, input.value);
                });
                editBtn.style.display = 'none';
                saveBtn.style.display = 'inline-block';
                cancelBtn.style.display = 'inline-block';
                editIndicator.style.display = 'inline';
                document.getElementById('budgetTable').style.borderColor = 'var(--amber)';
            } else {
                inputs.forEach(input => input.disabled = true);
                editBtn.style.display = 'inline-block';
                saveBtn.style.display = 'none';
                cancelBtn.style.display = 'none';
                editIndicator.style.display = 'none';
                document.getElementById('budgetTable').style.borderColor = 'var(--border)';
            }
        }
        
        function saveChanges() {
            const changes = [];
            document.querySelectorAll('.forecast-input').forEach(input => {
                const key = input.dataset.item + '-' + input.dataset.month;
                const original = originalValues.get(key);
                if (Math.abs(parseFloat(input.value) - parseFloat(original)) > 0.001) {
                    changes.push({
                        month: input.dataset.month,
                        item: input.dataset.item,
                        value: parseFloat(input.value)
                    });
                }
            });
            
            if (changes.length === 0) {
                alert('No changes detected.');
                return;
            }
            
            if (!confirm('Save ' + changes.length + ' forecast change(s)? This will be logged in the audit trail.')) {
                return;
            }
            
            document.getElementById('changesData').value = JSON.stringify(changes);
            document.getElementById('budgetForm').submit();
        }
        
        function cancelChanges() {
            if (!confirm('Discard all unsaved changes?')) return;
            
            document.querySelectorAll('.forecast-input').forEach(input => {
                const key = input.dataset.item + '-' + input.dataset.month;
                input.value = originalValues.get(key);
                input.disabled = true;
            });
            
            toggleEditMode();
        }
        </script>
        </body></html>'''
        
        start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8')])
        return [html_output.encode('utf-8')]
    except Exception as e:
        with open(CRASH_LOG, "w") as f:
            f.write(traceback.format_exc())
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [b"Operational Controller Engine structural update error logged."]
