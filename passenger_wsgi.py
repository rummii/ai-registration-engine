import sys
import os

# Environment variables needed at runtime
os.environ["COOKIE_SECRET"] = "144da6fb92f9681635b21509f2024fe1987144fba77c42593912eb22e4979e2a"
os.environ["SECRET_KEY"] = "6faaf838f8dbca610bce5bb1257507828708daeec7b0a203c7e0129ce56023db"
os.environ["TELEGRAM_ALLOWED_CHAT_ID"] = "6027602817"
os.environ["TELEGRAM_BOT_TOKEN"] = "8946164927:AAEZ6VF9XHP6GBxuF8PJ0wurfscPCU0-SDI"

sys.path.insert(0, '/home/vsmwrurd/ai_registration_engine')

from app import app as application
