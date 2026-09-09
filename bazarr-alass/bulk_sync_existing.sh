#!/bin/bash
# bulk_sync_existing.sh - One-time (or re-runnable) batch job to run alass
# sync against every already-downloaded subtitle in the library, not just
# new ones going forward (which sync_with_alass.sh already handles via
# Bazarr's post-processing hook).
#
# Usage (run inside the bazarr container):
#   /usr/local/bin/bulk_sync_existing.sh /media
#
# Manages its own logging to /config/bulk_sync.log (both live output and
# a persistent file), and posts a Discord summary on completion.
#
# Safe to interrupt and re-run -- alass is idempotent on already-aligned
# subtitles (it'll just find a near-zero shift and re-save essentially
# the same file).

LIBRARY_ROOT="${1:-/media}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
LOG_FILE="/config/bulk_sync.log"
COMPLETED_FILE="/config/bulk_sync_completed.txt"

# Ensure the completed-tracking file exists even on a first-ever run.
touch "$COMPLETED_FILE"

# Redirect all of this script's output to both the terminal (if any) and
# a fixed, known log file -- so it can reliably read its own log back at
# the end for the summary, regardless of how/where it's invoked from.
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[bulk-sync] Starting bulk alass sync under: $LIBRARY_ROOT"
echo "[bulk-sync] Started at: $(date)"
echo "[bulk-sync] This can take a long time on a large library -- safe to interrupt (Ctrl+C) and re-run later."

# Find every video+subtitle pair up front into a temp file, so we know the
# total count for progress reporting, and so the main loop isn't itself
# part of a pipeline (avoiding a subshell variable-scoping pitfall).
PAIRS_FILE=$(mktemp)

find "$LIBRARY_ROOT" -type f \( -iname "*.mp4" -o -iname "*.mkv" \) | while IFS= read -r VIDEO; do
    VIDEO_DIR=$(dirname "$VIDEO")
    VIDEO_BASE_NOEXT=$(basename "$VIDEO")
    VIDEO_BASE_NOEXT="${VIDEO_BASE_NOEXT%.*}"

    find "$VIDEO_DIR" -maxdepth 1 -type f -iname "${VIDEO_BASE_NOEXT}*.srt" | while IFS= read -r SUBTITLE; do
        echo "${VIDEO}|${SUBTITLE}"
    done
done > "$PAIRS_FILE"

TOTAL=$(wc -l < "$PAIRS_FILE")
echo "[bulk-sync] Found $TOTAL video+subtitle pairs to process"

CURRENT=0
SKIPPED=0
while IFS='|' read -r VIDEO SUBTITLE; do
    CURRENT=$((CURRENT + 1))

    if grep -Fxq "$SUBTITLE" "$COMPLETED_FILE"; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    echo "[bulk-sync] ($CURRENT / $TOTAL) Processing: $SUBTITLE"
    /usr/local/bin/sync_with_alass.sh "$VIDEO" "$SUBTITLE"

    # Record success so a future interrupted-and-restarted run can skip
    # this file instead of redoing already-completed work. Check the log
    # text directly rather than the exit code, since sync_with_alass.sh
    # always exits 0 by design (so a failed sync never breaks Bazarr's
    # own post-processing flow).
    if tail -1 "$LOG_FILE" | grep -q "Sync successful"; then
        echo "$SUBTITLE" >> "$COMPLETED_FILE"
    fi
done < "$PAIRS_FILE"

echo "[bulk-sync] Skipped $SKIPPED already-completed file(s) from a previous run."

rm -f "$PAIRS_FILE"

echo "[bulk-sync] Finished at: $(date)"
echo "[bulk-sync] Processed $TOTAL pairs."

SUCCESS_COUNT=$(grep -c "Sync successful" "$LOG_FILE")
FAILED_COUNT=$(grep -c "Sync failed" "$LOG_FILE")

echo "[bulk-sync] Success: $SUCCESS_COUNT, Failed: $FAILED_COUNT"

curl -s -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -H "User-Agent: Mozilla/5.0 (compatible; BazarrAlassBot/1.0)" \
    -d "{\"embeds\":[{\"title\":\"Bulk Subtitle Sync Complete\",\"description\":\"Processed **${TOTAL}** video+subtitle pairs under \`${LIBRARY_ROOT}\`.\\n\\n✅ Success: ${SUCCESS_COUNT}\\n⚠️ Failed: ${FAILED_COUNT}\",\"color\":9426266}]}" \
    > /dev/null

echo "[bulk-sync] Discord notification sent."
