# claude-skills

Reusable Claude Code skills and hooks for Scrum-based product development.

## Installation

Add as a git submodule to `.claude/skills/` in any project:

```bash
git submodule add git@github.com:NikitaIT/claude-skills.git .claude/skills
```

Claude Code auto-discovers skills from `.claude/skills/<name>/SKILL.md`.

## Structure

```sh
.claude/skills/               # ← submodule root
├── role-developer/SKILL.md    # Developer role (Scrum + product/ framework)
├── role-product-owner/SKILL.md # PO role (BAT, refinement, sprint execution)
├── role-scrum-master/SKILL.md # SM role (process, DoD, delegation)
├── scrum-guide/SKILL.md       # Scrum Guide, November 2020
├── issue-template/SKILL.md    # Issue refinement workflow (Describe → Design)
├── hooks/                     # Reusable Claude Code hooks
│   ├── git-sync.sh            # SessionStart: auto-pull remote
│   ├── check-outside-project.sh # PreToolUse(Bash): block writes outside repo
│   ├── check-modified.sh      # PreToolUse(Edit|Write): deny if externally modified
│   └── update-hash-cache.sh   # PostToolUse(Edit|Write): track Claude's edits
└── scripts/                   # Product management scripts
    ├── board/                 # Scrum board CLI (board.py + schema.sql + tests)
    ├── worktree-pool.sh       # Manage 5 reusable worktrees for parallel agents
    └── lint-backlog-words.sh  # Lint backlog CSV for forbidden implementation words
```

## Project-Specific Extensions

Role skills inject project-specific content at load time via:

```sh
!`cat .claude/project-extensions/role-<name>.md 2>/dev/null`
```

Create `.claude/project-extensions/` in your project to override or extend any role:

```sh
your-project/
├── .claude/
│   ├── skills/                  # ← this submodule
│   ├── project-extensions/      # ← project-specific overrides
│   │   ├── role-developer.md    # e.g., snapshot DoD, test selectors
│   │   ├── role-product-owner.md # e.g., pre-push hook details
│   │   └── role-scrum-master.md # e.g., telemetry sources
│   └── commands/                # ← other project-specific commands
│       └── context/
│           └── coding.md        # project structure, deps, code style
└── product/                     # ← standard product management framework
    ├── board.py
    ├── product_backlog.csv
    ├── sprint_backlog.csv
    └── ...
```

If the file doesn't exist, the injection silently produces nothing.

## Hooks Setup

Reference hooks from `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/skills/hooks/git-sync.sh",
            "statusMessage": "Syncing with remote..."
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/skills/hooks/check-outside-project.sh",
            "statusMessage": "Checking for writes outside project..."
          }
        ]
      },
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/skills/hooks/check-modified.sh",
            "statusMessage": "Checking for external changes..."
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/skills/hooks/update-hash-cache.sh"
          }
        ]
      }
    ]
  }
}
```

## Quick Start

```bash
# 1. Add submodule
git submodule add git@github.com:NikitaIT/claude-skills.git .claude/skills

# 2. Create project extensions (optional)
mkdir -p .claude/project-extensions

# 3. Copy hooks config to settings.json (see above)

# 4. Initialize product/ framework
mkdir -p product/product_backlog
touch product/product_backlog.csv product/sprint_backlog.csv product/sprint.csv product/sprint_log.csv
```
