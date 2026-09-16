import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv('.env.local')


def _secret(name, local_fallback):
	value = os.environ.get(name)
	if value:
		return value
	if os.environ.get("K_SERVICE") or os.environ.get("FLASK_ENV") == "production":
		raise RuntimeError(f"{name} must be configured in production.")
	return local_fallback


# Cookie signing secret (HMAC)
COOKIE_SECRET = _secret("COOKIE_SECRET", "local-cookie-secret-change-me")

# Flask secret key
SECRET_KEY = _secret("SECRET_KEY", "local-secret-key-change-me")

# Database configuration
DATABASE_URL = os.environ.get("DATABASE_URL")

# Telegram bot integration (for notifications)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Security settings
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB max request size

# Brute force protection
BRUTE_FORCE_LIMIT = 5  # Max failed attempts before lockout
LOCKOUT_MINUTES = 15   # Lockout duration in minutes

# Session settings
SESSION_HOURS = 8  # Cookie valid for 8 hours
