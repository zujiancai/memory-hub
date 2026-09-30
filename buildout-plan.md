# Memory Hub — Phased Delivery Plan

Companion to [`buildout-design.md`](./buildout-design.md). The design doc is the full technical spec; this plan carves it into six shippable phases plus a v1.1 deferral bucket, each with a stand-alone user-run acceptance script.

---

## Status tracker

Update the **Status** and **Notes** columns as work progresses. Statuses: `not started` → `in progress` → `in testing` → `completed` → `blocked`.

| Phase | Title | Status | Started | Completed | Notes |
|---|---|---|---|---|---|
| 1 | Foundation: Capture & View | in testing | 2026-09-29 | 2026-09-29 | Backend + SPA + Android skeleton + Bicep + pytest all landed. 28/28 tests passing at 86 % coverage; SPA build 767 kB JS / 12 kB CSS. Awaiting user acceptance run. |
| 2 | Curation: Albums, Diaries, Duplicates, Sharing | not started | — | — | — |
| 3 | Intelligence: CLIP Semantic Layer | not started | — | — | — |
| 4 | Grouping: Tags & Memories | not started | — | — | — |
| 5 | Assistive UX: Chat + Advanced Android | not started | — | — | — |
| 6 | Integration: MCP + Admin | not started | — | — | — |
| 7 | Later (v1.1+) | not scoped | — | — | Face clustering, video summarisation, aesthetics scoring, Live Photo, Google Photos / iCloud connectors. |

### Current phase — decision log
_Append a dated bullet whenever the current phase's scope, acceptance script, or status changes. Keep entries short; the design doc holds the "why"._

- **2026-09-29** — Phase 1 implementation started. Sub-agent delegated the full build against `buildout-design.md`. Scope locked to the Phase 1 backend / minimal web UI / Android skeleton / tests / deployment; every Phase 2+ feature explicitly out of scope. Schema-forward NULL columns (`asset.perceptual_hash`, `asset.upload_quality`, `asset.superseded_by`) included in the initial migration to avoid painful ALTERs later.
- **2026-09-29** — Phase 1 code-complete → `in testing`. Shipped: Flask API with `user`, `asset`, `storage`, `trash`, `admin`, and root ping blueprints (JWT + refresh cookie *and* body, argon2-hashed refresh rows, Google OAuth PKCE, avatar upload, PIN-gated trash); ingestion worker (EXIF + 512-px poster for photos, mid-frame poster for videos via PyAV); nightly `flask cleanup` CLI (grace-period sweep + `blob.ref_count` reap + `storage_used_bytes` recompute); Alembic initial migration with all Phase 1 tables plus the three schema-forward NULL columns; React 18 + Vite + Tailwind + `@tanstack/react-virtual` SPA with masonry Library, upload drawer that hashes locally via Web Crypto, DiceBear avatar picker, and PIN-gated Deleted view; Kotlin/Compose Android skeleton with Room `upload_state`, Retrofit + auth-refreshing interceptor, `EncryptedSharedPreferences` token store, WorkManager `UploadWorker` with UNMETERED/charging constraints and exponential backoff, DAO smoke test, and WorkManager unit test; Bicep templates (`main.bicep` + dev/prod parameters + deploy README) provisioning App Service + Postgres Flexible Server + Storage + Key Vault + App Insights with MSI-based Storage Blob Data Contributor and Key Vault Secrets User RBAC. `pipenv run pytest` = 28 passed, 86 % coverage on `server/`; `npm run build` = 767 kB JS (249 kB gzip) / 12 kB CSS. Android Gradle sync verified by shape only (SDK not present in sandbox). Divergences documented in `README.md`'s *Design notes*: refresh-token body-vs-cookie precedence choice, Python 3.13 used for local test verification while the Pipfile still targets 3.11, and the `server/ui/.npmrc` sandbox registry override.

### Sign-off log
_One row per phase gate the user closes. Attach the acceptance-script results and the deploy build ID._

| Phase | Signed off on | Deploy build | Acceptance-script artifact | Sign-off by |
|---|---|---|---|---|
| — | — | — | — | — |

---

## Phase 1 — Foundation: Capture & View (the MVP)

**Goal.** A signed-in user uploads photos/videos from browser and Android, sees them in a chronological Library grid, and can delete them safely. Nothing else.

