"""Tests for `board.py sprint check` — feature 52-sprint-readiness."""

import csv
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BOARD_DIR = Path(__file__).parent


def _git(repo: Path, *args: str) -> None:
    """Run a git command in the given repo."""
    subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )


def _setup_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with sprint data for testing."""
    repo = tmp_path / "repo"
    product = repo / "product"
    product.mkdir(parents=True)

    # Minimal sprint.csv (active sprint)
    (product / "sprint.csv").write_text(
        "id,goal,started_at,ended_at\n0,test,2026-01-01,\n"
    )

    # sprint_log.csv (empty)
    (product / "sprint_log.csv").write_text(
        "pbi_id,title,sprint_id,done_at,cause_id,feature_file,doc\n"
    )

    # product_backlog.csv (empty)
    (product / "product_backlog.csv").write_text(
        "id,title,status,cause_id,feature_file,doc\n"
    )

    # Create worktree pool directories
    pool = repo / ".claude" / "worktrees"
    for i in range(1, 6):
        (pool / f"dev-{i}").mkdir(parents=True)

    # Init git repo so git status works
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    return repo


def _write_sprint_backlog(product: Path, rows: list[dict]) -> None:
    """Write sprint_backlog.csv with given rows."""
    sb = product / "sprint_backlog.csv"
    with open(sb, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["pbi_id", "title", "feature_file", "doc", "cause_id"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _check(repo: Path) -> tuple[list[tuple[str, bool, str]], bool]:
    """Run sprint_check and return (results, all_pass)."""
    # Import here to avoid module-level side effects
    import importlib.util

    spec = importlib.util.spec_from_file_location("board", BOARD_DIR / "board.py")
    assert spec and spec.loader
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)

    results = board.sprint_check(repo)
    all_pass = all(passed for _, passed, _ in results)
    return results, all_pass


def _find_check(results: list[tuple[str, bool, str]], label: str) -> tuple[str, bool, str]:
    """Find a check result by label."""
    for r in results:
        if r[0] == label:
            return r
    raise KeyError(f"Check '{label}' not found in results")


# -- Scenario: All checks pass --


def test_all_checks_pass(tmp_path: Path) -> None:
    """Given a sprint with PBIs, clean git, worktrees, and all files exist."""
    repo = _setup_repo(tmp_path)
    product = repo / "product"

    # Create PBI doc and feature file
    pbi_doc = product / "product_backlog"
    pbi_doc.mkdir(parents=True, exist_ok=True)
    (pbi_doc / "1.md").write_text("# PBI 1\n")
    feature = repo / "features"
    feature.mkdir(parents=True, exist_ok=True)
    (feature / "1-test.feature").write_text("Feature: Test\n")

    _write_sprint_backlog(
        product,
        [
            {
                "pbi_id": "1",
                "title": "Test PBI",
                "feature_file": "features/1-test.feature",
                "doc": "product/product_backlog/1.md",
                "cause_id": "",
            }
        ],
    )

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add pbi")

    results, all_pass = _check(repo)
    assert all_pass, f"Expected all PASS: {results}"
    assert all(passed for _, passed, _ in results)
    # Every check is present
    labels = {r[0] for r in results}
    assert labels == {"Sprint active", "Git clean", "Worktree pool", "PBI docs", "Feature files"}


# -- Scenario: Sprint not started --


def test_sprint_not_started(tmp_path: Path) -> None:
    """Given no sprint is active (empty sprint_backlog)."""
    repo = _setup_repo(tmp_path)
    product = repo / "product"

    _write_sprint_backlog(product, [])
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "empty sprint")

    results, all_pass = _check(repo)
    assert not all_pass
    label, passed, detail = _find_check(results, "Sprint active")
    assert not passed
    assert "no PBIs" in detail


# -- Scenario: Git is dirty --


def test_git_dirty(tmp_path: Path) -> None:
    """Given uncommitted changes exist."""
    repo = _setup_repo(tmp_path)
    product = repo / "product"

    _write_sprint_backlog(
        product,
        [{"pbi_id": "1", "title": "Test", "feature_file": "", "doc": "", "cause_id": ""}],
    )
    # Don't commit — leaves dirty state

    results, all_pass = _check(repo)
    assert not all_pass
    label, passed, detail = _find_check(results, "Git clean")
    assert not passed
    assert "uncommitted" in detail


# -- Scenario: Missing PBI doc --


def test_missing_pbi_doc(tmp_path: Path) -> None:
    """Given a sprint PBI references a doc file that does not exist."""
    repo = _setup_repo(tmp_path)
    product = repo / "product"

    _write_sprint_backlog(
        product,
        [
            {
                "pbi_id": "1",
                "title": "Test",
                "feature_file": "",
                "doc": "product/product_backlog/1.md",
                "cause_id": "",
            }
        ],
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "missing doc")

    results, all_pass = _check(repo)
    assert not all_pass
    label, passed, detail = _find_check(results, "PBI docs")
    assert not passed
    assert "product/product_backlog/1.md" in detail


# -- Scenario: Missing worktree --


def test_missing_worktree(tmp_path: Path) -> None:
    """Given a worktree directory is missing from the pool."""
    repo = _setup_repo(tmp_path)
    product = repo / "product"

    # Remove one worktree directory
    shutil.rmtree(repo / ".claude" / "worktrees" / "dev-3")

    _write_sprint_backlog(
        product,
        [{"pbi_id": "1", "title": "Test", "feature_file": "", "doc": "", "cause_id": ""}],
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "missing wt")

    results, all_pass = _check(repo)
    assert not all_pass
    label, passed, detail = _find_check(results, "Worktree pool")
    assert not passed
    assert "dev-3" in detail


# -- Scenario: Failed check identifies what to fix --


def test_missing_doc_identifies_file(tmp_path: Path) -> None:
    """The output identifies the exact file that is missing."""
    repo = _setup_repo(tmp_path)
    product = repo / "product"

    _write_sprint_backlog(
        product,
        [
            {
                "pbi_id": "99",
                "title": "Missing doc",
                "feature_file": "",
                "doc": "product/product_backlog/99.md",
                "cause_id": "",
            }
        ],
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "missing doc 99")

    results, all_pass = _check(repo)
    assert not all_pass
    label, passed, detail = _find_check(results, "PBI docs")
    assert not passed
    assert "product/product_backlog/99.md" in detail


# -- Scenario: Sprint execution process gates on readiness check --


def test_po_role_gates_on_check() -> None:
    """The PO sprint execution process definition runs check before spawning."""
    po_role = BOARD_DIR / ".." / ".." / "role-product-owner" / "SKILL.md"
    content = po_role.read_text()
    # Verify the PO role mentions sprint check
    assert "sprint check" in content
    # Verify check comes before the "worktree pool" step
    check_pos = content.find("sprint check")
    pool_pos = content.find("worktree pool")
    assert pool_pos > 0, "worktree pool step must exist"
    assert check_pos < pool_pos, "sprint check must appear before worktree pool step"
