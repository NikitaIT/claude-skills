"""Scrum board CLI — role-specific views over CSV data via SQLite."""

import argparse
import csv
import datetime
import io
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import NotRequired, TypedDict


class PBI(TypedDict):
    id: int
    title: str
    loc: str
    cause_id: int | None
    feature_file: str | None
    doc: str | None
    status: NotRequired[str]


SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = Path(
    subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
)
PRODUCT_DIR = REPO_ROOT / "product"


def _main_repo_root() -> Path:
    """Return the main (non-worktree) repository root."""
    git_common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    return Path(git_common).parent


VIEWS: dict[str, str] = {
    "sprint": "SELECT * FROM current_sprint",
    "dev": "SELECT * FROM dev_sprint_board",
    "po": "SELECT * FROM po_backlog",
    "throughput": "SELECT * FROM po_throughput",
    "sm": "SELECT * FROM sm_sprint_health",
    "log": """
        SELECT sl.pbi_id, sl.title, s.goal, sl.done_at
        FROM sprint_log sl
        JOIN sprint s ON sl.sprint_id = s.id
        ORDER BY sl.done_at
    """,
}


def _load_db() -> sqlite3.Connection:
    """Load CSVs into in-memory SQLite, create views from schema.sql."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row

    schema = SCRIPT_DIR / "schema.sql"
    db.executescript(schema.read_text())

    tables = {
        "backlog": PRODUCT_DIR / "product_backlog.csv",
        "sprint": PRODUCT_DIR / "sprint.csv",
        "sprint_backlog": PRODUCT_DIR / "sprint_backlog.csv",
        "sprint_log": PRODUCT_DIR / "sprint_log.csv",
        "agent_log": PRODUCT_DIR / "agent_log.csv",
        "rejected_backlog": PRODUCT_DIR / "rejected_backlog.csv",
    }
    for table, path in tables.items():
        if not path.exists():
            continue
        with open(path) as f:
            reader = csv.reader(f)
            headers = next(reader)
            cols = ", ".join(headers)
            placeholders = ", ".join("?" * len(headers))
            db.executemany(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                ([v or None for v in row] for row in reader),
            )
    db.commit()
    return db


def _print_csv(rows: list[sqlite3.Row]) -> None:
    if not rows:
        return
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(rows[0].keys())
    for r in rows:
        writer.writerow(tuple(r))
    print(out.getvalue(), end="")


def _print_table(rows: list[sqlite3.Row]) -> None:
    if not rows:
        return
    headers = rows[0].keys()
    cols = [
        [str(v) if v is not None else "" for v in (r[h] for r in rows)] for h in headers
    ]
    widths = [
        max(len(h), max((len(v) for v in col), default=0))
        for h, col in zip(headers, cols)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(fmt.format(*(str(v) if v is not None else "" for v in tuple(r))))


def _print(rows: list[sqlite3.Row]) -> None:
    if sys.stdout.isatty():
        _print_table(rows)
    else:
        _print_csv(rows)


def _remove_csv_row(path: Path, id_value: str) -> None:
    """Remove row where first column matches id_value."""
    with open(path) as f:
        rows = list(csv.reader(f))
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        for r in rows:
            if r and r[0] != id_value:
                writer.writerow(r)


def _current_sprint(db: sqlite3.Connection) -> sqlite3.Row:
    sprint = db.execute("SELECT id FROM current_sprint").fetchone()
    if not sprint:
        print("No active sprint (all sprints have ended_at)", file=sys.stderr)
        sys.exit(1)
    return sprint


# -- Actions -----------------------------------------------------------


def _select(pbi_id: int) -> None:
    """Sprint Planning: move PBI from product_backlog → sprint_backlog."""
    db = _load_db()

    row = db.execute(
        "SELECT id, title, feature_file, doc, cause_id FROM backlog WHERE id = ?",
        (pbi_id,),
    ).fetchone()
    if not row:
        print(f"PBI #{pbi_id} not found in product_backlog.csv", file=sys.stderr)
        sys.exit(1)

    _current_sprint(db)  # ensure active sprint exists

    # append to sprint_backlog.csv
    sb_path = PRODUCT_DIR / "sprint_backlog.csv"
    with open(sb_path, "a", newline="") as f:
        csv.writer(f).writerow(
            [
                row["id"],
                row["title"],
                row["feature_file"] or "",
                row["doc"] or "",
                row["cause_id"] or "",
            ]
        )

    # remove from product_backlog.csv
    _remove_csv_row(PRODUCT_DIR / "product_backlog.csv", str(pbi_id))

    print(f'#{pbi_id} "{row["title"]}" → sprint_backlog')


def _done(pbi_id: int) -> None:
    """DoD met: move PBI from sprint_backlog → sprint_log."""
    db = _load_db()

    row = db.execute(
        "SELECT pbi_id, title, cause_id, feature_file, doc"
        " FROM sprint_backlog WHERE pbi_id = ?",
        (pbi_id,),
    ).fetchone()
    if not row:
        print(f"PBI #{pbi_id} not found in sprint_backlog.csv", file=sys.stderr)
        sys.exit(1)

    sprint = _current_sprint(db)
    today = datetime.date.today().isoformat()

    # append to sprint_log.csv
    log_path = PRODUCT_DIR / "sprint_log.csv"
    with open(log_path, "a", newline="") as f:
        csv.writer(f).writerow(
            [
                pbi_id,
                row["title"],
                sprint["id"],
                today,
                row["cause_id"] or "",
                row["feature_file"] or "",
                row["doc"] or "",
                "",  # outcome
            ]
        )

    # remove from sprint_backlog.csv
    _remove_csv_row(PRODUCT_DIR / "sprint_backlog.csv", str(pbi_id))

    print(f'#{pbi_id} "{row["title"]}" → sprint_log (sprint {sprint["id"]}, {today})')


def _sprint_start(goal: str) -> None:
    """Create a new sprint with the given goal."""
    db = _load_db()

    existing = db.execute("SELECT id FROM current_sprint").fetchone()
    if existing:
        print(
            f"Sprint {existing['id']} is still active. End it first.", file=sys.stderr
        )
        sys.exit(1)

    last = db.execute("SELECT MAX(id) AS max_id FROM sprint").fetchone()
    new_id = (last["max_id"] or -1) + 1
    today = datetime.date.today().isoformat()

    sprint_path = PRODUCT_DIR / "sprint.csv"
    with open(sprint_path, "a", newline="") as f:
        csv.writer(f).writerow([new_id, goal, today, ""])

    print(f'Sprint {new_id} started: "{goal}" ({today})')


def _sprint_end() -> None:
    """Close the current sprint (set ended_at = today)."""
    db = _load_db()
    sprint = _current_sprint(db)
    today = datetime.date.today().isoformat()

    sprint_path = PRODUCT_DIR / "sprint.csv"
    with open(sprint_path) as f:
        rows = list(csv.reader(f))
    with open(sprint_path, "w", newline="") as f:
        writer = csv.writer(f)
        for r in rows:
            if r and r[0] == str(sprint["id"]):
                r[3] = today
            writer.writerow(r)

    print(f"Sprint {sprint['id']} ended ({today})")


ALL_STATUSES = [
    "done",
    "effective",
    "ineffective",
    "sprint",
    "describe",
    "problem",
    "rejected",
    "approach",
    "design",
]


def _effective_loc(item: PBI) -> str:
    """Return display location (backlog items with status=done → done)."""
    loc = item["loc"]
    if loc == "backlog" and item.get("status") == "done":
        return "done"
    return loc


def _load_all_items(db: sqlite3.Connection) -> dict[int, PBI]:
    """Gather all PBIs from every tracking CSV into a single dict."""
    items: dict[int, PBI] = {}

    for r in db.execute(
        "SELECT pbi_id, title, cause_id, outcome, feature_file, doc FROM sprint_log"
    ).fetchall():
        items[r["pbi_id"]] = {
            "id": r["pbi_id"],
            "title": r["title"],
            "loc": r["outcome"] if r["outcome"] else "done",
            "cause_id": r["cause_id"],
            "feature_file": r["feature_file"],
            "doc": r["doc"],
        }

    for r in db.execute(
        "SELECT pbi_id, title, cause_id, feature_file, doc FROM sprint_backlog"
    ).fetchall():
        items[r["pbi_id"]] = {
            "id": r["pbi_id"],
            "title": r["title"],
            "loc": "sprint",
            "cause_id": r["cause_id"],
            "feature_file": r["feature_file"],
            "doc": r["doc"],
        }

    for r in db.execute(
        "SELECT id, title, status, cause_id, feature_file, doc FROM backlog"
    ).fetchall():
        items[r["id"]] = {
            "id": r["id"],
            "title": r["title"],
            "loc": "backlog",
            "status": r["status"],
            "cause_id": r["cause_id"],
            "feature_file": r["feature_file"],
            "doc": r["doc"],
        }

    for r in db.execute(
        "SELECT id, title, cause_id, feature_file, doc FROM rejected_backlog"
    ).fetchall():
        items[r["id"]] = {
            "id": r["id"],
            "title": r["title"],
            "loc": "rejected",
            "cause_id": r["cause_id"],
            "feature_file": r["feature_file"],
            "doc": r["doc"],
        }

    return items


def _build_tree(
    items: dict[int, PBI],
) -> tuple[list[PBI], dict[int, list[PBI]]]:
    """Build parent→children map and root list from items."""
    children: dict[int, list[PBI]] = defaultdict(list)
    roots: list[PBI] = []
    for item in items.values():
        cid = item.get("cause_id")
        if cid and cid in items:
            children[cid].append(item)
        else:
            roots.append(item)
    roots.sort(key=lambda x: x["id"])
    for kids in children.values():
        kids.sort(key=lambda x: x["id"])
    return roots, children


def _tree(
    *,
    depth: int | None = None,
    statuses: list[str] | None = None,
) -> None:
    """Show all PBIs as a tree organized by cause_id."""
    status_set: set[str] | None = set(statuses) if statuses else None
    db = _load_db()
    items = _load_all_items(db)
    roots, children = _build_tree(items)

    if sys.stdout.isatty():
        _tree_tty(roots, children, depth=depth, statuses=status_set)
    else:
        _tree_csv(items, statuses=status_set)


def _osc8(url: str, text: str) -> str:
    """Wrap text in an OSC 8 terminal hyperlink."""
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def _tree_tty(
    roots: list[PBI],
    children: dict[int, list[PBI]],
    *,
    depth: int | None = None,
    statuses: set[str] | None = None,
) -> None:
    """Colored tree for terminal."""
    LOC_STYLE = {
        "done": ("\033[32m", "✓"),  # green
        "effective": ("\033[1;32m", "★"),  # bold green
        "ineffective": ("\033[31m", "✗"),  # red
        "sprint": ("\033[33m", "●"),  # yellow
        "backlog": ("\033[0m", "○"),  # default
        "rejected": ("\033[2m", "⊘"),  # dim, circle-slash
    }
    STATUS_COLOR = {
        "describe": "\033[2m",  # dim
        "problem": "\033[0m",  # default
        "approach": "\033[36m",  # cyan
        "design": "\033[34m",  # blue
    }
    RESET = "\033[0m"

    def _matches(item: PBI) -> bool:
        if statuses is None:
            return True
        loc = _effective_loc(item)
        status = item.get("status", "")
        return loc in statuses or status in statuses

    def _has_matching_descendant(item: PBI) -> bool:
        for child in children.get(item["id"], []):
            if _matches(child) or _has_matching_descendant(child):
                return True
        return False

    def _render(item: PBI, prefix: str, is_last: bool, level: int) -> None:
        if depth is not None and level > depth:
            return
        if (
            statuses is not None
            and not _matches(item)
            and not _has_matching_descendant(item)
        ):
            return

        connector = "└── " if is_last else "├── "
        loc = _effective_loc(item)
        status = item.get("status", "")
        color, marker = LOC_STYLE.get(loc, ("\033[0m", "?"))
        if loc == "backlog":
            color = STATUS_COLOR.get(status, "\033[0m")
        tag = f" [{status}]" if loc == "backlog" else ""

        # Wrap marker in hyperlink to feature file
        feature_file = item.get("feature_file")
        if feature_file:
            feature_path = (REPO_ROOT / feature_file).resolve()
            marker = _osc8(feature_path.as_uri(), marker)

        # Wrap #id in hyperlink to doc file
        doc = item.get("doc")
        id_text = f"#{item['id']}"
        if doc:
            doc_path = (REPO_ROOT / doc).resolve()
            id_text = _osc8(doc_path.as_uri(), id_text)
        title_text = f"{id_text} {item['title']}{tag}"

        print(f"{prefix}{connector}{color}{marker} {title_text}{RESET}")

        child_prefix = prefix + ("    " if is_last else "│   ")
        kids = children.get(item["id"], [])
        visible = [c for c in kids if depth is None or level + 1 <= depth]
        if statuses is not None:
            visible = [c for c in visible if _matches(c) or _has_matching_descendant(c)]
        for i, child in enumerate(visible):
            _render(child, child_prefix, i == len(visible) - 1, level + 1)

    visible_roots = roots
    if statuses is not None:
        visible_roots = [r for r in roots if _matches(r) or _has_matching_descendant(r)]
    for i, root in enumerate(visible_roots):
        _render(root, "", i == len(visible_roots) - 1, 0)

    print()
    DIM = "\033[2m"
    R = "\033[0m"
    print(
        f"{DIM}○{R} describe → {R}○{R} problem ─┬→ "
        f"\033[36m○{R} approach → \033[34m○{R} design → "
        f"\033[33m●{R} sprint → \033[32m✓{R} done ─┬→ "
        f"\033[1;32m★{R} effective\n"
        f"                        "
        f"└→ {DIM}⊘ rejected{R}"
        f"                                 "
        f"└→ \033[31m✗{R} ineffective\n"
        f"\n"
        f"{DIM}"
        f"  select <id>    design → sprint\n"
        f"  reject <id>    problem → rejected\n"
        f"  done <id>      sprint → done\n"
        f"  assess <id>    done → effective | ineffective\n"
        f"  restore <id>   rejected → describe | problem\n"
        f"  rejected <id>  show alternatives for ineffective PBI"
        f"{R}"
    )


def _tree_csv(items: dict[int, PBI], *, statuses: set[str] | None = None) -> None:
    """Flat CSV for programmatic consumption."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "title", "location", "status", "cause_id"])
    for item in sorted(items.values(), key=lambda x: x["id"]):
        if statuses is not None and not (
            _effective_loc(item) in statuses or item.get("status", "") in statuses
        ):
            continue
        loc = item["loc"]
        status = item.get("status", "")
        # For effective/ineffective, show in status column too
        if loc in ("effective", "ineffective"):
            status = loc
        writer.writerow(
            [item["id"], item["title"], loc, status, item.get("cause_id", "")]
        )
    print(out.getvalue(), end="")


