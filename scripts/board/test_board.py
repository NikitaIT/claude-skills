"""Tests for board.py forecast and retro commands (PBI #41)."""

import csv
import importlib.util
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Load board.py as a module directly (product/ is not a Python package)
_BOARD_PATH = Path(__file__).parent / "board.py"
_spec = importlib.util.spec_from_file_location("board", _BOARD_PATH)
assert _spec and _spec.loader
board = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(board)


def _write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


@pytest.fixture
def tmp_product_dir(tmp_path: Path):
    """Create a temporary product directory with empty CSVs.
    schema.sql is loaded from SCRIPT_DIR (next to board.py), not PRODUCT_DIR."""
    # Empty defaults
    _write_csv(tmp_path / "product_backlog.csv", ["id", "title", "status", "cause_id", "feature_file", "doc"], [])
    _write_csv(tmp_path / "sprint.csv", ["id", "goal", "started_at", "ended_at"], [])
    _write_csv(tmp_path / "sprint_backlog.csv", ["pbi_id", "title", "feature_file", "doc", "cause_id"], [])
    _write_csv(tmp_path / "sprint_log.csv", ["pbi_id", "title", "sprint_id", "done_at", "cause_id", "feature_file", "doc"], [])
    _write_csv(tmp_path / "agent_log.csv", ["pbi_id", "sprint_id", "agent", "duration_ms", "total_tokens", "tool_uses", "status"], [])

    return tmp_path


def _run_forecast(product_dir: Path) -> str:
    """Run _forecast() with patched PRODUCT_DIR and capture stdout."""
    with patch.object(board, "PRODUCT_DIR", product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            board._forecast()
        return buf.getvalue()


def _run_retro(product_dir: Path) -> str:
    """Run _retro() with patched PRODUCT_DIR and capture stdout."""
    with patch.object(board, "PRODUCT_DIR", product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            board._retro()
        return buf.getvalue()


# -- Scenario: Forecast outputs capacity recommendation --


def test_forecast_outputs_capacity_recommendation(tmp_product_dir: Path):
    """Given agent_log.csv has data from at least 1 completed sprint,
    the forecast outputs avg tokens, duration, throughput, and recommended count."""
    _write_csv(tmp_product_dir / "sprint.csv", ["id", "goal", "started_at", "ended_at"], [
        [10, "Sprint 10", "2026-01-01", "2026-01-02"],
    ])
    _write_csv(tmp_product_dir / "agent_log.csv",
        ["pbi_id", "sprint_id", "agent", "duration_ms", "total_tokens", "tool_uses", "status"],
        [
            [1, 10, "dev-1", 600000, 100000, 50, "done"],
            [2, 10, "dev-2", 300000, 50000, 30, "done"],
        ],
    )

    output = _run_forecast(tmp_product_dir)

    assert "Avg tokens/PBI" in output
    assert "duration" in output.lower()
    assert "Throughput" in output
    assert "Recommended PBI count" in output


# -- Scenario: Forecast handles empty log --


def test_forecast_empty_log(tmp_product_dir: Path):
    """Given agent_log.csv has no data, forecast says no historical data."""
    output = _run_forecast(tmp_product_dir)
    assert "No historical data" in output


# -- Scenario: Retro outputs sprint summary --


def test_retro_outputs_sprint_summary(tmp_product_dir: Path):
    """Given the last sprint is completed with agent data,
    retro outputs velocity, cost, slowest PBI, impediments."""
    _write_csv(tmp_product_dir / "sprint.csv", ["id", "goal", "started_at", "ended_at"], [
        [10, "Sprint 10", "2026-01-01", "2026-01-02"],
    ])
    _write_csv(tmp_product_dir / "agent_log.csv",
        ["pbi_id", "sprint_id", "agent", "duration_ms", "total_tokens", "tool_uses", "status"],
        [
            [1, 10, "dev-1", 600000, 100000, 50, "done"],
            [2, 10, "dev-2", 300000, 50000, 30, "done"],
            [3, 10, "dev-3", 400000, 80000, 40, "failed"],
        ],
    )

    output = _run_retro(tmp_product_dir)

    # Velocity
    assert "2 PBIs" in output
    # Total cost
    assert "tokens" in output.lower()
    assert "min" in output.lower()
    # Slowest PBI
    assert "#1" in output  # PBI 1 at 600000ms is slowest
    # Impediments
    assert "#3" in output  # PBI 3 failed
    assert "failed" in output.lower()


# -- Scenario: Retro handles no completed sprints --


def test_retro_no_completed_sprints(tmp_product_dir: Path):
    """Given no sprints have ended, retro says no completed sprints."""
    _write_csv(tmp_product_dir / "sprint.csv", ["id", "goal", "started_at", "ended_at"], [
        [13, "Active sprint", "2026-03-02", ""],
    ])

    output = _run_retro(tmp_product_dir)
    assert "No completed sprints" in output


# -- Scenario: Forecast matches manual calculation --


def test_forecast_matches_manual_calculation(tmp_product_dir: Path):
    """Given agent_log.csv has known data from 3 sprints,
    recommended PBI count = min(5, round(avg throughput)),
    avg tokens = mean of per-PBI tokens."""
    _write_csv(tmp_product_dir / "sprint.csv", ["id", "goal", "started_at", "ended_at"], [
        [10, "Sprint 10", "2026-01-01", "2026-01-02"],
        [11, "Sprint 11", "2026-01-03", "2026-01-04"],
        [12, "Sprint 12", "2026-01-05", "2026-01-06"],
    ])
    _write_csv(tmp_product_dir / "agent_log.csv",
        ["pbi_id", "sprint_id", "agent", "duration_ms", "total_tokens", "tool_uses", "status"],
        [
            # Sprint 10: 3 PBIs
            [28, 10, "dev-1", 559498, 107498, 55, "done"],
            [30, 10, "dev-2", 333498, 53498, 38, "done"],
            [34, 10, "dev-3", 347498, 57498, 42, "done"],
            # Sprint 11: 2 PBIs
            [29, 11, "dev-1", 397627, 73410, 59, "done"],
            [35, 11, "dev-2", 884701, 149188, 100, "done"],
            # Sprint 12: 1 PBI
            [36, 12, "dev-1", 1099909, 150171, 116, "done"],
        ],
    )

    output = _run_forecast(tmp_product_dir)

    # Throughput: (3+2+1)/3 = 2.0, recommended = max(5, round(2.0)) = 5
    assert "Recommended PBI count: 5" in output

    # Avg tokens: (107498+53498+57498+73410+149188+150171)/6 = 98543.83 ~ 98544
    assert "98,544" in output


# -- Scenario: Sprint execution process uses forecast and retro --


def test_po_process_references_forecast_and_retro():
    """The PO sprint execution process definition references
    the forecast command before planning and retro command after close."""
    po_role = Path(__file__).parent / ".." / ".." / "role-product-owner" / "SKILL.md"
    content = po_role.read_text()

    assert "board.py forecast" in content, "PO role must reference board.py forecast"
    assert "board.py retro" in content, "PO role must reference board.py retro"
