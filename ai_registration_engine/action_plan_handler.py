import os, sqlite3, html, json, traceback
from datetime import datetime

BASE_DIR = "/home/vsmwrurd/ai_registration_engine"
DB_FILE = os.path.join(BASE_DIR, "booking_storage.db")

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS action_plan_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, section TEXT NOT NULL, section_title TEXT DEFAULT '',
        task TEXT NOT NULL, owner TEXT DEFAULT '', due_date TEXT DEFAULT '', status TEXT DEFAULT 'Not started',
        notes TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    return conn

def action_plan_application(environ, start_response):
    cookie_str = environ.get('HTTP_COOKIE', '')
    auth_user = None
    if "auth_user=" in cookie_str:
        for part in cookie_str.split(';'):
            if "auth_user=" in part.strip():
                try:
                    from passenger_wsgi import verify_signed_cookie
                    auth_user = verify_signed_cookie(part.strip().split('=', 1)[1])
                except: pass
    if not auth_user:
        start_response('302 Found', [('Location', '/book-now?admin=true')])
        return [b""]

    if environ.get('REQUEST_METHOD') == 'POST':
        try:
            length = int(environ.get('CONTENT_LENGTH', 0))
            data = json.loads(environ['wsgi.input'].read(length).decode('utf-8'))
            action = data.get('action')
            conn = get_db()
            c = conn.cursor()
            
            if action == 'save_all':
                for item in data.get('items', []):
                    c.execute("""UPDATE action_plan_items SET task=?, owner=?, due_date=?, status=?, notes=?, updated_at=? WHERE id=?""",
                              (item['task'], item['owner'], item['due_date'], item['status'], item['notes'], datetime.utcnow().isoformat(), int(item['id'])))
                conn.commit()
                conn.close()
                start_response('200 OK', [('Content-Type', 'application/json')])
                return [json.dumps({'success': True}).encode('utf-8')]
                
            elif action == 'add_item':
                c.execute("INSERT INTO action_plan_items (section, section_title, task, status) VALUES (?,?,?,?)",
                          (data['section'], data['section_title'], 'New task...', 'Not started'))
                conn.commit()
                conn.close()
                start_response('200 OK', [('Content-Type', 'application/json')])
                return [json.dumps({'success': True, 'id': c.lastrowid}).encode('utf-8')]
                
            elif action == 'delete_item':
                c.execute("DELETE FROM action_plan_items WHERE id=?", (int(data['id']),))
                conn.commit()
                conn.close()
                start_response('200 OK', [('Content-Type', 'application/json')])
                return [json.dumps({'success': True}).encode('utf-8')]
        except Exception as e:
            start_response('500 Internal Server Error', [('Content-Type', 'application/json')])
            return [json.dumps({'error': str(e)}).encode('utf-8')]

    try:
        conn = get_db()
        items = conn.execute("SELECT * FROM action_plan_items ORDER BY section, id").fetchall()
        conn.close()
        
        sections = {}
        for item in items:
            s = item['section']
            if s not in sections: sections[s] = []
            sections[s].append(dict(item))
            
        html_out = ""
        titles = {"00": "Lock the deal", "01": "Capitalization", "02": "Office & renovation", 
                  "03": "Stations & server", "04": "Product & curriculum", "05": "Website & pre-sale",
                  "06": "Funding & credits", "07": "Admin & legitimacy"}
        subtitles = {"00": "Biggest dispute risk — close before Jul 16", "01": "Hybrid — ₱150k pot is dead",
                     "02": "Base = upstairs unit + bodega", "03": "₱500k capex dropped — pool gear",
                     "04": "Lab architecture locked Jun 21", "05": "Pro ₱8,000 · Builder ₱3,500",
                     "06": "Lead with Hollywood Ninja, not AIEC", "07": "Gates the credit pitch & pre-sale trust"}
                  
        for sec in sorted(sections.keys()):
            rows = ""
            for i in sections[sec]:
                # Changed Due to textarea to prevent truncation
                rows += f"""<tr data-id="{i['id']}">
                    <td><textarea class="inp-task" oninput="autoResize(this)">{html.escape(i['task'])}</textarea></td>
                    <td><input type="text" class="inp-owner" value="{html.escape(i['owner'])}"></td>
                    <td><textarea class="inp-due" oninput="autoResize(this)">{html.escape(i['due_date'])}</textarea></td>
                    <td><select class="inp-status">
                        <option {"selected" if i['status']=='Not started' else ""}>Not started</option>
                        <option {"selected" if i['status']=='In progress' else ""}>In progress</option>
                        <option {"selected" if i['status']=='Done' else ""}>Done</option>
                        <option {"selected" if i['status']=='Blocked' else ""}>Blocked</option>
                    </select></td>
                    <td><textarea class="inp-notes" oninput="autoResize(this)">{html.escape(i['notes'])}</textarea></td>
                    <td style="text-align:center;"><button class="del-btn" onclick="deleteRow({i['id']})">×</button></td>
                </tr>"""
            
            html_out += f"""
            <div class="section-block">
                <h3><span class="sec-num">{sec}</span> {titles.get(sec, sec)} <span class="sec-sub">{subtitles.get(sec, '')}</span></h3>
                <table class="data-table">
                    <thead><tr><th style="width:35%">Task</th><th style="width:10%">Owner</th><th style="width:10%">Due</th><th style="width:15%">Status</th><th style="width:25%">Notes</th><th style="width:5%"></th></tr></thead>
                    <tbody>{rows}</tbody>
                </table>
                <button class="add-row-btn" onclick="addRow('{sec}', '{titles.get(sec, '')}')">＋ Add row to this section</button>
            </div>"""

        watch_list_html = """
        <div class="watch-list">
            <h3>⚠ Watch list</h3>
            <ul>
                <li><strong>5-day buffer.</strong> Jeff returns Aug 10, cohort Aug 16. Everything buildable must be done before he travels — treat the return window as setup only.</li>
                <li><strong>Deal unsigned.</strong> Cap + renovation split agreed verbally after hours of circling. Get it on paper before Jul 16 spend starts.</li>
                <li><strong>Server unknown.</strong> Condition unverified until pulled. Don't discover a dead drive days before launch.</li>
                <li><strong>Legitimacy not live.</strong> No Google Business listing / permit yet — blocks both the credit pitch and pre-sale trust.</li>
                <li><strong>Claude token bleed.</strong> Running live sessions inside the loaded Project burns the limit. Work in a fresh chat, commit decisions back after.</li>
            </ul>
        </div>
        """

        nav_html = """
        <div class="top-nav">
            <a href="/book-now">Public View</a>
            <a href="/book-now?admin=true">Admin Console</a>
            <a href="/book-now?accounting-dashboard=true" class="amber">Accounting</a>
            <a href="/budget-controller" class="amber">Budget</a>
            <a href="/action-plan" class="amber">Action Plan</a>
            <a href="/book-now?admin=true&action=logout" class="red">Log Out</a>
        </div>
        """

        page = f"""<!DOCTYPE html><html><head><title>AIEC Action Plan</title>
        <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
        <style>
            :root {{ --bg: #090d16; --card: #111827; --fg: #f3f4f6; --muted: #9ca3af; --border: rgba(255,255,255,0.08); --teal: #2dd4bf; --amber: #f59e0b; --red: #f43f5e; --purple: #a855f7; --font-heading: 'Syne', sans-serif; --font-body: 'Space Grotesk', sans-serif; }}
            .top-nav {{ position: fixed; top: 0; right: 0; left: 0; background: rgba(9,13,22,0.98); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); padding: 1rem 2rem; display: flex; justify-content: flex-end; align-items: center; gap: 1.5rem; z-index: 1000; }}
            .top-nav a {{ color: var(--muted); text-decoration: none; font-size: 0.9rem; font-weight: 600; font-family: var(--font-body); }}
            .top-nav a:hover {{ color: var(--teal); }}
            .top-nav a.amber {{ color: var(--amber); }}
            .top-nav a.red {{ color: var(--red); }}
            
            body {{ font-family: var(--font-body); background: var(--bg); color: var(--fg); padding: 100px 2rem 120px 2rem; max-width: 1400px; margin: 0 auto; }}
            h1 {{ font-family: var(--font-heading); font-size: 2rem; font-weight: 800; color: #fff; margin-bottom: 0.5rem; }}
            .header-info {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin-bottom: 2rem; padding: 1rem; background: var(--card); border-radius: 8px; border: 1px solid var(--border); font-size: 0.9rem; color: var(--muted); }}
            
            .toolbar {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem; margin-bottom: 2rem; padding: 1rem; background: var(--card); border-radius: 8px; border: 1px solid var(--border); }}
            .legend {{ display: flex; gap: 1rem; align-items: center; font-size: 0.85rem; }}
            .legend-title {{ color: var(--muted); font-weight: 600; margin-right: 0.5rem; }}
            .status-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; }}
            .dot-ns {{ background: var(--muted); }} .dot-ip {{ background: var(--teal); }} .dot-d {{ background: #22c55e; }} .dot-b {{ background: var(--red); }}
            .owner-tag {{ background: rgba(255,255,255,0.1); padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }}
            
            .section-block {{ margin-bottom: 2rem; }}
            h3 {{ font-family: var(--font-heading); color: var(--teal); margin: 0 0 1rem 0; font-size: 1.3rem; display: flex; align-items: baseline; gap: 0.5rem; }}
            .sec-num {{ color: var(--purple); font-size: 1rem; }}
            .sec-sub {{ color: var(--muted); font-size: 0.9rem; font-weight: 400; font-family: var(--font-body); }}
            
            .data-table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
            th, td {{ padding: 0.5rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; vertical-align: top; }}
            th {{ background: rgba(255,255,255,0.03); color: #fff; font-weight: 700; text-transform: uppercase; font-size: 0.75rem; text-align: left; }}
            
            input, select {{ background: #0b0f19; border: 1px solid var(--border); color: #fff; padding: 0.4rem; width: 100%; box-sizing: border-box; border-radius: 4px; font-family: var(--font-body); font-size: 0.9rem; }}
            textarea {{ 
                background: #0b0f19; border: 1px solid var(--border); color: #fff; padding: 0.4rem; 
                width: 100%; box-sizing: border-box; border-radius: 4px; font-family: var(--font-body); font-size: 0.9rem;
                resize: none; overflow: hidden; line-height: 1.4; white-space: pre-wrap; word-wrap: break-word;
                min-height: 38px;
            }}
            input:focus, textarea:focus, select:focus {{ border-color: var(--teal); outline: none; }}
            .inp-task {{ min-height: 50px; }}
            .inp-notes {{ min-height: 50px; }}
            .inp-due {{ min-height: 38px; }}
            
            .add-row-btn {{ background: transparent; border: 1px dashed var(--border); color: var(--muted); padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem; margin-top: 0.5rem; width: 100%; text-align: left; }}
            .add-row-btn:hover {{ border-color: var(--teal); color: var(--teal); }}
            .del-btn {{ background: transparent; border: none; color: var(--red); cursor: pointer; font-size: 1.2rem; padding: 0 5px; }}
            
            .watch-list {{ background: rgba(244, 63, 94, 0.05); border: 1px solid rgba(244, 63, 94, 0.2); border-radius: 8px; padding: 1.5rem; margin-top: 3rem; }}
            .watch-list h3 {{ color: var(--red); margin-top: 0; }}
            .watch-list ul {{ margin: 0; padding-left: 1.5rem; }}
            .watch-list li {{ margin-bottom: 0.5rem; line-height: 1.5; }}
            
            .save-btn {{ position: fixed; bottom: 30px; right: 30px; background: var(--teal); color: #090d16; border: none; padding: 15px 30px; border-radius: 50px; font-weight: 800; font-size: 1.1rem; cursor: pointer; box-shadow: 0 4px 20px rgba(45, 212, 191, 0.3); z-index: 1000; transition: all 0.2s; font-family: var(--font-body); }}
            .save-btn:hover {{ transform: translateY(-2px); box-shadow: 0 6px 25px rgba(45, 212, 191, 0.5); }}
            #saveStatus {{ position: fixed; bottom: 100px; right: 30px; background: var(--card); color: var(--teal); border: 1px solid var(--teal); padding: 10px 20px; border-radius: 8px; display: none; z-index: 1000; font-weight: 600; }}
            
            @media print {{
                .top-nav, .save-btn, #saveStatus, .add-row-btn, .del-btn {{ display: none !important; }}
                body {{ padding: 20px; background: #fff; color: #000; }}
                .data-table, th, td, input, textarea {{ border-color: #ccc; color: #000; background: #fff; }}
            }}
        </style></head><body>
        {nav_html}
        <h1>▮▮ AI EXPERIENCE CENTER PH ▮ PRODUCTION CALL SHEET</h1>
        <p style="color:var(--muted); margin-bottom: 1rem;">Action Plan — Launch Cohort 01 · From conceptualization → execution</p>
        
        <div class="header-info">
            <span>📅 Sessions Jun 21 + Jun 28</span>
            <span>🏗️ Move-in / Reno JUL 16</span>
            <span> Pre-sale opens JUL (wk 1)</span>
            <span>✈️ Jeff returns AUG 10</span>
            <span> Cohort 01 (Sat) AUG 16</span>
            <span>⚠️ Prep buffer 5 DAYS</span>
        </div>

        <div class="toolbar">
            <div style="display:flex; gap:1rem;">
                <button onclick="window.print()" style="background:var(--card); color:var(--fg); border:1px solid var(--border); padding:0.5rem 1rem; border-radius:4px; cursor:pointer;">⎙ Print / PDF</button>
            </div>
            <div class="legend">
                <span class="legend-title">Status key:</span>
                <span><span class="status-dot dot-ns"></span>Not started</span>
                <span><span class="status-dot dot-ip"></span>In progress</span>
                <span><span class="status-dot dot-d"></span>Done</span>
                <span><span class="status-dot dot-b"></span>Blocked</span>
            </div>
            <div class="legend">
                <span class="legend-title">Owners:</span>
                <span class="owner-tag">JEFF</span>
                <span class="owner-tag">ROBSON</span>
                <span class="owner-tag">P3</span>
                <span class="owner-tag">ALL</span>
            </div>
        </div>
        
        <p style="color:var(--muted); font-size:0.9rem; margin-bottom:2rem;"><em>Every cell is editable — click to type. Changes are saved to the database for all users.</em></p>
        
        <div id="saveStatus">✓ All changes saved to database!</div>
        <button class="save-btn" onclick="saveAllChanges()"> SAVE ALL CHANGES</button>
        
        {html_out}
        
        {watch_list_html}
        
        <footer style="text-align:center; color:var(--muted); font-size:0.8rem; margin-top:3rem; padding-top:1rem; border-top:1px solid var(--border);">
            AIEC Action Plan · generated from Jun 21 + Jun 28 sessions · owners and dates are editable placeholders — adjust before circulating.
        </footer>
        
        <script>
        function autoResize(el) {{
            el.style.height = 'auto';
            el.style.height = el.scrollHeight + 'px';
        }}
        document.addEventListener('DOMContentLoaded', function() {{
            document.querySelectorAll('textarea').forEach(el => autoResize(el));
        }});

        async function saveAllChanges() {{
            const btn = document.querySelector('.save-btn');
            const status = document.getElementById('saveStatus');
            btn.textContent = 'Saving...';
            btn.disabled = true;
            
            const allItems = [];
            document.querySelectorAll('tr[data-id]').forEach(row => {{
                allItems.push({{
                    id: row.dataset.id,
                    task: row.querySelector('.inp-task').value,
                    owner: row.querySelector('.inp-owner').value,
                    due_date: row.querySelector('.inp-due').value,
                    status: row.querySelector('.inp-status').value,
                    notes: row.querySelector('.inp-notes').value
                }});
            }});
            
            try {{
                const res = await fetch('/action-plan', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{action: 'save_all', items: allItems}})
                }});
                const data = await res.json();
                if (data.success) {{
                    status.style.display = 'block';
                    btn.textContent = '✓ Saved!';
                    setTimeout(() => {{
                        status.style.display = 'none';
                        btn.textContent = '💾 SAVE ALL CHANGES';
                        btn.disabled = false;
                    }}, 2000);
                }} else {{ alert('Error: ' + data.error); btn.disabled = false; }}
            }} catch(e) {{ alert('Network error'); btn.disabled = false; }}
        }}

        async function addRow(section, title) {{
            try {{
                const res = await fetch('/action-plan', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{action: 'add_item', section: section, section_title: title}})
                }});
                location.reload();
            }} catch(e) {{ alert('Error adding row'); }}
        }}

        async function deleteRow(id) {{
            if(!confirm('Delete this row?')) return;
            try {{
                await fetch('/action-plan', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{action: 'delete_item', id: id}})
                }});
                location.reload();
            }} catch(e) {{ alert('Error deleting row'); }}
        }}
        </script></body></html>"""
        
        start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8')])
        return [page.encode('utf-8')]
    except Exception as e:
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain')])
        return [f"Error: {traceback.format_exc()}".encode('utf-8')]
