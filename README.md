# Home Media Server

Docker Compose setup for a home media server: automated movie/TV
acquisition and organization (Radarr, Sonarr, Bazarr, Prowlarr-style
stack), transcoding (Tdarr), a dashboard (Homepage), plus several
custom-built apps.

## Custom apps in this repo

- **clan-vote** — member voting site with Discord webhook notifications
- **clan-about** — clan info/rules site
- **dinner-roller** — a spinning-wheel dinner picker with Mealie
  recipe/shopping-list integration (ingredient parsing, consolidation,
  and a public read/write shopping list view)
- **bazarr-alass** — custom Bazarr image with alass-based subtitle
  re-syncing, gated by a safety threshold that rejects implausibly
  large shift corrections

## Setup

1. Copy `.env.example` to `.env` and fill in your own values (paths,
   secrets, API tokens). Generate random secret keys with:
   python3 -c "import secrets; print(secrets.token_hex(32))"
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
