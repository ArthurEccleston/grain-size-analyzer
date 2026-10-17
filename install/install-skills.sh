#!/usr/bin/env sh
# Install Arthur's SEM / mechanical skills from GitHub.
#
# Usage:
#   sh install-skills.sh [SKILLS_DIR]
#   SKILLS_DIR=/path/to/skills sh install-skills.sh
#
# Default SKILLS_DIR: $HOME/.claude/skills
set -eu

SKILLS_DIR="${SKILLS_DIR:-${1:-$HOME/.claude/skills}}"
REPOS="instron-tensile-analysis-skill:instron-tensile-analysis grain-size-analyzer:grain-size"

mkdir -p "$SKILLS_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM

for item in $REPOS; do
    repo="${item%%:*}"
    name="${item##*:}"
    target="$SKILLS_DIR/$name"
    echo "Installing $name from github.com/ArthurEccleston/$repo"

    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 "https://github.com/ArthurEccleston/$repo.git" "$TMP/$repo"
    else
        command -v curl >/dev/null 2>&1 || { echo "error: need git or curl" >&2; exit 1; }
        curl -fsSL "https://github.com/ArthurEccleston/$repo/archive/refs/heads/main.tar.gz" \
            -o "$TMP/$repo.tar.gz"
        mkdir -p "$TMP/$repo"
        tar -xzf "$TMP/$repo.tar.gz" -C "$TMP/$repo" --strip-components=1
    fi

    rm -rf "$target"
    cp -a "$TMP/$repo" "$target"
    rm -rf "$target/.git"

    if [ ! -f "$target/SKILL.md" ]; then
        echo "error: $name has no SKILL.md after install" >&2
        exit 1
    fi
    echo "  -> $target"
done

echo
echo "Installed to: $SKILLS_DIR"
echo "Next steps:"
echo "  python -m pip install -r \"$SKILLS_DIR/grain-size/requirements.txt\""
echo "  python -m pip install openpyxl"

# Star both repositories when gh is available and authenticated.
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    for item in $REPOS; do
        repo="${item%%:*}"
        if gh api --method PUT "user/starred/ArthurEccleston/$repo" >/dev/null 2>&1; then
            echo "starred $repo"
        fi
    done
else
    echo "note: install gh and run 'gh auth login' to star both repositories automatically"
fi
