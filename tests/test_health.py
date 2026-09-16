import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module


def test_health_route_reports_ok():
    importlib.reload(app_module)
    client = app_module.app.test_client()

    response = client.get('/health')

    assert response.status_code == 200
    assert response.json['status'] == 'ok'
