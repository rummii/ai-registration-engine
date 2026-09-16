import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db as db_module


def test_budget_profitability_metrics():
    from app import calculate_budget_metrics

    forecast = {
        "Marketing": [100.0] + [0.0] * 11,
        "Rent": [50.0] + [0.0] * 11,
    }
    actual = {
        "Marketing": [80.0] + [0.0] * 11,
        "Rent": [40.0] + [0.0] * 11,
    }

    metrics = calculate_budget_metrics(forecast, actual, [500.0] + [0.0] * 11)

    assert metrics["forecast_gop"][0] == 400.0
    assert metrics["actual_gop"][0] == 420.0
    assert metrics["forecast_net"][0] == 350.0
    assert metrics["actual_net"][0] == 380.0
