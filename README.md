# Home Media Server

Docker Compose setup for a home media server: automated movie/TV
acquisition and organization (Radarr, Sonarr, Bazarr, Prowlarr-style
stack), transcoding (Tdarr), a dashboard (Homepage), plus several
custom-built apps.

## Custom apps in this repo

- **dinner-roller** — a spinning-wheel dinner picker with Mealie
  recipe/shopping-list integration (ingredient parsing, consolidation,
  and a public read/write shopping list view)
- **bazarr-alass** — custom Bazarr image with alass-based subtitle
  re-syncing, gated by a safety threshold that rejects implausibly
  large shift corrections

## Setup

1. Run `./setup.sh` -- an interactive script that asks your OS, detects
   your correct PUID/PGID, fills in your timezone and media paths, and
   offers to start the whole stack for you (`docker compose up -d`)
   right at the end. (Or manually copy `.env.example` to `.env`, fill
   in your own values, and run `docker compose up -d` yourself.)
2. Each *arr-style service (Radarr, Sonarr, etc.) generates its own API
   key on first launch -- configure indexers/download clients through
   each service's own web UI afterward.
3. Mealie-related values in `.env` (API token, shopping list ID) can
   only be filled in *after* Mealie is running, since they come from
   Mealie's own UI/API once it's up.

## Note on data

This repo intentionally does not include each service's actual
config/database folders (config/, data/ -- gitignored) since those
are large, machine-specific runtime data, not something Git is suited
for. This repo is the blueprint for the setup, not a live backup --
back up the actual config/data folders separately.

## Download → Tdarr → import pipeline

New downloads are transcoded by Tdarr *before* Sonarr/Radarr import them:
NZBGet downloads, `nzbget-scripts/TdarrTranscode.py` sends the release to Tdarr and
waits, then Sonarr/Radarr rename and move the result as usual. The script is
fail-safe: if Tdarr is down or errors, the original file imports untouched.

The script is mounted into NZBGet automatically. Two one-time steps in the UIs:

1. **Tdarr:** create a library named exactly `Downloads` with source `/downloads`,
   folder watching, scheduled scans and scan-on-start all **off**, and add your
   transcode plugin stack to it.
2. **NZBGet:** Settings → Extension Scripts → enable `TdarrTranscode`
   (defaults: `http://tdarr:8265`, library `Downloads`, categories `Movies,TV Shows`).

Check the link with: `docker exec nzbget /config/scripts/TdarrTranscode.py --check`

Optional: pin the Tdarr image by digest instead of `:latest` so auto-updates
(e.g. Watchtower) can't change the API underneath the script.
