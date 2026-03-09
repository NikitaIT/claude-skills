#!/bin/bash
# SessionStart hook: pull remote changes, report divergence.
#
# git pull --ff-only does fetch + merge in one step.
# If ff not possible (diverged), fetch still happens — we just report the issue.

if git pull --ff-only --quiet 2>/dev/null; then
  exit 0
fi

# ff-only failed — check why
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse @{upstream} 2>/dev/null)
BASE=$(git merge-base "$LOCAL" "$REMOTE" 2>/dev/null)

if [ "$LOCAL" != "$REMOTE" ] && [ -n "$BASE" ]; then
  LOCAL_AHEAD=$(git rev-list --count "$REMOTE".."$LOCAL" 2>/dev/null)
  REMOTE_AHEAD=$(git rev-list --count "$LOCAL".."$REMOTE" 2>/dev/null)
  echo "WARNING: branches diverged (local +${LOCAL_AHEAD}, remote +${REMOTE_AHEAD}). Run: git pull --rebase origin main && git push"
fi

exit 0
