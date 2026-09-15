"""
Unit tests for TRINETRA Temporal Engine.
Tests harmonic basis computation, RLS online covariance updates, and CUSUM break detection.
"""
import os
import sys
import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.engines.temporal import CellModel, harmonic_basis, temporal_engine


def test_harmonic_basis():
    x = harmonic_basis(day_of_year=180.0, year_frac=0.5)
    assert len(x) == 6
    assert x[0] == 1.0
    assert x[1] == 0.5


def test_cell_model_seasonal_tracking():
    """
    Tests that stable seasonal / baseline variation does NOT trigger a false break.
    """
    cell = CellModel(h3_id="test_cell_01", dims=4)

    for i in range(15):
        date_str = f"2024-{(i%12)+1:02d}-15"
        embed = np.array([1.0, 0.5, -0.5, 0.2])
        is_break, _ = cell.update(date_str, embed, valid_fraction=0.95)
        assert is_break is False


def test_cell_model_break_detection():
    """
    Tests that persistent large deviations DO trigger CUSUM break detection.
    """
    cell = CellModel(h3_id="test_cell_break", dims=4)

    # First 15 normal observations to calibrate baseline
    for i in range(15):
        date_str = f"2024-{(i%12)+1:02d}-01"
        embed = np.array([1.0, 0.5, -0.5, 0.2])
        cell.update(date_str, embed, valid_fraction=0.95)

    # Now introduce persistent +5.0 anomaly
    break_fired = False
    break_info = None
    for j in range(6):
        date_str = f"2025-0{j+1}-01"
        embed = np.array([6.0, 5.5, 4.5, 5.2])
        is_break, info = cell.update(date_str, embed, valid_fraction=0.95)
        if is_break:
            break_fired = True
            break_info = info
            break

    assert break_fired is True
    assert "estimate" in break_info
    assert "confidence_interval" in break_info
    assert break_info["interval_days"] >= 1
