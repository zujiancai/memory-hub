# Memory Hub

Memory Hub is a self-hosted, personal photo, video, and diary vault: an iCloud
/ Google Photos-style upload and browse experience for people who want to keep
their memories on their own Azure subscription. Phase 1 delivers the capture-
and-view MVP: a Flask API, a React SPA that lives on the same origin, an
Android auto-uploader, and Bicep templates to run it all on Azure.

Scope for Phase 1 = **library only**. Diaries, albums, tags, semantic search,
duplicate detection, chat, MCP tools, and the mobile pre-upload image pipeline
are all deferred to later phases per `buildout-plan.md`.

## Repo layout

```
memory-hub/
├── server/                     # Flask API + React SPA (hosted from /server/ui/dist)
│   ├── server/                 # Python package
│   ├── server/ui/              # React 18 + Vite + Tailwind SPA
│   └── migrations/             # Alembic
├── test/                       # pytest suite (targets `server/`)
├── android-client/             # Kotlin / Compose / WorkManager uploader
├── deployment/                 # Bicep templates + parameters
├── buildout-design.md          # Full technical spec (read-only reference)
├── buildout-plan.md            # Phase tracker + decision log
└── README.md
```

## Prereqs

- **Python 3.11+** (dev tested on 3.13 — see *Design notes*)
- **Node 20** and npm
- **Android Studio Iguana** (2023.2) + Android SDK 34 + JDK 17
- **Azure CLI** ≥ 2.60 for deployment
- (Optional) **Docker** if you want to run Azurite for local blob storage

## Local dev quickstart

### 1. Backend

```powershell
cd server
pipenv install --dev
pipenv shell
Copy-Item .env.example .env
# Edit .env: set FLASK_SECRET, JWT_SIGNING_KEY, DATABASE_URL if not sqlite

# Create the schema
flask --app server.app db upgrade

# Seed a dev user for the SPA to log into
flask --app server.app seed-dev-user

# Run the API on http://localhost:5000
flask --app server.app run
```

### 2. SPA

```powershell
cd server\ui
npm ci
Copy-Item .env.example .env
npm run dev   # http://localhost:5173, proxies /api to :5000
```

For a production-style hosted-by-Flask build:

```powershell
cd server\ui
npm run build     # writes server/ui/dist/
# Flask's catch-all route serves dist/index.html for anything that isn't /api/*
```

### 3. Ingestion worker

```powershell
cd server
pipenv run python -m server.worker
```

Single-worker is fine for Phase 1. To scale, run multiple processes — the DB
row lock (`state='hashing'`) ensures a job is only claimed once.

### 4. Nightly cleanup

```powershell
cd server
pipenv run flask --app server.app cleanup
```

Purges soft-deleted assets past the grace period (default 30 days, override with
`TRASH_GRACE_DAYS`), drops orphan blobs (`ref_count == 0`), and recomputes
`user.storage_used_bytes` as a safety net.

### 5. Android

Open `android-client/` in Android Studio, sync Gradle, run on an API 26+ device
or emulator. See `android-client/README.md` for the full detail.

## Tests

```powershell
cd server
pipenv run pytest
```

Latest run: **28 passed**, **86 %** line coverage on `server/`.

## Deployment (Azure)

See `deployment/README.md`. Summary:

```powershell
az group create --name memory-hub-dev --location eastus
az deployment group create `
  --resource-group memory-hub-dev `
  --template-file deployment\main.bicep `
  --parameters @deployment\parameters.dev.json `
  --parameters deployerObjectId=$(az ad signed-in-user show --query id -o tsv) `
  --parameters postgresAdminPassword=$env:MH_PG_PASSWORD `
  --parameters jwtSigningKey=$env:MH_JWT_KEY `
  --parameters googleOAuthClientId=$env:MH_GOOGLE_CLIENT_ID `
  --parameters googleOAuthClientSecret=$env:MH_GOOGLE_CLIENT_SECRET
```

## Design notes

Where the spec left room for judgment, these are the concrete choices this
phase made:

- **Refresh-token cookie *vs* body precedence.** The spec allows both the
  cookie-mode (SPA) and body-mode (Android) refresh flows. When a request
  presents *both*, the request body wins. Rationale: the mobile client always
  sends an explicit refresh token; the SPA never does. So a body value is a
  strong signal of "this is a mobile-flavour call, use it verbatim." This also
  keeps the pytest client from getting stuck on a stale cookie after logout.

- **Python 3.13 used to run tests locally.** The Pipfile declares 3.11 (as the
  spec asks) — that's what the App Service Plan targets. The local sandbox only
  had 3.9/3.13/3.14 available, so the pytest suite was verified on 3.13. PyAV
  18.1 ships a `cp311-abi3` wheel that also loads under 3.13, so this didn't
  require any code changes.

- **Best-effort user-bytes accounting for shared blobs.** Because the same
  blob (identified by its SHA-256) can be referenced by multiple assets owned
  by the same user (dedup), permanently deleting an asset only decrements
  `user.storage_used_bytes` when the physical blob is deleted. The nightly
  `flask cleanup` command recomputes `storage_used_bytes` from scratch as a
  safety net, matching what the spec calls out.

- **Soft delete does not free quota.** `DELETE /api/asset/<id>` sets
  `deleted_at` but leaves `storage_used_bytes` untouched — behaviour matching
  iCloud and Google Photos. The `GET /api/storage/quota` endpoint returns the
  soft-deleted bytes as a separate `deleted_pending_purge_bytes` counter so the
  UI can show them.

- **Ingestion is inline for physical blob deletes.** Permanent delete of a
  ref-count-zero blob happens synchronously inside the request. The code path
  is behind `blob_storage.delete(...)` so a future async sweeper can replace
  it without touching the API layer.

- **npm registry override.** `server/ui/.npmrc` points at
  `https://packagefeedproxy.microsoft.io/npm/` because the public npm registry
  is TLS-blocked from the dev sandbox this was built in. Delete the file for a
  normal developer setup.

- **Schema-forward NULL columns.** `asset.perceptual_hash`,
  `asset.upload_quality`, and `asset.superseded_by` are added by the initial
  migration but never populated by Phase 1 code. Each column carries a
  `# Phase-forward: populated in Phase N` comment in `server/server/models.py`.

- **No `mcp-server/` folder.** MCP is Phase 6.

## Next phase

See `buildout-plan.md` — Phase 2 ("Diaries + tags + duplicates") is next.