# -- Sprint check ------------------------------------------------------


def sprint_check(repo_root: Path | None = None) -> list[tuple[str, bool, str]]:
    """Validate sprint readiness: 5 read-only checks.

    Returns list of (label, passed, detail) tuples.
    """
    if repo_root is None:
        repo_root = PRODUCT_DIR.parent
    product_dir = repo_root / "product"
    results: list[tuple[str, bool, str]] = []

    # 1. Sprint active — sprint_backlog.csv has ≥1 row (after header)
    sb_path = product_dir / "sprint_backlog.csv"
    if sb_path.exists():
        with open(sb_path) as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            rows = list(reader)
        if rows:
            results.append(("Sprint active", True, ""))
        else:
            results.append(("Sprint active", False, "sprint_backlog.csv has no PBIs"))
    else:
        results.append(("Sprint active", False, "sprint_backlog.csv not found"))

    # 2. Git clean — git status --porcelain is empty
    try:
        output = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        ).stdout.strip()
        if output:
            results.append(("Git clean", False, "uncommitted changes"))
        else:
            results.append(("Git clean", True, ""))
    except subprocess.CalledProcessError:
        results.append(("Git clean", False, "git status failed"))

    # 3. Worktree pool — .claude/worktrees/dev-{1..5} all exist
    pool_dir = repo_root / ".claude" / "worktrees"
    missing_wt: list[str] = []
    for i in range(1, 6):
        wt = pool_dir / f"dev-{i}"
        if not wt.is_dir():
            missing_wt.append(str(wt.relative_to(repo_root)))
    if missing_wt:
        results.append(("Worktree pool", False, " ".join(missing_wt) + " not found"))
    else:
        results.append(("Worktree pool", True, ""))

    # 4. PBI docs — every doc value in sprint_backlog.csv exists
    missing_docs: list[str] = []
    if sb_path.exists():
        with open(sb_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                doc = row.get("doc", "").strip()
                if doc and not (repo_root / doc).exists():
                    missing_docs.append(doc)
    if missing_docs:
        results.append(("PBI docs", False, " ".join(missing_docs) + " not found"))
    else:
        results.append(("PBI docs", True, ""))

    # 5. Feature files — every non-empty feature_file in sprint_backlog.csv exists
    missing_features: list[str] = []
    if sb_path.exists():
        with open(sb_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ff = row.get("feature_file", "").strip()
                if ff and not (repo_root / ff).exists():
                    missing_features.append(ff)
    if missing_features:
        results.append(
            ("Feature files", False, " ".join(missing_features) + " not found")
        )
    else:
        results.append(("Feature files", True, ""))

    return results


def _check_ids() -> None:
    """Check that every PBI doc has a matching row in CSV tracking files."""
    doc_dir = PRODUCT_DIR / "product_backlog"
    doc_ids = {int(p.stem) for p in doc_dir.glob("*.md") if p.stem.isdigit()}

    tracked: set[int] = set()
    for csv_file in (
        "product_backlog.csv",
        "rejected_backlog.csv",
        "sprint_backlog.csv",
        "sprint_log.csv",
    ):
        path = PRODUCT_DIR / csv_file
        if not path.exists():
            continue
        with open(path) as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if row and row[0].strip().isdigit():
                    tracked.add(int(row[0]))

    missing = sorted(doc_ids - tracked)
    if missing:
        print(f"Untracked PBI docs: {', '.join(f'#{i}' for i in missing)}")
        sys.exit(1)


def _sprint_check() -> None:
    """CLI wrapper: print results table and exit 0/1."""
    results = sprint_check()

    label_width = max(len(r[0]) for r in results)
    all_pass = True
    for label, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        line = f"{label:<{label_width}}  {status}"
        if not passed:
            all_pass = False
            if detail:
                line += f"  {detail}"
        print(line)

    sys.exit(0 if all_pass else 1)


# -- Reports -----------------------------------------------------------


def _forecast() -> None:
    """Capacity forecast: avg tokens, duration, throughput over last 3 sprints."""
    db = _load_db()

    # Get completed sprints that have agent data
    sprints = db.execute(
        """
        SELECT DISTINCT al.sprint_id
        FROM agent_log al
        JOIN sprint s ON al.sprint_id = s.id
        WHERE s.ended_at IS NOT NULL AND s.ended_at != ''
          AND al.status = 'done'
        ORDER BY al.sprint_id DESC
        LIMIT 3
        """
    ).fetchall()

    if not sprints:
        print("No historical data — cannot forecast")
        return

    sprint_ids = [r["sprint_id"] for r in sprints]
    placeholders = ", ".join("?" * len(sprint_ids))

    # Per-PBI averages across those sprints
    stats = db.execute(
        f"""
        SELECT
            AVG(total_tokens) AS avg_tokens_per_pbi,
            AVG(duration_ms) / 1000 AS avg_duration_seconds_per_pbi
        FROM agent_log
        WHERE status = 'done' AND sprint_id IN ({placeholders})
        """,
        sprint_ids,
    ).fetchone()

    # Throughput: PBIs done per sprint
    throughput_rows = db.execute(
        f"""
        SELECT sprint_id, COUNT(*) AS pbis
        FROM agent_log
        WHERE status = 'done' AND sprint_id IN ({placeholders})
        GROUP BY sprint_id
        """,
        sprint_ids,
    ).fetchall()

    avg_throughput = sum(r["pbis"] for r in throughput_rows) / len(throughput_rows)
    recommended = max(5, round(avg_throughput))

    avg_tokens = round(stats["avg_tokens_per_pbi"])
    avg_duration = round(stats["avg_duration_seconds_per_pbi"])
    avg_duration_min = round(avg_duration / 60, 1)

    print(
        "Capacity Forecast (last {} sprint{})".format(
            len(sprint_ids), "s" if len(sprint_ids) > 1 else ""
        )
    )
    print("-" * 40)
    print(f"Avg tokens/PBI:       {avg_tokens:,}")
    print(f"Avg duration/PBI:     {avg_duration_min} min ({avg_duration}s)")
    print(f"Throughput:           {avg_throughput:.1f} PBIs/sprint")
    print(f"Recommended PBI count: {recommended}")


def _retro() -> None:
    """Sprint retrospective: velocity, cost, slowest PBI, impediments."""
    db = _load_db()

    # Find the latest completed sprint
    latest = db.execute(
        """
        SELECT id, goal FROM sprint
        WHERE ended_at IS NOT NULL AND ended_at != ''
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()

    if not latest:
        print("No completed sprints")
        return

    sprint_id = latest["id"]

    # This sprint's agent data
    sprint_data = db.execute(
        "SELECT * FROM agent_log WHERE sprint_id = ? AND status = 'done'",
        (sprint_id,),
    ).fetchall()

    velocity_this = len(sprint_data)

    # 3-sprint average (excluding current)
    avg_rows = db.execute(
        """
        SELECT sprint_id, COUNT(*) AS pbis
        FROM agent_log
        WHERE status = 'done' AND sprint_id != ?
          AND sprint_id IN (
            SELECT DISTINCT sprint_id FROM agent_log
            WHERE status = 'done' AND sprint_id != ?
            ORDER BY sprint_id DESC LIMIT 3
          )
        GROUP BY sprint_id
        """,
        (sprint_id, sprint_id),
    ).fetchall()

    if avg_rows:
        avg_velocity = sum(r["pbis"] for r in avg_rows) / len(avg_rows)
    else:
        avg_velocity = 0

    total_tokens = sum(r["total_tokens"] for r in sprint_data)
    total_duration_s = sum(r["duration_ms"] for r in sprint_data) / 1000
    total_duration_min = round(total_duration_s / 60, 1)

    if sprint_data:
        avg_tokens_pbi = round(total_tokens / len(sprint_data))
        avg_duration_pbi_min = round(total_duration_min / len(sprint_data), 1)
    else:
        avg_tokens_pbi = 0
        avg_duration_pbi_min = 0

    # Slowest PBI
    slowest = db.execute(
        """
        SELECT pbi_id, duration_ms / 1000 AS seconds
        FROM agent_log
        WHERE sprint_id = ? AND status = 'done'
        ORDER BY duration_ms DESC LIMIT 1
        """,
        (sprint_id,),
    ).fetchone()

    # Impediments
    impediments = db.execute(
        "SELECT pbi_id, agent, status, duration_ms / 1000 AS seconds"
        " FROM agent_log WHERE sprint_id = ? AND status != 'done'",
        (sprint_id,),
    ).fetchall()

    print(f"Sprint {sprint_id} Retrospective")
    print(f'Goal: "{latest["goal"]}"')
    print("-" * 40)
    if avg_velocity > 0:
        print(f"Velocity:             {velocity_this} PBIs (avg {avg_velocity:.1f})")
    else:
        print(f"Velocity:             {velocity_this} PBIs (no prior data for avg)")
    print(f"Total cost:           {total_tokens:,} tokens, {total_duration_min} min")
    print(
        f"Cost/PBI:             {avg_tokens_pbi:,} tokens, {avg_duration_pbi_min} min"
    )
    if slowest:
        slowest_min = round(slowest["seconds"] / 60, 1)
        print(f"Slowest PBI:          #{slowest['pbi_id']} ({slowest_min} min)")
    if impediments:
        print("Impediments:")
        for imp in impediments:
            print(
                f"  - PBI #{imp['pbi_id']} ({imp['agent']}): {imp['status']}"
                f" ({round(imp['seconds'] / 60, 1)} min)"
            )
    else:
        print("Impediments:          none")


def _agent_prompt(pbi_id: int, worktree_name: str) -> None:
    """Generate a ready-to-use developer agent prompt for a sprint PBI."""
    db = _load_db()

    row = db.execute(
        "SELECT pbi_id, title, feature_file, doc FROM sprint_backlog WHERE pbi_id = ?",
        (pbi_id,),
    ).fetchone()
    if not row:
        print(f"PBI {pbi_id} is not in the current sprint", file=sys.stderr)
        sys.exit(1)

    wt_path = _main_repo_root() / ".claude" / "worktrees" / worktree_name
    if not wt_path.is_dir():
        print(f"Worktree {worktree_name} not found at {wt_path}", file=sys.stderr)
        sys.exit(1)

    sprint = _current_sprint(db)

    wt = str(wt_path)
    pbi_doc = row["doc"] or ""
    feature_file = row["feature_file"] or ""
    title = row["title"]

    lines = [
        f"You are a Developer. Implement PBI #{pbi_id} from Sprint {sprint['id']}.",
        "",
        f"**Your working directory is `{wt}`.**",
        "IMPORTANT: For ALL file operations (Read, Write, Edit, Glob, Grep), use absolute paths"
        " starting with your working directory. For Bash commands, first run:",
        f"`cd {wt} && git fetch origin && git reset --hard origin/main`",
        "",
        "Load your role and coding context by reading:",
        f"- {wt}/.claude/skills/role-developer/SKILL.md",
        f"- {wt}/.claude/commands/context/coding.md",
        f"- {wt}/CLAUDE.md",
    ]

    if pbi_doc:
        lines.append("")
        lines.append(f"Then read the PBI: {wt}/{pbi_doc}")

    if feature_file:
        lines.append(f"And the feature file: {wt}/{feature_file}")

    lines.extend(
        [
            "",
            f"Task: {title}",
            "",
            "After implementing:",
            "1. Run `pnpm check` to verify everything passes",
            "2. Commit with message describing the achieved goal",
            "3. Push to remote",
            f"4. Run `uv run python .claude/skills/scripts/board/board.py done {pbi_id}`",
            "",
            "Write an ADR if you make a non-trivial architectural decision.",
            "Commit message should describe the achieved goal. Never add Co-Authored-By.",
        ]
    )

    print("\n".join(lines))


def _rejected_view(pbi_id: int) -> None:
    """Show nearest ancestor subtree that contains rejected alternatives."""
    db = _load_db()
    items = _load_all_items(db)

    if pbi_id not in items:
        print(f"PBI #{pbi_id} not found", file=sys.stderr)
        sys.exit(1)

    _, all_children = _build_tree(items)

    def _collect_subtree(node_id: int) -> set[int]:
        ids = {node_id}
        for child in all_children.get(node_id, []):
            ids |= _collect_subtree(child["id"])
        return ids

    # Walk up cause_id chain — stop at nearest ancestor with rejected children
    subtree_root = pbi_id
    current = pbi_id
    seen: set[int] = set()
    while True:
        cid = items[current].get("cause_id")
        if not cid or cid not in items or cid in seen:
            break
        seen.add(cid)
        subtree_root = cid
        if any(c["loc"] == "rejected" for c in all_children.get(cid, [])):
            break
        current = cid

    # Subtree of the found ancestor
    subtree_ids = _collect_subtree(subtree_root)

    # Ancestor path above subtree_root (for context, no sibling expansion)
    path_ids: set[int] = set()
    cur = subtree_root
    while True:
        cid = items[cur].get("cause_id")
        if not cid or cid not in items or cid in path_ids:
            break
        path_ids.add(cid)
        cur = cid

    display_ids = subtree_ids | path_ids
    display_items = {k: v for k, v in items.items() if k in display_ids}
    roots, children = _build_tree(display_items)

    if sys.stdout.isatty():
        _tree_tty(roots, children)
    else:
        _tree_csv(display_items)

    # Restore hints for rejected items in the subtree
    rejected = [items[i] for i in sorted(subtree_ids) if items[i]["loc"] == "rejected"]
    if rejected:
        print("Restore with:")
        for r in rejected:
            print(f"  board.py restore {r['id']}")


def _assess(pbi_id: int, outcome: str) -> None:
    """Mark a done PBI as effective or ineffective."""
    if outcome not in ("effective", "ineffective"):
        print(
            f"Invalid outcome '{outcome}'. Use 'effective' or 'ineffective'.",
            file=sys.stderr,
        )
        sys.exit(1)

    log_path = PRODUCT_DIR / "sprint_log.csv"
    rows: list[list[str]] = []
    found = False
    row_cause_id: int | None = None

    with open(log_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows.append(header)
        outcome_idx = header.index("outcome")
        title_idx = header.index("title")
        cause_id_idx = header.index("cause_id")
        for row in reader:
            if row and int(row[0]) == pbi_id:
                found = True
                row[outcome_idx] = outcome
                raw = row[cause_id_idx].strip()
                row_cause_id = int(raw) if raw else None
                if outcome == "ineffective":
                    # "I must" → "I must not", "I may" → "I would not"
                    title = row[title_idx]
                    title = title.replace("I must ", "I must not ")
                    title = title.replace("I may ", "I would not ")
                    row[title_idx] = title
                    print(f"PBI #{pbi_id} marked ineffective: {title}")
                else:
                    print(f"PBI #{pbi_id} marked effective: {row[title_idx]}")
            rows.append(row)

    if not found:
        print(f"PBI #{pbi_id} not found in sprint_log", file=sys.stderr)
        sys.exit(1)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerows(rows)
    log_path.write_text(out.getvalue())

    if outcome == "ineffective" and row_cause_id is not None:
        _rejected_view(pbi_id)


def _reject(pbi_id: int) -> None:
    """Move PBI from product_backlog → rejected_backlog."""
    db = _load_db()

    row = db.execute(
        "SELECT id, title, status, cause_id, feature_file, doc FROM backlog WHERE id = ?",
        (pbi_id,),
    ).fetchone()
    if not row:
        print(f"PBI #{pbi_id} not found in product_backlog.csv", file=sys.stderr)
        sys.exit(1)

    # append to rejected_backlog.csv
    rb_path = PRODUCT_DIR / "rejected_backlog.csv"
    with open(rb_path, "a", newline="") as f:
        csv.writer(f).writerow(
            [
                row["id"],
                row["title"],
                "rejected",
                row["cause_id"] or "",
                row["feature_file"] or "",
                row["doc"] or "",
            ]
        )

    # remove from product_backlog.csv
    _remove_csv_row(PRODUCT_DIR / "product_backlog.csv", str(pbi_id))

    print(f'#{pbi_id} "{row["title"]}" → rejected_backlog')


def _restore(pbi_id: int) -> None:
    """Move PBI from rejected_backlog → product_backlog."""
    db = _load_db()
    row = db.execute(
        "SELECT id, title, cause_id, feature_file, doc FROM rejected_backlog WHERE id = ?",
        (pbi_id,),
    ).fetchone()
    if not row:
        print(f"PBI #{pbi_id} not found in rejected_backlog.csv", file=sys.stderr)
        sys.exit(1)

    status = "problem" if row["doc"] else "describe"

    pb_path = PRODUCT_DIR / "product_backlog.csv"
    with open(pb_path, "a", newline="") as f:
        csv.writer(f).writerow(
            [
                row["id"],
                row["title"],
                status,
                row["cause_id"] or "",
                row["feature_file"] or "",
                row["doc"] or "",
            ]
        )

    _remove_csv_row(PRODUCT_DIR / "rejected_backlog.csv", str(pbi_id))
    print(f'#{pbi_id} "{row["title"]}" → product_backlog [{status}]')


# -- Main --------------------------------------------------------------


def _view(name: str) -> None:
    """Show a SQL view."""
    db = _load_db()
    rows = db.execute(VIEWS[name]).fetchall()
    _print(rows)


def _build_parser() -> argparse.ArgumentParser:
    epilog = """\
views:
  sprint, dev, po, throughput, sm, log
  tree [-d depth] [-s status ...]
  rejected <pbi_id>                      show subtree with rejected alternatives

actions:
  select <id>                         move PBI to sprint backlog
  done <id>                           mark PBI as done
  reject <id>                         move PBI to rejected backlog
  restore <id>                        restore rejected PBI to backlog
  assess <id> effective|ineffective   mark outcome
  sprint start "<goal>"               start a new sprint
  sprint end                          end current sprint
  sprint check                        validate sprint readiness
  agent-prompt <pbi_id> <worktree>    generate developer agent prompt

checks:
  check-ids                           verify all PBI docs are tracked

reports:
  forecast                            capacity forecast
  retro                               sprint retrospective"""

    parser = argparse.ArgumentParser(
        prog="board.py",
        description="Scrum board CLI",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # Views (sprint is also a subcommand, so skip here)
    for name in VIEWS:
        if name == "sprint":
            continue
        sub.add_parser(name)

    # Rejected alternatives view
    p = sub.add_parser("rejected")
    p.add_argument("id", type=int, metavar="pbi_id")

    # Tree
    tree_p = sub.add_parser("tree")
    tree_p.add_argument(
        "-d", "--depth", type=int, default=None, help="max tree depth (0=roots only)"
    )
    tree_p.add_argument(
        "-s",
        "--status",
        default=None,
        choices=ALL_STATUSES,
        nargs="+",
        help="statuses to show",
    )

    # Actions
    p = sub.add_parser("select")
    p.add_argument("id", type=int)

    p = sub.add_parser("done")
    p.add_argument("id", type=int)

    p = sub.add_parser("assess")
    p.add_argument("id", type=int)
    p.add_argument("outcome", choices=["effective", "ineffective"])

    p = sub.add_parser("reject")
    p.add_argument("id", type=int)

    p = sub.add_parser("restore")
    p.add_argument("id", type=int)

    p = sub.add_parser("agent-prompt")
    p.add_argument("id", type=int, metavar="pbi_id")
    p.add_argument("worktree", metavar="worktree-name")

    # Sprint: view (no args) or subcommands (start/end/check)
    sprint_p = sub.add_parser("sprint")
    sprint_sub = sprint_p.add_subparsers(dest="sprint_command")
    sp = sprint_sub.add_parser("start", help="start a new sprint")
    sp.add_argument("goal", help="sprint goal")
    sprint_sub.add_parser("end", help="end current sprint")
    sprint_sub.add_parser("check", help="validate sprint readiness")

    # Checks
    sub.add_parser("check-ids")

    # Reports
    sub.add_parser("forecast")
    sub.add_parser("retro")

    return parser


_parser = _build_parser()


def main() -> None:
    args = _parser.parse_args()

    if not args.command:
        _parser.print_help()
        sys.exit(1)

    if args.command in VIEWS and args.command != "sprint":
        _view(args.command)
    elif args.command == "rejected":
        _rejected_view(args.id)
    elif args.command == "tree":
        _tree(depth=args.depth, statuses=args.status)
    elif args.command == "select":
        _select(args.id)
    elif args.command == "done":
        _done(args.id)
    elif args.command == "assess":
        _assess(args.id, args.outcome)
    elif args.command == "reject":
        _reject(args.id)
    elif args.command == "restore":
        _restore(args.id)
    elif args.command == "agent-prompt":
        _agent_prompt(args.id, args.worktree)
    elif args.command == "sprint":
        if not args.sprint_command:
            _view("sprint")
        elif args.sprint_command == "start":
            _sprint_start(args.goal)
        elif args.sprint_command == "end":
            _sprint_end()
        elif args.sprint_command == "check":
            _sprint_check()
    elif args.command == "check-ids":
        _check_ids()
    elif args.command == "forecast":
        _forecast()
    elif args.command == "retro":
        _retro()


if __name__ == "__main__":
    main()
