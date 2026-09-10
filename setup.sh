#!/bin/bash
# setup.sh - Interactive first-time setup for this home media server stack.
# Asks a few questions and generates a working .env file from .env.example.

set -e

ENV_FILE=".env"
ENV_EXAMPLE=".env.example"

if [ ! -f "$ENV_EXAMPLE" ]; then
    echo "Error: $ENV_EXAMPLE not found. Run this script from the repo root."
    exit 1
fi

if [ -f "$ENV_FILE" ]; then
    read -p ".env already exists. Overwrite it? [y/N] " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "Aborted -- your existing .env was left untouched."
        exit 0
    fi
fi

cp "$ENV_EXAMPLE" "$ENV_FILE"

echo ""
echo "=== Home Media Server Setup ==="
echo ""

# --- Operating system + PUID/PGID ---
echo "What operating system is this server running on?"
echo "  1) macOS"
echo "  2) Linux (Ubuntu, Debian, etc.)"
read -p "Enter 1 or 2: " os_choice

# id -u/-g work identically on both platforms and give the genuinely
# correct values for THIS specific user -- more reliable than guessing
# a generic "typical" default for the OS, which can be wrong if this
# isn't the first user account on the machine.
DETECTED_PUID=$(id -u)
DETECTED_PGID=$(id -g)

case "$os_choice" in
    1)
        echo "macOS selected."
        ;;
    2)
        echo "Linux selected."
        ;;
    *)
        echo "Unrecognized choice, proceeding with detected values anyway."
        ;;
esac

echo "Detected PUID=$DETECTED_PUID, PGID=$DETECTED_PGID for your user account."
read -p "Use these values? [Y/n] " use_detected
if [[ "$use_detected" =~ ^[Nn]$ ]]; then
    read -p "Enter PUID: " DETECTED_PUID
    read -p "Enter PGID: " DETECTED_PGID
fi

sed -i.bak "s/^PUID=.*/PUID=$DETECTED_PUID/" "$ENV_FILE"
sed -i.bak "s/^PGID=.*/PGID=$DETECTED_PGID/" "$ENV_FILE"
rm -f "$ENV_FILE.bak"

# --- Timezone ---
echo ""
read -p "Timezone (e.g. America/Phoenix, America/New_York): " tz_input
if [ -n "$tz_input" ]; then
    sed -i.bak "s|^TZ=.*|TZ=$tz_input|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
fi

# --- Paths ---
echo ""
echo "Now let's set up your media/download paths."
read -p "Path to your media library (movies/TV storage): " media_path
if [ -n "$media_path" ]; then
    sed -i.bak "s|^MEDIA_PATH=.*|MEDIA_PATH=$media_path|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
fi

read -p "Path to your downloads folder: " downloads_path
if [ -n "$downloads_path" ]; then
    sed -i.bak "s|^DOWNLOADS_PATH=.*|DOWNLOADS_PATH=$downloads_path|" "$ENV_FILE"
    rm -f "$ENV_FILE.bak"
fi

echo ""
echo "=== Done! ==="
echo ".env has been created with your values."
echo ""
echo "Remaining steps:"
echo "  1. Review .env and fill in any remaining values (Mealie tokens, etc.)"
echo "     -- some of these require the containers to be running first."
echo "  2. Run: docker compose up -d"
echo "  3. Configure indexers/download clients in Radarr, Sonarr, etc."
echo "     through each service's own web UI."
