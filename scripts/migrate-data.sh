#!/bin/bash
# scripts/migrate-data.sh — explicit, safe migration of legacy zephyr data.
#
# The recovery runtime never touches /mnt/workspace/zephyr (the original
# deployment's tree). This script is the ONLY sanctioned bridge: it copies the
# pieces a user may want into DATA_ROOT/import/zephyr-legacy/ without ever
# overwriting or deleting anything.
#
#   migrate-data.sh --dry-run   list what would be copied (default)
#   migrate-data.sh --apply     copy, then verify with a sha256 manifest
#
# Idempotent: --apply copies with --ignore-existing semantics, records a state
# marker, and re-runs only copy what is still missing. Any failure stops the
# run with a non-zero exit and leaves existing data untouched.
set -euo pipefail

LEGACY="/mnt/workspace/zephyr"
DATA_ROOT="${DATA_ROOT:-/mnt/workspace/zephyr-v2}"
IMPORT_DIR="$DATA_ROOT/import/zephyr-legacy"
STATE="$DATA_ROOT/import/migration-state.json"

# Legacy paths worth keeping, in copy order. Globs are fine; missing sources
# are reported, not fatal (old deployments differ).
SOURCES=(
    "hermes"             # legacy HERMES_HOME (sessions, memories, config)
    "config"             # legacy generated credentials/seed configs
    "work"               # legacy user files, if any
)

mode="--dry-run"
[ "${1:-}" = "--apply" ] && mode="--apply"
if [ "${1:-}" = "--dry-run" ] || [ -z "${1:-}" ]; then mode="--dry-run"; fi

if [ "$(id -u)" != 0 ]; then
    echo 'Run as root from the platform administrative terminal.' >&2
    exit 2
fi
if [ ! -d "$LEGACY" ]; then
    echo "No legacy tree at $LEGACY — nothing to migrate."
    exit 0
fi
if [ -e /mnt/workspace/zephyr-v2 ] && [ ! -d "$DATA_ROOT" ]; then
    echo "DATA_ROOT $DATA_ROOT is not a directory; refusing to continue." >&2
    exit 2
fi

echo "mode:   $mode"
echo "source: $LEGACY"
echo "target: $IMPORT_DIR"
echo

plan=()
for item in "${SOURCES[@]}"; do
    src="$LEGACY/$item"
    if [ ! -e "$src" ]; then
        echo "skip (absent): $item"
        continue
    fi
    dest="$IMPORT_DIR/$item"
    if [ -e "$dest" ]; then
        # Never overwrite: existing target content is the user's responsibility.
        pending=$(rsync -rn --out-format='%n' "$src/" "$dest/" 2>/dev/null | head -n 50 || true)
        if [ -z "$pending" ]; then
            echo "done already:  $item (target present, nothing new)"
        else
            count=$(rsync -rn --out-format='%n' "$src/" "$dest/" 2>/dev/null | wc -l || echo '?')
            echo "partial:       $item ($count file(s) would be added; existing files kept)"
            plan+=("$item")
        fi
    else
        size=$(du -sh "$src" 2>/dev/null | cut -f1 || echo '?')
        echo "would copy:    $item ($size)"
        plan+=("$item")
    fi
done

if [ "$mode" = "--dry-run" ]; then
    echo
    echo "dry run only — re-run with --apply to copy. Nothing was modified."
    exit 0
fi

echo
echo "applying..."
mkdir -p "$IMPORT_DIR"
manifest="$IMPORT_DIR/manifest.sha256"
: > "$manifest.partial"
failed=0
for item in "${plan[@]}"; do
    echo "copying $item..."
    rsync -a --ignore-existing "$LEGACY/$item/" "$IMPORT_DIR/$item/" || { failed=1; break; }
done
if [ "$failed" != 0 ]; then
    echo 'rsync failed — stopping before manifest verification.' >&2
    echo 'Existing data is untouched; re-run --apply to resume.' >&2
    exit 1
fi

# Integrity: hash everything imported, then verify the manifest reads back.
( cd "$IMPORT_DIR" && find . -type f ! -name 'manifest.sha256*' -print0 ) | \
    LC_ALL=C sort -z | xargs -0 sha256sum > "$manifest.partial"
mv "$manifest.partial" "$manifest"
if ( cd "$IMPORT_DIR" && sha256sum -c manifest.sha256 --quiet ); then
    files=$(wc -l < "$manifest")
    printf '{"status": "complete", "files": %s, "finished": "%s"}\n' \
        "$files" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATE"
    chmod 600 "$STATE"
    echo "migration complete: $files files verified in $IMPORT_DIR"
    echo "Merge into the live tree manually if wanted:"
    echo "  rsync -a --ignore-existing $IMPORT_DIR/hermes/ $DATA_ROOT/hermes/"
else
    echo 'manifest verification FAILED — inspect before using imported data.' >&2
    exit 1
fi
