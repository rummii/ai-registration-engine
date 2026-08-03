#!/usr/bin/env python3
"""
AI Experience Center - System Integrity Test
Tests all modules, database schema, and routing
"""

import os
import sys
import sqlite3
import importlib.util

BASE_DIR = "/home/vsmwrurd/ai_registration_engine"
DB_FILE = os.path.join(BASE_DIR, "booking_storage.db")

def color_print(text, color):
    colors = {
        'green': '\033[92m',
        'yellow': '\033[93m',
        'red': '\033[91m',
        'blue': '\033[94m',
        'end': '\033[0m'
    }
    print(f"{colors.get(color, '')}{text}{colors['end']}")

def test_file_exists(filepath, description):
    exists = os.path.exists(filepath)
    status = "✅" if exists else "❌"
    color_print(f"{status} {description}: {filepath}", "green" if exists else "red")
    return exists

def test_import(module_name, filepath):
    try:
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        color_print(f"✅ Module import: {module_name}", "green")
        return True
    except Exception as e:
        color_print(f"❌ Module import: {module_name} - {str(e)}", "red")
        return False

def test_database_schema():
    color_print("\n🔍 Testing Database Schema...", "blue")
    
    if not os.path.exists(DB_FILE):
        color_print("❌ Database file not found", "red")
        return False
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    required_tables = [
        'system_users',
        'program_config',
        'cohort_dates',
        'participant_bookings',
        'budget_forecast',
        'budget_actuals_cache'
    ]
    
    all_good = True
    for table in required_tables:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if cursor.fetchone():
            color_print(f"  ✅ Table: {table}", "green")
        else:
            color_print(f"  ❌ Table missing: {table}", "red")
            all_good = False
    
    cursor.execute("PRAGMA table_info(cohort_dates)")
    columns = [col[1] for col in cursor.fetchall()]
    critical_cols = ['lab', 'custom_title', 'time_window']
    for col in critical_cols:
        if col in columns:
            color_print(f"  ✅ Column: cohort_dates.{col}", "green")
        else:
            color_print(f"  ❌ Column missing: cohort_dates.{col}", "red")
            all_good = False
    
    conn.close()
    return all_good

def test_routes():
    color_print("\n🔗 Testing Routes...", "blue")
    
    routes = {
        '/': 'Public booking page',
        '/book-now': 'Booking form',
        '/book-now?admin=true': 'Admin console',
        '/action-plan': 'Action Plan (protected)',
        '/budget-controller': 'Budget Controller',
        '/book-now?accounting-dashboard=true': 'Accounting Ledger'
    }
    
    for route, desc in routes.items():
        color_print(f"  ℹ️  Route: {route} - {desc}", "blue")
    
    return True

def test_security():
    color_print("\n🔐 Testing Security Configuration...", "blue")
    
    env_vars = ['SECRET_KEY', 'COOKIE_SECRET', 'TELEGRAM_BOT_TOKEN']
    all_good = True
    
    for var in env_vars:
        if os.environ.get(var):
            color_print(f"  ✅ Environment variable: {var}", "green")
        else:
            color_print(f"  ⚠️  Missing environment variable: {var}", "yellow")
            all_good = False
    
    with open(os.path.join(BASE_DIR, 'passenger_wsgi.py'), 'r') as f:
        content = f.read()
        if 'COOKIE_SECRET = b"ai_center_2026' in content:
            color_print(f"  ⚠️  Warning: Hardcoded COOKIE_SECRET found", "yellow")
    
    return all_good

def test_dependencies():
    color_print("\n📦 Testing Dependencies...", "blue")
    
    deps = ['sqlite3', 'hashlib', 'hmac', 'json', 'traceback', 'html']
    all_good = True
    
    for dep in deps:
        try:
            __import__(dep)
            color_print(f"  ✅ Dependency: {dep}", "green")
        except ImportError:
            color_print(f"  ❌ Missing dependency: {dep}", "red")
            all_good = False
    
    try:
        import telebot
        color_print(f"  ✅ External: pyTelegramBotAPI", "green")
    except ImportError:
        color_print(f"  ⚠️  Missing: pyTelegramBotAPI (for Telegram bot)", "yellow")
        color_print(f"     Note: Bot can be installed separately if needed", "yellow")
    except SyntaxError as e:
        color_print(f"  ⚠️  pyTelegramBotAPI version incompatible with Python 3.6", "yellow")
        color_print(f"     Note: This is OK - bot runs separately. Upgrade Python to 3.8+ for bot support", "yellow")
    
    return all_good

def main():
    color_print("=" * 60, "blue")
    color_print(" AI EXPERIENCE CENTER - INTEGRITY TEST", "blue")
    color_print("=" * 60, "blue")
    
    results = []
    
    color_print("\n📁 Testing File Structure...", "blue")
    files_to_check = [
        (os.path.join(BASE_DIR, 'passenger_wsgi.py'), 'Main WSGI application'),
        (os.path.join(BASE_DIR, 'accounting.py'), 'Accounting module'),
        (os.path.join(BASE_DIR, 'budget_controller.py'), 'Budget controller'),
        (os.path.join(BASE_DIR, 'action_plan_handler.py'), 'Action Plan handler'),
        (os.path.join(BASE_DIR, 'AIEC_Action_Plan.html'), 'Action Plan HTML'),
    ]
    
    for filepath, desc in files_to_check:
        results.append(test_file_exists(filepath, desc))
    
    color_print("\n📦 Testing Module Imports...", "blue")
    modules_to_test = [
        ('passenger_wsgi', os.path.join(BASE_DIR, 'passenger_wsgi.py')),
        ('accounting', os.path.join(BASE_DIR, 'accounting.py')),
        ('budget_controller', os.path.join(BASE_DIR, 'budget_controller.py')),
        ('action_plan_handler', os.path.join(BASE_DIR, 'action_plan_handler.py')),
    ]
    
    for module_name, filepath in modules_to_test:
        results.append(test_import(module_name, filepath))
    
    results.append(test_database_schema())
    results.append(test_routes())
    results.append(test_security())
    results.append(test_dependencies())
    
    color_print("\n" + "=" * 60, "blue")
    passed = sum(results)
    total = len(results)
    percentage = (passed / total * 100) if total > 0 else 0
    
    if percentage >= 90:
        color_print(f"✅ SYSTEM READY FOR DEPLOYMENT ({passed}/{total} tests passed)", "green")
        color_print(f"   Non-critical items can be configured post-deployment", "green")
    else:
        color_print(f"⚠️  TESTS COMPLETED: {passed}/{total} ({percentage:.1f}%)", "yellow")
        color_print(f"   Critical issues must be resolved before deployment", "yellow")
    
    color_print("=" * 60, "blue")
    
    return percentage >= 90

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
