import os
from dotenv import load_dotenv

load_dotenv()
load_dotenv('.env.local')


# Cloud Run always sets K_SERVICE. FLASK_ENV covers other production hosts.
IS_PRODUCTION = bool(os.environ.get("K_SERVICE")) or os.environ.get("FLASK_ENV") == "production"


def _secret(name, local_fallback):
	value = os.environ.get(name)
	if value:
		return value
	if IS_PRODUCTION:
		raise RuntimeError(f"{name} must be configured in production.")
	return local_fallback


def _required(name):
	"""Return a required variable, raising in production when it is missing."""
	value = os.environ.get(name)
	if value:
		return value
	if IS_PRODUCTION:
		raise RuntimeError(f"{name} must be configured in production.")
	return None


# Cookie signing secret (HMAC)
COOKIE_SECRET = _secret("COOKIE_SECRET", "local-cookie-secret-change-me")

# Flask secret key
SECRET_KEY = _secret("SECRET_KEY", "local-secret-key-change-me")

# Database configuration. Required in production so the app never silently
# falls back to an ephemeral local SQLite file on Cloud Run.
DATABASE_URL = _required("DATABASE_URL")

# Telegram bot integration (for notifications)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Cloud Storage bucket holding voucher photos uploaded through the Telegram bot.
# Not a secret, so it is safe to default. When empty, voucher uploads are
# reported to the user as unavailable instead of failing the whole expense.
VOUCHER_BUCKET = os.environ.get("VOUCHER_BUCKET", "aiex-registration-vouchers-223942147362")

# Telegram downloads a photo in one request, so cap what we are willing to fetch
# and store. Telegram's largest photo rendition is well under this.
MAX_VOUCHER_BYTES = 10 * 1024 * 1024

# Security settings
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB max request size

# Brute force protection
BRUTE_FORCE_LIMIT = 5  # Max failed attempts before lockout
LOCKOUT_MINUTES = 15   # Lockout duration in minutes

# Session settings
SESSION_HOURS = 8  # Cookie valid for 8 hours
