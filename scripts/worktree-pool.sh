#!/usr/bin/env bash
# Manage a pool of 5 reusable git worktrees for developer agents.
#
# Usage:
#   scripts/worktree-pool.sh init          Create 5 worktrees if they don't exist
#   scripts/worktree-pool.sh reset [N]     Reset worktree N (or all) to origin/main

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
POOL_DIR="$REPO_ROOT/.claude/worktrees"
POOL_SIZE=5

ensure_one() {
  local i="$1"
  local wt="$POOL_DIR/dev-$i"
  local branch="worktree-dev-$i"

  if [ -d "$wt" ]; then
    return
  fi

  mkdir -p "$POOL_DIR"
  git branch -f "$branch" origin/main 2>/dev/null || true
  git worktree add "$wt" "$branch" 2>/dev/null || {
    git worktree remove "$wt" --force 2>/dev/null || true
    git branch -D "$branch" 2>/dev/null || true
    git branch "$branch" origin/main
    git worktree add "$wt" "$branch"
  }
  echo "dev-$i: created"

  local start_time=$SECONDS
  (cd "$wt" && pnpm install --frozen-lockfile) || echo "dev-$i: install failed" >&2
  echo "dev-$i: deps installed in $((SECONDS - start_time))s"
}

init() {
  git fetch origin
  for i in $(seq 1 $POOL_SIZE); do
    ensure_one "$i"
  done
}

reset_one() {
  local i="$1"
  local wt="$POOL_DIR/dev-$i"
  local branch="worktree-dev-$i"

  ensure_one "$i"

  cd "$wt"
  git fetch origin
  git checkout "$branch" 2>/dev/null || git checkout -b "$branch"
  git reset --hard origin/main
  git clean -fd
  cd "$REPO_ROOT"

  local start_time=$SECONDS
  (cd "$wt" && pnpm install --frozen-lockfile) || echo "dev-$i: install failed" >&2
  echo "dev-$i: deps installed in $((SECONDS - start_time))s"

  echo "dev-$i: reset to origin/main"
}

reset_all() {
  git fetch origin
  for i in $(seq 1 $POOL_SIZE); do
    reset_one "$i"
  done
}

case "${1:-}" in
  init)    init ;;
  reset)   if [ -n "${2:-}" ]; then reset_one "$2"; else reset_all; fi ;;
  *)       echo "Usage: $0 {init|reset [N]}" >&2; exit 1 ;;
esac
