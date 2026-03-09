#!/usr/bin/env bash
# Block Bash commands that write files outside the project directory.
set -euo pipefail

input=$(cat)
command=$(echo "$input" | jq -r '.tool_input.command // empty')

# Check for output redirects (>, >>) to absolute paths outside project
# Exclude /dev/null which is a standard output sink
if echo "$command" | grep -vE '/dev/null' | grep -qE '>\s*/[^.]'; then
  project_dir=$(pwd)
  # Allow writes to project directory
  if ! echo "$command" | grep -qF "$project_dir"; then
    echo '{"decision":"block","reason":"Writing files outside the project directory is not allowed. Use a project-local path instead."}'
    exit 0
  fi
fi

echo '{"decision":"allow"}'