**Backend.** `user`, `refresh_token`, JWT auth, Google OAuth. `blob` (sha256/ref_count/SAS). Asset ingest: `precheck` (**sha256 only**) → `upload-url` → `POST /api/asset`. Basic EXIF + thumbnail/poster (videos via `av`, mid-frame). Trash flow (soft-delete, PIN, nightly `ref_count` sweep). Quota + `413`. Blueprints: `user`, `asset`, `storage`, `trash`, minimal `admin`.

**Web UI.** 3-pane shell scaffold. Left rail: **Library, Recently Saved, Deleted, storage bar, user pill**. Masonry-virtualised Library (`capture_ts DESC`). Login / signup / Google callback / User-info modal (password, friendly name, DiceBear avatar). **No right rail yet.**

**Android.** Watch folders, single default policy — one global "delete local after upload" toggle, Wi-Fi / charging switches. Room `upload_state`. SAF picker, incremental scan.

**Deferred:** albums, diaries, tags, share, pin, pHash, duplicates, CLIP, search, chat, MCP, upload profiles, space-saver, supersede, Keep import.

**Acceptance.** Two users each upload 500 photos + 20 videos from browser + Android; Library shows them in `capture_ts DESC`; delete → Trash → restore → permanent delete → quota bar drops. Cross-user isolation. `pytest-cov` ≥ 80 %, Android instrumented tests cover retry paths.

---

## Phase 2 — Curation: Albums, Diaries, Duplicates, Sharing

**Goal.** User curates collections, keeps journals, shares to others, and cleans near-duplicates.

**Backend.** `album` + `album_asset(sort_key)` **from day one**. `diary` + `diary_entry` + `diary_entry_asset(sort_key)`. Markdown → text extraction, FTS5/`tsvector`. Google Keep Takeout import with `source_hash` idempotency. `permission` (album/diary grain) + `share_link`. `pin` (asset/album/diary — no `tag` yet). Populate `asset.perceptual_hash` on new ingest + **one-time backfill** for Phase 1 rows. `/api/duplicates` (Hamming ≤ 6, BK-tree). No supersede yet.

**Web UI.** Collection view + album detail with drag-to-reorder (client-side `sort_key_between`). Diaries view (read-only Markdown timeline). Pinned rail. Duplicates view. Share modal + join-via-link. Import view (Keep + file).

**Android.** No changes.

**Acceptance.** Create 3 albums, drag-reorder, share one via user grant + one via link (test expiry), import 200 Keep notes with a required `tag` + `is_archived` scope (re-run = `unchanged`; verify titles like `2026-04-15 — Kyoto arrival` land with `entry_date=2026-04-15` and `entry.title="Kyoto arrival"`, that `04/15/2026 …` alt-format also works, that a note titled `Kyoto arrival` without a leading date is counted in `skipped_no_date` and not persisted, and that the diary listing returns entries `entry_date DESC`), resolve 5 duplicate clusters. `pytest-cov` ≥ 80 %.

---

## Phase 3 — Intelligence: CLIP Semantic Layer

**Goal.** Text search + find-similar, cross-modal.

**Backend.** `openclip-ViT-B-32` baseline. `asset_embedding` (per-frame for video), `diary_entry_embedding` (chunked ≤ 77 tokens + overlap), `diary_embedding` aggregate. pgvector on prod, JSON on SQLite, IVFFlat/HNSW. Worker paths for both subject types. **Backfill** existing rows via resumable `ingestion_job`. `/api/search/text`, `/search/similar`, `/search/diary`. **No** `/search/group` yet, **no** auto-tagging yet — those land in Phase 4 where they can actually feed something.

**Web UI.** Deliberately minimal: a plain top-bar search box that hits `/search/text` and filters the center grid. Validate CLIP quality *without* the chat UX in the way. "Find similar" action on assets and entries.

**Android.** No changes.

**Acceptance.** Fixture set of 300 photos + 40 entries; hand-labeled truth set; precision@10 ≥ 60 % on cross-modal queries (e.g., "beach at sunset" surfaces both beach photos and beach-mentioning entries). Backfill on a 10 K-row dev DB completes < 30 min. Deterministic-stubbed CLIP path in tests.

---

## Phase 4 — Grouping: Tags & Memories

**Goal.** Namespaced content-category tags + auto Memories.

**Backend.** `tag` + `asset_tag` + `diary_entry_tag` with namespaces (`people:*`, `place:*`, `event:*`, `topic:*`, bare). Namespace validator; reserved-namespace enforcement (CLIP → `topic:*` / bare only). `label_bank` + auto-tagging step in the CLIP worker. `/api/tag/*` incl. `promote-to-album`. `/api/search/group?persist=true` → `event:auto-*`; nightly Memories job. `pin` gains `resource_type='tag'`.

