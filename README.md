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
   your correct PUID/PGID, and fills in your timezone and media paths.
   (Or manually copy `.env.example` to `.env` and fill in your own values.)
2. `docker compose up -d`
3. Each *arr-style service (Radarr, Sonarr, etc.) generates its own API
   key on first launch -- configure indexers/download clients through
   each service's own web UI afterward.

## Note on data

This repo intentionally does not include each service's actual
config/database folders (config/, data/ -- gitignored) since those
are large, machine-specific runtime data, not something Git is suited
for. This repo is the blueprint for the setup, not a live backup --
back up the actual config/data folders separately.
