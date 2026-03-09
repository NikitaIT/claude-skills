#!/bin/bash
# Lint backlog CSV files for forbidden implementation-language words.
# Stakeholder backlog items should describe WHAT the user wants, not HOW.
# Usage: lint-backlog-words.sh [file...]
#   No args — validates all product/*.csv files.
# Exit code: 1 if forbidden words found, 0 otherwise.

FORBIDDEN="show|apply|persist|install|dropdown|fixes|redesign"
found=0

if [ $# -eq 0 ]; then
  set -- product/*.csv
fi

for file in "$@"; do
  case "$file" in
    product/*.csv) ;;
    *) continue ;;
  esac

  [ -f "$file" ] || continue

  while IFS= read -r line; do
    # Skip header
    case "$line" in id,*) continue ;; esac

    # Skip [process] lines
    echo "$line" | grep -q '\[process\]' && continue

    match=$(echo "$line" | grep -iowE "$FORBIDDEN" | head -1)
    if [ -n "$match" ]; then
      echo "ERROR: $file: forbidden word \"$match\""
      echo "  $line"
      found=1
    fi
  done < "$file"
done

if [ "$found" -eq 1 ]; then
  echo ""
  echo "PO: rephrase these lines from the stakeholder perspective."
  echo "Use 'I wish...' / 'I must...' describing WHAT the user wants, not HOW."
  echo "Forbidden: show, apply, persist, install, dropdown, fixes, redesign"
  exit 1
fi

exit 0