**Web UI.** Memories rail (`?ns=event`). Tags rail (all namespaces as album-like cards). People rail (`?ns=people`, user-attached only — face clustering is v1.1). Asset-detail tag pills (solid = user, ghost = clip_auto).

**Android.** No changes.

**Acceptance.** User attaches `people:michelle` on 20 assets → People card appears. Nightly Memories on a 500-asset fixture produces ≥ 5 `event:auto-*` tags. `promote-to-album` produces a monotonic `sort_key` sequence. Namespace validator rejects `foo:`, `:bar`, uppercase, empty-value. Clip-auto write to `people:*` returns `403`.

---

## Phase 5 — Assistive UX: Chat + Advanced Android

**Goal.** Photo AI right-rail panel; upload profiles + space-saver + supersede.

**Backend.** `chat_session` + `chat_message` + rule-based intent router. `POST /api/chat/session/<id>/message` routes to existing endpoints; persists `result_json`. Extend `precheck` with `phash` + `upload_quality`, return `near_duplicate_of`. Extend `POST /api/asset` with `upload_quality` + `supersedes` + validation. Nightly **supersede sweep**. `/api/duplicates` excludes `superseded_by IS NOT NULL`. Add columns `asset.upload_quality`, `asset.superseded_by`.

**Web UI.** Right-rail Photo AI panel (replaces Phase 3 top-bar search). Suggested-action chips. Inline result strip; "show all in grid" pipe. Chat session list, rename, delete.

**Android.** `upload_profile` + `watch_folder` Room tables. Profile fields: `personal_tags`, `delete_local_after_upload`, `upload_quality`, `upload_videos`, `target_albums`. Pre-upload resize (2048 px / 1080p H.264 @ 8 Mbps). On-device pHash → precheck → supersede policy (skip / upgrade / upload). Migration assigns existing folders to `Default`.

**Acceptance.** Chat: "beach photos" returns result strip; "make an album out of the last search" creates via `group_and_promote`. Android: `Space saver` profile skips a resized copy of an existing full; flip folder to `Full` uploads with `supersedes` and old asset gets `superseded_by`; sweep soft-deletes past grace. `pytest-cov` ≥ 80 % on new code; Android instrumented tests cover resize + precheck decision matrix.

---

## Phase 6 — Integration: MCP + Admin

**Goal.** External agents drive the system; admins can operate it.

**Backend.** `api_token` + scopes (`read_assets`, `read_diaries`, `search`, `write_albums`, `write_tags`, `write_pins`, `write_diary_entries`). `/api/user/api-token` create/revoke. Admin blueprint: user list, token revocation, re-run ingestion, queue depth, quota adjustments. MCP server: stdio + streamable-http; tools/resources/prompts as specced.

**Web UI.** User-info modal → "MCP access" with scope checkboxes. Admin console (role-gated route).

**Android.** No changes.

**Acceptance.** Claude Desktop + Copilot CLI connect via stdio; run `search_media` + `create_album`. A `read_assets`-only token calling `create_album` returns `401`. Admin revokes a token; next call fails.

---

## Phase 7 — Later (v1.1+, not scoped)

Face clustering → `people:*` candidates. Video summarisation (Whisper + captioner). Aesthetics scoring (NIMA). Live Photo. Google Photos / iCloud connectors.

---

## Cross-cutting rules (every phase)

- Alembic migration reviewed on both SQLite and Postgres.
- `pytest-cov` ≥ 80 % on new code.
- Android instrumented tests for any worker/settings changes.
- One-page **user-run acceptance script** matching the "Acceptance" line.
- Bicep updated + dev-subscription deploy.
- README delta.

## Schema-forward moves in Phase 1 (avoids painful ALTERs later)

- `asset.perceptual_hash` shipped as a NULL column in Phase 1; Phase 2 populates + indexes.
- `asset.upload_quality` and `asset.superseded_by` also land as NULL columns in Phase 1; Phase 5 just writes them.
- Embedding tables **not** pre-created — they're separate tables, no cost to defer.

## Milestone gates (user sign-off points)

1. **P1** — "Would I use this daily as basic backup?"
2. **P2** — "Would I show it to a friend as a photo app?"
3. **P3** — "Does CLIP earn its keep on my real photos?"
4. **P4** — "Is the tag/namespace model actually how I think?"
5. **P5** — "Does the AI panel feel useful, does space-saver actually save space?"
6. **P6** — "Can I hand this to my future self as a platform other tools plug into?"
