#!/bin/bash
# PreToolUse hook for Edit|Write: deny if file has external changes.
#
# Two checks:
# 1. Remote: unpulled commits that touch this file → deny (until git pull)
# 2. Local: uncommitted changes → deny once, allow after re-read (hash cache)

CACHE_DIR=".claude/.edit_hashes"
mkdir -p "$CACHE_DIR"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('file_path', ''))
" 2>/dev/null)

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# 1. Remote changes: auto-pull if upstream has new commits
UPSTREAM=$(git rev-parse --abbrev-ref @{upstream} 2>/dev/null)
if [ -n "$UPSTREAM" ]; then
  REMOTE_CHANGES=$(git log --oneline HEAD.."$UPSTREAM" 2>/dev/null)
  if [ -n "$REMOTE_CHANGES" ]; then
    if ! git pull --ff-only --quiet 2>/dev/null; then
      cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "File $FILE_PATH has unpulled remote changes and auto-pull failed (branches diverged?). Resolve manually."
  }
}
EOF
      exit 0
    fi
  fi
fi

# 2. Local changes: uncommitted modifications
if git diff --quiet HEAD -- "$FILE_PATH" 2>/dev/null; then
  CACHE_FILE="$CACHE_DIR/$(echo "$FILE_PATH" | tr '/' '_')"
  rm -f "$CACHE_FILE"
  exit 0
fi

# File has local changes — check if Claude already seen this version
CURRENT_HASH=$(md5 -q "$FILE_PATH" 2>/dev/null || md5sum "$FILE_PATH" 2>/dev/null | cut -d' ' -f1)
CACHE_FILE="$CACHE_DIR/$(echo "$FILE_PATH" | tr '/' '_')"

if [ -f "$CACHE_FILE" ] && [ "$(cat "$CACHE_FILE")" = "$CURRENT_HASH" ]; then
  exit 0  # Same version Claude already saw — allow
fi

# New external changes — cache hash and deny
echo "$CURRENT_HASH" > "$CACHE_FILE"

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "File $FILE_PATH was modified externally. Re-read it before editing."
  }
}
EOF
