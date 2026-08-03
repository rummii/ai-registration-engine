import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "booking_storage.db"
VOUCHER_DIR = BASE_DIR / "vouchers"
VOUCHER_DIR.mkdir(exist_ok=True)

# Security - MUST be set via environment variables in production
SECRET_KEY = os.environ.get('SECRET_KEY', 'CHANGE-THIS-IN-PRODUCTION')
COOKIE_SECRET = os.environ.get('COOKIE_SECRET', 'CHANGE-THIS-IN-PRODUCTION').encode('utf-8')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_ALLOWED_CHAT_ID = int(os.environ.get('TELEGRAM_ALLOWED_CHAT_ID', '0'))

# Flask config
DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB

# Auth config
BRUTE_FORCE_LIMIT = 5
LOCKOUT_MINUTES = 15
SESSION_HOURS = 24
