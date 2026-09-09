#!/bin/bash
# sync_with_alass.sh - Called by Bazarr as a custom post-processing step
# after every subtitle download, to re-sync the subtitle using alass
# (generally more accurate than Bazarr's built-in ffsubsync).
#
# Bazarr invokes this as:
#   /usr/local/bin/sync_with_alass.sh "{{episode}}" "{{subtitles}}" 2>&1
#
# Args: $1 = full path to the video file, $2 = full path to the subtitle file

MAX_SHIFT_SECONDS=2

VIDEO="$1"
SUBTITLE="$2"
# alass infers subtitle format from the file extension, so the temp output
# must keep the same extension (e.g. .srt) -- putting a marker after the
# extension instead of before it causes alass to reject the file entirely.
SUBTITLE_EXT="${SUBTITLE##*.}"
SUBTITLE_BASE="${SUBTITLE%.*}"
TEMP_OUTPUT="${SUBTITLE_BASE}.alass-tmp.${SUBTITLE_EXT}"

if [ -z "$VIDEO" ] || [ -z "$SUBTITLE" ]; then
    echo "[alass] Missing video or subtitle path argument, skipping sync"
    exit 0
fi

if [ ! -f "$VIDEO" ]; then
    echo "[alass] Video file not found: $VIDEO -- skipping sync"
    exit 0
fi

if [ ! -f "$SUBTITLE" ]; then
    echo "[alass] Subtitle file not found: $SUBTITLE -- skipping sync"
    exit 0
fi

echo "[alass] Syncing '$SUBTITLE' against '$VIDEO'"

FILTERED_OUTPUT=$(/usr/local/bin/alass-cli "$VIDEO" "$SUBTITLE" "$TEMP_OUTPUT" 2>&1 | tr '\r' '\n' | grep -Ev '^[0-9]+ */ *[0-9]+ *\[' | tee /dev/stderr)
ALASS_EXIT=${PIPESTATUS[0]}

MAX_ABS_SHIFT=$(echo "$FILTERED_OUTPUT" | grep -oE "by -?[0-9]+:[0-9]+:[0-9]+\.[0-9]+" | sed 's/by //' | awk -F'[:.]' '
{
    h = $1; gsub(/-/, "", h)
    total = h*3600 + $2*60 + $3 + $4/1000
    if (total > max) max = total
}
END { print max+0 }
')

SHIFT_TOO_LARGE=0
if awk -v shift="$MAX_ABS_SHIFT" -v limit="$MAX_SHIFT_SECONDS" 'BEGIN{exit !(shift > limit)}'; then
    SHIFT_TOO_LARGE=1
fi

if [ "$SHIFT_TOO_LARGE" -eq 1 ]; then
    echo "[alass] Sync REJECTED: shift of ${MAX_ABS_SHIFT}s exceeds ${MAX_SHIFT_SECONDS}s safety threshold -- likely a bad audio match, leaving original subtitle unchanged"
    rm -f "$TEMP_OUTPUT"
elif [ $ALASS_EXIT -eq 0 ] && [ -s "$TEMP_OUTPUT" ]; then
    mv "$TEMP_OUTPUT" "$SUBTITLE"
    echo "[alass] Sync successful, subtitle updated in place"
else
    echo "[alass] Sync failed (exit code $ALASS_EXIT), leaving original subtitle unchanged"
    rm -f "$TEMP_OUTPUT"
fi

exit 0
