#!/bin/bash
# PostToolUse hook for Edit|Write: update hash cache after Claude edits a file.
# Prevents check-modified.sh from false-positive blocking subsequent edits
# to the same file (Claude's own changes ≠ external changes).

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

CURRENT_HASH=$(md5 -q "$FILE_PATH" 2>/dev/null || md5sum "$FILE_PATH" 2>/dev/null | cut -d' ' -f1)
CACHE_FILE="$CACHE_DIR/$(echo "$FILE_PATH" | tr '/' '_')"
echo "$CURRENT_HASH" > "$CACHE_FILE"

exit 0
