#!/usr/bin/env bash
# Symlink every skill in this repo into a Claude Code skills dir for dev/testing.
#   scripts/link-skills.sh            -> ~/.claude/skills (all projects)
#   scripts/link-skills.sh <project>  -> <project>/.claude/skills
#   scripts/link-skills.sh --unlink [<project>]
# Don't combine with a plugin install of this repo, or every skill shows up twice.
set -euo pipefail

unlink=0
[[ "${1:-}" == "--unlink" ]] && { unlink=1; shift; }
target="${1:+$1/.claude/skills}"
target="${target:-$HOME/.claude/skills}"
src="$(cd "$(dirname "$0")/.." && pwd)/skills"

mkdir -p "$target"
for d in "$src"/*/; do
  name=$(basename "$d")
  link="$target/$name"
  if (( unlink )); then
    [[ -L "$link" ]] && rm "$link" && echo "unlinked $link"
  else
    if [[ -e "$link" && ! -L "$link" ]]; then
      echo "skip $link: exists and is not a symlink" >&2
      continue
    fi
    ln -sfn "$d" "$link" && echo "$link -> $d"
  fi
done
