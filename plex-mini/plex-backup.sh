#!/bin/bash
set -u
WEBHOOK_FILE="$HOME/.plex-backup-webhook"
SRC="$HOME/Library/Application Support/Plex Media Server"
PLIST="$HOME/Library/Preferences/com.plexapp.plexmediaserver.plist"
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
DEST="$ICLOUD/Plex-Backups"
STAGE="$HOME/plex-backup-stage"
LOG="$HOME/plex-backup.log"
KEEP=4
STAMP=$(date +%Y-%m-%d)
OUT="$DEST/plex-backup-$STAMP.tar.gz"
NOTE=""

notify() {
  if [ -s "$WEBHOOK_FILE" ]; then
    curl -s -m 20 -H 'Content-Type: application/json' -d "{\"content\":\"$1\"}" "$(cat "$WEBHOOK_FILE")" >/dev/null
  fi
}
start_plex() { pgrep -x "Plex Media Server" >/dev/null || open -a "Plex Media Server"; }
fail() {
  echo "$(date) FAIL: $1" >> "$LOG"
  start_plex
  notify "Plex backup FAILED: $1"
  exit 1
}
running() { pgrep -x "Plex Media Server" >/dev/null; }
wait_stop() {
  for i in $(seq 1 "$1"); do
    running || return 0
    sleep 2
  done
  running && return 1 || return 0
}
stop_plex() {
  osascript -e 'tell application "Plex Media Server" to quit' >/dev/null 2>&1
  wait_stop 20 && return 0
  pkill -TERM -x "Plex Media Server"
  wait_stop 10 && { NOTE=" (needed SIGTERM)"; return 0; }
  pkill -KILL -x "Plex Media Server"
  wait_stop 5 && { NOTE=" (force-stopped)"; return 0; }
  return 1
}

echo "$(date) start" >> "$LOG"
[ -d "$ICLOUD" ] || fail "iCloud Drive not available on the Plex mini"
mkdir -p "$DEST" || fail "could not create backup folder"
[ -d "$SRC" ] || fail "Plex data folder not found"

rm -rf "$STAGE"; mkdir -p "$STAGE" || fail "could not create staging folder"

stop_plex || fail "Plex would not stop"
sleep 3

rsync -a --exclude 'Updates' --exclude 'Cache' --exclude 'Crash Reports' "$SRC/" "$STAGE/pms/" || fail "copy of Plex data failed"
cp "$PLIST" "$STAGE/" || fail "copy of Plex settings file failed"
start_plex

tar -czf "$OUT" -C "$STAGE" . || fail "could not write the archive"
tar -tzf "$OUT" >/dev/null 2>&1 || fail "archive failed verification"
SIZE=$(du -h "$OUT" | cut -f1)
rm -rf "$STAGE"

ls -1t "$DEST"/plex-backup-*.tar.gz 2>/dev/null | tail -n +$((KEEP+1)) | while read -r old; do rm -f "$old"; done

echo "$(date) OK $OUT $SIZE$NOTE" >> "$LOG"
notify "Plex backup OK: plex-backup-$STAMP.tar.gz ($SIZE)$NOTE"
