import sys
import os

# Add project directory to path
sys.path.insert(0, os.path.dirname(__file__))

from app import app as application

# Initialize database on first load
from db import init_db, migrate_price_data
init_db()
migrate_price_data()
