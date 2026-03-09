"""Tests for reject command and rejected_backlog integration."""

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
    """Create a temporary product directory with CSVs.
    schema.sql is loaded from SCRIPT_DIR (next to board.py), not PRODUCT_DIR."""
    _write_csv(tmp_path / "product_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[10, "I may use approach A", "approach", 1, "", ""]])
    _write_csv(tmp_path / "rejected_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"], [])
    _write_csv(tmp_path / "sprint.csv",
               ["id", "goal", "started_at", "ended_at"], [])
    _write_csv(tmp_path / "sprint_backlog.csv",
               ["pbi_id", "title", "feature_file", "doc", "cause_id"], [])
    _write_csv(tmp_path / "sprint_log.csv",
               ["pbi_id", "title", "sprint_id", "done_at", "cause_id",
                "feature_file", "doc", "outcome"], [])
    _write_csv(tmp_path / "agent_log.csv",
               ["pbi_id", "sprint_id", "agent", "duration_ms",
                "total_tokens", "tool_uses", "status"], [])

    return tmp_path


def test_reject_moves_pbi_to_rejected_backlog(tmp_product_dir: Path):
    """Rejecting a PBI removes it from product_backlog and appends to rejected_backlog."""
    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            board._reject(10)

    # Gone from product_backlog
    with open(tmp_product_dir / "product_backlog.csv") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 1  # header only

    # Present in rejected_backlog
    with open(tmp_product_dir / "rejected_backlog.csv") as f:
        reader = csv.DictReader(f)
        rejected = list(reader)
    assert len(rejected) == 1
    assert rejected[0]["id"] == "10"
    assert rejected[0]["status"] == "rejected"


def test_reject_pbi_not_found(tmp_product_dir: Path):
    """Rejecting a non-existent PBI prints error and exits."""
    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        with pytest.raises(SystemExit) as exc_info:
            board._reject(999)
    assert exc_info.value.code == 1


def test_assess_ineffective_shows_rejected_context(tmp_product_dir: Path):
    """Marking PBI ineffective shows subtree with rejected siblings and restore hints."""
    # Setup: a done PBI with cause_id=1, and rejected siblings with same cause_id
    _write_csv(tmp_product_dir / "sprint_log.csv",
               ["pbi_id", "title", "sprint_id", "done_at", "cause_id",
                "feature_file", "doc", "outcome"],
               [[20, "I must use approach X", "0", "2026-01-01", 1, "", "", ""]])
    _write_csv(tmp_product_dir / "rejected_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[30, "I may use approach Y", "rejected", 1, "", ""],
                [31, "I may use approach Z", "rejected", 1, "", ""]])
    # Parent value in product_backlog
    _write_csv(tmp_product_dir / "product_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[1, "I wish to solve problem", "done", "", "", ""]])

    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf), patch("sys.stdout.isatty", return_value=False):
            board._assess(20, "ineffective")

    output = buf.getvalue()
    # Tree contains root, ineffective PBI, and rejected siblings
    assert "1," in output  # root in CSV tree
    assert "20," in output
    assert "30," in output
    assert "31," in output
    assert "board.py restore 30" in output
    assert "board.py restore 31" in output


def test_assess_ineffective_no_cause_id(tmp_product_dir: Path):
    """Marking PBI ineffective without cause_id produces no rejected context."""
    _write_csv(tmp_product_dir / "sprint_log.csv",
               ["pbi_id", "title", "sprint_id", "done_at", "cause_id",
                "feature_file", "doc", "outcome"],
               [[20, "I must do something", "0", "2026-01-01", "", "", "", ""]])

    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            board._assess(20, "ineffective")

    output = buf.getvalue()
    assert "marked ineffective" in output
    # No tree output — no cause_id
    assert "board.py restore" not in output


def test_restore_without_doc_sets_describe(tmp_product_dir: Path):
    """Restoring a rejected PBI without doc sets status=describe."""
    _write_csv(tmp_product_dir / "rejected_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[30, "I may use approach Y", "rejected", 1, "", ""]])

    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            board._restore(30)

    output = buf.getvalue()
    assert "product_backlog [describe]" in output

    with open(tmp_product_dir / "product_backlog.csv") as f:
        reader = csv.DictReader(f)
        restored = [r for r in reader if r["id"] == "30"]
    assert restored[0]["status"] == "describe"


def test_restore_with_doc_sets_problem(tmp_product_dir: Path):
    """Restoring a rejected PBI with doc sets status=problem."""
    _write_csv(tmp_product_dir / "rejected_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[30, "I may use approach Y", "rejected", 1, "", "product/product_backlog/30.md"]])

    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            board._restore(30)

    output = buf.getvalue()
    assert "product_backlog [problem]" in output

    with open(tmp_product_dir / "product_backlog.csv") as f:
        reader = csv.DictReader(f)
        restored = [r for r in reader if r["id"] == "30"]
    assert restored[0]["status"] == "problem"


def test_restore_pbi_not_found(tmp_product_dir: Path):
    """Restoring a non-existent PBI prints error and exits."""
    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        with pytest.raises(SystemExit) as exc_info:
            board._restore(999)
    assert exc_info.value.code == 1


def test_tree_shows_rejected_from_separate_file(tmp_product_dir: Path):
    """Tree includes items from rejected_backlog.csv with loc=rejected."""
    _write_csv(tmp_product_dir / "rejected_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[58, "I may assess using form controls", "rejected", 6, "", ""]])
    _write_csv(tmp_product_dir / "product_backlog.csv",
               ["id", "title", "status", "cause_id", "feature_file", "doc"],
               [[6, "I wish easy assessment", "approach", "", "", ""]])

    with patch.object(board, "PRODUCT_DIR", tmp_product_dir):
        with patch.object(board, "REPO_ROOT", tmp_product_dir.parent):
            buf = io.StringIO()
            with patch("sys.stdout", buf), patch("sys.stdout.isatty", return_value=False):
                board._tree()

    output = buf.getvalue()
    assert "58" in output
    assert "rejected" in output
