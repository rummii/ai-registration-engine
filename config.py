import os

# Cookie signing secret (HMAC)
COOKIE_SECRET = os.environ.get("COOKIE_SECRET", "default-cookie-secret-change-me")

# Flask secret key
SECRET_KEY = os.environ.get("SECRET_KEY", "default-secret-key-change-me")

# Telegram bot integration (for notifications)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")

# Security settings
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB max request size

# Brute force protection
BRUTE_FORCE_LIMIT = 5  # Max failed attempts before lockout
LOCKOUT_MINUTES = 15   # Lockout duration in minutes

# Session settings
SESSION_HOURS = 8  # Cookie valid for 8 hours
