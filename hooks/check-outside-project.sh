#!/usr/bin/env bash
# Block Bash commands that write files outside the project directory.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | grep -o '"command":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Check for output redirects (>, >>) to absolute paths outside project
# Exclude /dev/null which is a standard output sink
if echo "$COMMAND" | grep -vE '/dev/null' | grep -qE '>\s*/[^.]'; then
  PROJECT_DIR=$(pwd)
  # Allow writes to project directory
  if ! echo "$COMMAND" | grep -qF "$PROJECT_DIR"; then
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Writing files outside the project directory is not allowed. Use a project-local path instead."
  }
}
EOF
    exit 0
  fi
fi
