# Build-Out Prompt — Memory Hub

A user-scoped website for personal **Albums** (photos + videos) and **Diaries** (dated text journal entries, markdown-formatted, optionally with attached photos/videos), with **CLIP**-powered semantic tagging so a signed-in user can text-search, find similar items, and auto-group across everything they own or have been granted access to. Because CLIP's text encoder shares a 512-dimensional space with its image encoder, the same embedding column supports **cross-modal search** — a text query ranks photos, videos, **and** diary entries in one call, and clicking a photo can surface the diary entries that "feel like" it. Media files live in **Azure Blob Storage**, content-addressed for deduplication; the relational database stores metadata, diary text, and access control.

---

### Preparation
1. Repository file structure: create folders under root — `server` for web API + UI, `mcp-server` for the Model Context Protocol server (agent integration), `android-client` for the Android client, `test` for local test data, and `deployment` for the Bicep/ARM templates that provision the Azure resources.

2. Use `Python` and `Flask` for the web server with `pipenv` for the virtual environment. For web API, use Flask blueprints to group related routes and handlers: `user`, `asset`, `album`, `diary`, `search`, `tag`, `share`, `admin`.

3. Use Kotlin and WorkManager for the Android client (background upload of photos and videos from user-configured watch folders on the device; diary ingestion is web-only via Google Keep Takeout import).

4. For each code folder under root, create a `.gitignore` for the respective language + environment (Python + venv, Node/React build artifacts, Gradle/Android, Bicep `.tfstate`-equivalent locals).

5. Pin CLIP-side deps up front so the ingestion worker is reproducible: `open_clip_torch` (ViT-B/32 baseline; ViT-L/14 opt-in for higher recall), `torch` (CPU wheels are fine for a dev box; GPU only becomes cost-effective past ~10 K new assets/day), `Pillow`, `av` (video decode), `azure-storage-blob`, `azure-identity`, `pgvector` client library, `psycopg[binary]`.

---

### Database Design
SQLite for local dev + tests, **Azure Database for PostgreSQL Flexible Server** with the `pgvector` extension for prod. The **same SQLAlchemy models** work on both — only the vector column swaps between a JSON-encoded fallback (SQLite) and native `vector(512)` (Postgres).

Core tables:

| Table | Purpose | Key columns |
|---|---|---|
| `user` | Registered users. | `id (uuid pk)`, `email (unique)`, `password_hash (nullable — Google-only accounts have no local password)`, `google_sub (unique nullable)`, `friendly_name`, `avatar_blob_key`, `avatar_generator_json` (nullable — DiceBear config `{style, seed, backgroundColor, flip, rotate}` so the avatar picker reopens where the user left off; NULL when they uploaded their own photo), `storage_quota_bytes` (per-user cap, default from env), `storage_used_bytes` (denormalized; updated on ingestion complete and asset delete), `deleted_pin_hash` (nullable — argon2 hash of the PIN that gates the "Deleted" view; NULL until user sets one), `role (user/admin)`, `created_at`, `updated_at`. |
| `refresh_token` | Long-lived auth tokens; supports "keep me signed in" and revoke-on-logout. | `id`, `user_id fk`, `token_hash`, `device_label`, `expires_at`, `revoked_at`. |
| `blob` | Physical, deduplicated storage entry for media. **One row per unique file content**, addressed by `sha256`. | `sha256 (pk, 64-hex)`, `size_bytes`, `mime_type`, `container`, `blob_name` (== `sha256`), `uploaded_at`, `ref_count`. Never delete a blob while `ref_count > 0`. |
| `asset` | A **user-visible** photo or video. Multiple assets can reference the same `blob` (dedupe). | `id (uuid pk)`, `blob_sha256 fk`, `owner_id fk → user`, `kind (photo/video)`, `original_filename`, `capture_ts` (from EXIF/mtime), `width`, `height`, `duration_ms` (video), `exif_json`, `perceptual_hash (pHash, 64-bit)` for near-duplicate detection distinct from bit-exact `sha256`, `upload_quality` (enum `full` / `space_saver` — records whether the uploaded bytes are the original or a client-side downscale from the Android space-saver profile; back-filled from `exif_json.upload_quality` for pre-column rows), `superseded_by (nullable fk → asset.id)` — set when a later `full`-quality upload replaces this asset (typically an earlier `space_saver` copy); the nightly cleanup job soft-deletes superseded rows after a grace period, `poster_blob_sha256` (video thumbnail), `deleted_at (soft delete)`, `created_at`, `updated_at`. |
| `album` | User-curated ordered set of assets (photos + videos). | `id`, `owner_id fk`, `title`, `description`, `cover_asset_id`, `type` (enum `album` / `project` — `project` is a staging bucket shown in the "Projects" section of the left rail; same schema, different UI treatment; promoting a project just flips the enum), `created_at`, `updated_at`. |
| `album_asset` | Association table with a **lexical `sort_key`** (fractional-indexing string like `"a0"`, `"b0"`; insert `"a5"` between them without renumbering neighbours — Notion/Figma/Trello pattern) so the user's curated order is preserved. When the user hasn't dragged anything, `sort_key` is derived from `capture_ts` on insert so new adds land in chronological order for free. | `(album_id, asset_id, sort_key)`. |
| `diary` | A user's journal / notebook. A user can own several (e.g., "Travel 2026", "Cooking"). | `id`, `owner_id fk`, `title`, `description`, `cover_asset_id (nullable)`, `created_at`, `updated_at`. |
| `diary_entry` | A single dated post. Rich text stored in-DB as Markdown; small enough not to need blob storage. | `id (uuid pk)`, `diary_id fk`, `author_id fk → user` (allows co-authored diaries later), `entry_date` (the diary date the user wrote about, may differ from `created_at`), `title` — **primary dedup key** together with `diary_id`; enforced by `UNIQUE (diary_id, title)`, `body_md` (raw Markdown as authored elsewhere and uploaded), `body_text` (extracted plain text for search + embedding), `word_count`, `mood` (nullable free-text or emoji), `location` (nullable string / lat-long), `source` (nullable enum: `google_keep`, `file_upload`, `manual_api`) — tracks where the entry came from, `source_ref` (nullable — Keep note server id, uploaded file name, etc., for diagnostics), `source_hash` (nullable SHA-256 of the source bytes; used to detect whether a re-import actually changed the note), `client_uuid` (nullable, indexed — legacy identity for file uploads that carried YAML front-matter; retained for back-compat but not the primary key), `created_at`, `updated_at`. |
| `diary_entry_asset` | Attaches assets to a diary entry with a **lexical `sort_key`** (same fractional-indexing scheme as `album_asset` — O(1) reorders, no bulk renumber). | `(entry_id, asset_id, sort_key)`. |
| `permission` | Access control at album/diary grain. | `id`, `subject_id fk → user`, `resource_type (album/diary)`, `resource_id`, `role (viewer/editor/owner)`, `granted_by fk → user`, `granted_at`. |
| `share_link` | Signed, expiring URLs for view-only sharing to non-users. | `id`, `resource_type`, `resource_id`, `token_hash`, `expires_at`, `created_by`. |
| `tag` | Content-category dictionary. **Names follow a `namespace:name` convention** — `travel:canada`, `people:michelle`, `place:tokyo`, `event:wedding-2025`, `topic:beach`. Bare names without a colon remain allowed for legacy free-form tags. Reserved namespaces (`people:*`, `place:*`, `event:*`) are **user-curated only** — the CLIP auto-tagger cannot write to them. `topic:*` and bare names are open to auto-tagging. This is the single primitive for *all* content-based grouping (people, places, events, topics, moods); curated ordered collections with title/description/cover/share-grain stay in `album`. | `id`, `name (unique, case-folded — the unique index doubles as the namespace prefix-scan for `WHERE name LIKE 'people:%'`)`, `created_at`. |
| `asset_tag` / `diary_entry_tag` | Many-to-many; the `source` column distinguishes user-authored from CLIP-suggested tags so the UI can render them differently. Namespace-scope rule enforced at write time: `source='clip_auto'` rows may target only `topic:*` or bare-name tags — never `people:*`, `place:*`, `event:*`. Auto-suggestions for reserved namespaces (e.g., a v1.1 face-cluster guess of "michelle") surface as *review candidates* in the People/Places views and are only persisted as `asset_tag` rows after the user confirms them (as `source='user'`). | `(asset_id, tag_id, source in {user,clip_auto}, confidence nullable)` / `(entry_id, tag_id, source, confidence)`. |
| `asset_embedding` | CLIP image/frame embedding. One row per asset for photos; multiple keyframe rows for video. | `id`, `asset_id fk`, `model (e.g. "openclip-ViT-B-32")`, `frame_offset_ms (null for photos)`, `embedding (vector(512) on Postgres, JSON on SQLite)`, `created_at`. Add IVFFlat / HNSW index on `embedding` in Postgres. |
| `diary_entry_embedding` | CLIP **text** embedding of `body_text` (chunked if long — one row per chunk, each ≤ 77 tokens after CLIP tokenization, with `chunk_index` and `chunk_start_offset` for citation). Same 512-d space as `asset_embedding`, so a single ANN index over the union answers cross-modal queries. | `id`, `entry_id fk`, `model`, `chunk_index`, `chunk_start_offset`, `embedding`, `created_at`. |
| `diary_embedding` | Aggregate embedding for a whole diary (mean of its entry-chunk embeddings) so the search UI can rank whole diaries alongside individual hits. Recomputed by a background job when entries change. | `diary_id pk`, `model`, `embedding`, `updated_at`. |
| `pin` | User-pinned resources shown in the left rail's "Pinned" section (a mixed-kind favorites list, distinct from albums). `resource_type='tag'` supports pinning a namespaced tag (e.g., `people:michelle`, `travel:canada`) so the Pinned-People and Pinned-Tag rail entries live here rather than in a bespoke face-cluster table. | `(user_id, resource_type in {asset, album, diary, tag}, resource_id, position, pinned_at)`. |
| `chat_session` | A conversation thread in the right-side "Photo AI" panel. | `id`, `user_id fk`, `title` (auto-derived from first user message, editable), `created_at`, `last_message_at`. |
| `chat_message` | Ordered turns within a chat session. | `id`, `session_id fk`, `role (user/assistant/system)`, `content` (text), `intent` (nullable enum: `search_text` / `find_similar` / `group_and_promote` / `rank_aesthetics` / `summarize_video` / `chit_chat`), `result_json` (nullable — the structured results the assistant rendered inline, so reopening the chat replays the same result strip without re-running the search), `created_at`. |
| `ingestion_job` | Tracks upload → hash → thumbnail → embed → index for assets, **and** create/edit → embed for diary entries. | `id`, `subject_type (asset/entry)`, `subject_id`, `state (queued/hashing/embedding/indexing/done/failed)`, `error`, `attempts`, `updated_at`. |

Indices: `asset(owner_id, capture_ts)`, `asset(perceptual_hash)`, `asset(owner_id, deleted_at)` for the Deleted view, `album_asset(album_id, sort_key)`, `album(owner_id, type)` for the Projects filter, `diary_entry(diary_id, entry_date)`, `diary_entry_asset(entry_id, sort_key)`, `permission(subject_id, resource_type, resource_id)`, `pin(user_id, position)`, `chat_message(session_id, created_at)`, `refresh_token(user_id)`, `asset_tag(tag_id, source)` and `diary_entry_tag(tag_id, source)` so the tag-namespace views can page members quickly and filter user-vs-auto in the same scan, full-text (`tsvector`/`FTS5`) index on `diary_entry.body_text` for exact-keyword fallback, plus the vector-column ANN index above.

---

### Web API
1. Create the web API with Python Flask and SQLAlchemy, backed by SQLite locally (`app.db`) and Azure Database for PostgreSQL in prod. Config via `pipenv`-managed `.env` locally; environment variables + Azure Key Vault references in prod.

2. API root has one endpoint: `GET /api/ping` returning `{ok, version, commit}`.

3. **`user` blueprint** — login, logout, `user_info`, update, avatar.
    - `user` table columns: `id`, `email`, `password_hash`, `google_sub`, `friendly_name`, `avatar_blob_key`, `avatar_generator_json`, `role`, `created_at`, `updated_at`.
    - Login is required for logout, `user_info`, and update. Use **refresh + access token** (JWT, `HS256` locally, `RS256` via Azure Key Vault–backed key in prod). Access token TTL ≈ 15 min; refresh token TTL configurable, default 30 days.
    - User can login with Google (OAuth 2.0 authorization-code flow, PKCE from the SPA). If the `google_sub` is new, the login handler creates the `user` row with a random password hash the user can later reset.
    - Logged-in user can update **their own** `password`, `friendly_name`, and `avatar` (image upload capped at, e.g., 2 MB, jpg/png/webp). Avatar is stored as a regular content-addressed `blob` row and the `avatar_blob_key` FK is updated.
    - Backend method (admin-only, not a route) for adding a new user with a default password — used by tests and bootstrap.

4. **`asset` blueprint** — the core upload / read / delete surface, orchestrating blob + database.
    - `POST /api/asset/precheck` — client sends `sha256` + `size` + optional `phash` (16-hex, on-device perceptual hash) + optional `upload_quality` (`full` / `space_saver`, from the resolved Android upload profile). Server responds `{exists, upload_url?, near_duplicate_of?}`. When `exists = true`, the client skips upload (SHA-256 dedup) and jumps straight to metadata registration. When `phash` is present and no bit-exact match exists, the server also runs a BK-tree lookup over the caller's own `asset.perceptual_hash` with a **strict** Hamming threshold of `≤ 4` (tighter than the `/api/duplicates` view's `≤ 6` so this auto-decision path stays conservative — avoids skipping visually-similar-but-distinct frames from a burst). If a near-duplicate is found, `near_duplicate_of: {asset_id, upload_quality, size_bytes, capture_ts, hamming_distance}` is returned; the client decides the follow-up action per the policy in the Android worker section.
    - `POST /api/asset/upload-url` — issues a **user-delegation SAS** for a single-blob write, valid ~15 min, scoped to `container/{sha256}`. The client uploads directly to blob storage — the API never proxies bytes.
    - `POST /api/asset` — client calls after the blob upload completes; server validates the uploaded blob's hash matches, creates the `blob` row if new, then creates the `asset` row and enqueues an `ingestion_job`. Optional body fields: `tags: string[]` (namespace-validated, attached with `source='user'` — used by the Android upload-profile `personal_tags`), `album_ids: string[]` / `tag_names_to_attach: string[]` (used by upload-profile `target_albums`), `upload_quality: "full"|"space_saver"` (persisted to `asset.upload_quality`), and `supersedes: uuid` (id of an existing `asset` this upload replaces — server validates the caller owns the target and its `perceptual_hash` is within Hamming `≤ 4` of the new asset, then sets `target.superseded_by = new.id`; a mismatch returns `409` so a stale client can't blindly overwrite unrelated assets). **Rejects with `413` when the new asset would push `user.storage_used_bytes` past `user.storage_quota_bytes`** (checked before the `asset` row is inserted). Successful inserts increment `storage_used_bytes` atomically.
    - `GET /api/asset/<id>` — metadata + a short-lived read SAS for the file blob and the poster/thumbnail blob.
    - `GET /api/asset/<id>/thumbnail` — 302-redirect to a read SAS on the poster blob (or the original for photos ≤ some size).
    - `DELETE /api/asset/<id>` — soft delete (sets `deleted_at`); the asset moves to the "Deleted" view. The nightly cleanup job decrements `blob.ref_count` on **permanent** delete (from `/api/trash/<id>` or after the grace-period sweep) and deletes the physical blob when it hits zero. Soft-delete does **not** decrement `storage_used_bytes` — quota still reflects trash contents until purge, matching how iCloud / Google Photos handle it. A companion nightly **supersede sweep** soft-deletes any `asset` with `superseded_by IS NOT NULL AND updated_at < now - grace_period` (default 7 days, configurable per user), then it flows through the same permanent-purge path — this is how "upgrade to full quality" reclaims the space taken by the older space-saver copy.

5. **`album` and `diary` blueprints** — CRUD, membership, cover.
    - `POST /api/album`, `GET /api/album`, `GET /api/album/<id>`, `PATCH /api/album/<id>`, `DELETE /api/album/<id>`.
    - `POST /api/album/<id>/items` — add asset IDs; server rejects any asset the caller doesn't own or have `editor` permission on.
    - `PATCH /api/album/<id>/items/<asset_id>` — body `{sort_key}`. Single-item move to a new fractional-indexing key computed **client-side** from the two neighbours (`sort_key_between(prev, next)` helper in the SPA). O(1) server write, no bulk renumber, no `PATCH …/reorder` bulk endpoint needed. Same shape at `PATCH /api/diary/<id>/entry/<entry_id>/asset/<asset_id>` for diary-entry attachment reorder.
    - Diary routes: `POST /api/diary`, `GET /api/diary`, `GET /api/diary/<id>` (returns metadata + paginated entries), `PATCH /api/diary/<id>`, `DELETE /api/diary/<id>`.
    - `POST /api/diary/<id>/entry` — body `{entry_date, title, body_md, mood?, location?, source?, source_ref?, source_hash?, asset_ids?}`. Server renders the Markdown to plain text (`markdown` + `beautifulsoup4`) into `body_text`, updates `word_count`, attaches referenced assets after ownership check, and enqueues an `ingestion_job` of type `entry`. **Idempotent upsert keyed on title**: the server matches an existing row by `(diary_id, title)`. If a match exists and the new `source_hash` (SHA-256 of the raw source bytes — Google Keep JSON blob, or the uploaded `.md`/`.txt` bytes) equals the stored one, the call is a no-op. If the hash **differs**, the server overwrites `body_md`, `body_text`, `mood`, `location`, `source`, `source_ref`, `source_hash`, re-attaches assets, bumps `updated_at`, and re-enqueues embedding (the old `diary_entry_embedding` rows for that `entry_id` are deleted and rebuilt). Callers may still send an optional `client_uuid` for legacy identity, but title is the primary dedup key.
    - `POST /api/diary/<id>/import/google-keep` — body `{tag: string, is_archived: bool, notes: [KeepNote]}` where `KeepNote` mirrors the Google Takeout Keep JSON schema (`title`, `textContent`, `labels[].name`, `isArchived`, `isTrashed`, `userEditedTimestampUsec`, `attachments[]`). **Both `tag` and `is_archived` are required** — the import is always scoped to one intentional slice of the user's Keep vault, never a blanket dump. The endpoint (1) filters `notes` by `tag` (must match at least one `labels[].name`, case-insensitive) and `is_archived` (must equal `isArchived`), and always skips `isTrashed == true`. (2) For each survivor, **the note's `title` must start with a date in one of two formats — `yyyy-MM-dd` or `MM/dd/yyyy`** — parsed via `^(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b`. The parsed date becomes `entry.entry_date` (the sort key for the timeline — see the diary listing endpoint below) and the remaining title (with the leading date + any separator whitespace/dash/colon trimmed) becomes `entry.title`. Notes whose title does **not** start with a valid date are **skipped** and reported in the response as `skipped_no_date` — the user's expected workflow is to fix the note upstream in Keep and re-run the import. (3) `textContent → entry.body_md` (Keep is plaintext; Markdown renders plaintext fine — store as-is). (4) The `/entry` upsert path is called per note with `source='google_keep'`, `source_ref=<Keep note server_id if present else title-slug>`, and `source_hash=SHA256(json.dumps(note, sort_keys=True))`. Returns `{created: N, updated: M, unchanged: K, skipped_no_date: S, filtered_out_by_tag: T, filtered_out_by_archived: A, skipped_trashed: X}` so a user can reconcile note counts precisely. Attachments in Keep notes are rare and best-effort — if present as image bytes, they go through the normal asset ingestion path and get linked via `diary_entry_asset`.
    - `PATCH /api/diary/<id>/entry/<entry_id>` — same shape; a content-affecting change re-enqueues embedding. Rarely called from a client (entries are typically re-uploaded rather than edited in place); kept for admin and API completeness.
    - `DELETE /api/diary/<id>/entry/<entry_id>`.
    - `GET /api/diary/<id>/entry?from=&to=&q=` — date-ranged, text-filtered listing (uses FTS5/`tsvector`, not CLIP; CLIP search lives in the `search` blueprint). **Default sort is `entry_date DESC`** (latest first) — the diary timeline is a reverse-chronological journal by design. `from`/`to` filter on `entry_date`; the optional `q` full-text filter narrows within that range without changing the ordering.
    - `POST /api/album/<id>/share` and `POST /api/diary/<id>/share` — creates a `share_link` row and returns a signed URL. Access-checked on every hit; diary shares default to the whole diary but accept an optional `entry_id` to share a single entry.

6. **`search` blueprint** — CLIP-powered semantic search, cross-modal.
    - `POST /api/search/text` — body `{query, k, filter?}`. Server runs CLIP **text** encoder on `query` (one shared model instance in the API process), does a vector ANN search across the **union** of `asset_embedding` and `diary_entry_embedding` **restricted to items the caller can see** (owner + explicit `permission` grants). Results are heterogeneous — each hit is `{kind: photo|video|diary_entry, id, score, preview}`. Optional `filter.kind` narrows to one type.
    - `POST /api/search/similar` — body `{subject_type, subject_id, k}`. Works for **either** an asset or a diary entry: server pulls the stored embedding for that subject (avoids re-encoding) and does the same ANN search against the caller's whole visible corpus. So "find similar" on a photo can surface diary entries that describe similar scenes, and vice versa.
    - `POST /api/search/group` — body `{k_clusters, scope=(album|diary|all), persist?: bool}`. Mini-batch k-means over the caller's visible embeddings (assets + entry chunks). When `persist=true` (the default for the nightly Memories job), each surviving cluster is materialised as an `event:auto-<yyyy-mm-dd>-<slug>` tag with `source='clip_auto'` on its members — the Memories rail then reads directly off `GET /api/tag/namespace?ns=event` and Memories become first-class, addressable, pinnable, and promotable to real albums. When `persist=false`, groups are returned inline only.
    - `GET /api/search/diary` — ranks whole diaries (not individual entries) via `diary_embedding`. Useful for "which diary is this about?".

7. **`tag` blueprint** — the single primitive for **all** content-category grouping (people, places, events, topics, moods, trips). Curated ordered collections with title/description/cover/share-grain stay in `album`; tags cover everything else.
    - `GET /api/tag?prefix=…` — autocomplete over the user's own tag set. Prefix matches against the full `namespace:name` so `people:` narrows to the People view, `travel:` to trip tags, etc.
    - `GET /api/tag/namespace` — returns the caller's populated namespaces with counts, and for each tag a suggested **cover asset** (highest-confidence tagged asset for that tag, computed on read). Powers the "Tags" section of the left rail and its per-namespace album-like card grid.
    - `GET /api/tag/namespace?ns=<namespace>` — members within one namespace (e.g., `ns=people` returns every `people:*` tag the caller has, each with cover + count) so the People, Places, and Memories rail entries can render as album-style card grids off a single endpoint.
    - `POST /api/asset/<id>/tag` and `POST /api/diary-entry/<id>/tag` — attach a user tag. The server validates that any colon-containing name matches `^[a-z0-9_-]+:[a-z0-9 _-]+$`, and rejects `source='clip_auto'` writes into reserved namespaces (`people:*`, `place:*`, `event:*`) — only the user-scoped route can attach those. Ingestion attaches `clip_auto` tags via an internal path scoped to `topic:*` and bare names.
    - `DELETE /api/asset/<id>/tag/<tag_id>` and `DELETE /api/diary-entry/<id>/tag/<tag_id>`.
    - `POST /api/tag/<id>/promote-to-album` — takes a namespaced tag (typically an `event:auto-*` from `/search/group`, or a user-selected `travel:*`) and creates a real `album` populated with its current members ordered by `capture_ts` ascending (initial `sort_key`s laid out uniformly so the user can then drag). Optional `{delete_tag: bool}` in the body removes the source tag after promotion. Bridge for the "make an album out of this group" flow — the same flow the AI-chat `group_and_promote` intent lands on.

8. **`pin` blueprint** — powers the left-rail "Pinned" section (mixed-kind favorites; distinct from albums).
    - `GET /api/pin` — ordered list of the caller's pins, joined with the target resource for display.
    - `POST /api/pin` — body `{resource_type, resource_id, position?}`; server appends by default.
    - `PATCH /api/pin/reorder` — body `[{id, position}, …]` for drag-to-reorder in the rail.
    - `DELETE /api/pin/<id>`.

9. **`storage` blueprint** — powers the storage bar at the bottom of the left rail.
    - `GET /api/storage/quota` — returns `{used_bytes, quota_bytes, asset_count, deleted_pending_purge_bytes}` from the denormalized `user.storage_used_bytes` (recomputed nightly by the WebJob as a safety net).

10. **`trash` blueprint** — the "Deleted" view.
    - `POST /api/user/deleted-pin` — set / change the PIN that gates this view (argon2 hash → `user.deleted_pin_hash`). First-time entry to the view forces this.
    - `POST /api/user/deleted-pin/verify` — returns a short-lived (~15 min) `trash_session` cookie so subsequent GETs don't re-prompt.
    - `GET /api/trash` — soft-deleted assets (`deleted_at IS NOT NULL`), newest first, requires the trash-session cookie.
    - `POST /api/trash/<id>/restore` — clears `deleted_at`.
    - `DELETE /api/trash/<id>` — permanent delete: removes the `asset` row, decrements `blob.ref_count`, and enqueues a background sweep to delete the blob when `ref_count == 0`.
    - `POST /api/trash/purge` — bulk permanent delete; requires PIN re-verification.

11. **`duplicates` blueprint** — the "Duplicates" view.
    - `GET /api/duplicates` — clusters the caller's assets by perceptual hash (BK-tree over `asset.perceptual_hash` with Hamming distance ≤ 6 as the cluster threshold; the parameter is tunable per request). Returns `[{cluster_id, members: [{asset_id, capture_ts, size_bytes, kind, upload_quality, preview}]}]`. **Excludes** bit-exact duplicates (already collapsed into a single `blob` at ingestion) **and** rows with `superseded_by IS NOT NULL` (already scheduled for the nightly supersede sweep — surfacing them would double up with the upgrade path). `upload_quality` is returned per member so the UI can render "keep the full-quality one" as the default suggestion.
    - `POST /api/duplicates/resolve` — body `{keep_asset_id, delete_asset_ids: [...]}`; server soft-deletes the losers so they show up in the Deleted view for a grace period before permanent purge.

12. **`chat` blueprint** — powers the right-side "Photo AI" panel.
    - `GET /api/chat/sessions` — list of the caller's sessions with title + last-message preview.
    - `POST /api/chat/session` — create a new session (empty).
    - `GET /api/chat/session/<id>/messages` — full message history for one session.
    - `POST /api/chat/session/<id>/message` — body `{content}`. Server persists the user turn, runs the **intent router**, calls the matching downstream endpoint, persists the assistant turn with `intent` + `result_json`, and returns `{message_id, intent, natural_language_reply, results}`. Intent router (v1) is rule-based:
        - Keyword prefixes ("similar to …", "like this photo") + presence of a `subject_id` in the request context → `find_similar` (`/search/similar`).
        - Phrases like "group", "cluster", "make an album" → `group_and_promote` (`/search/group`, awaits user confirm before creating the album).
        - Phrases like "best", "top picks", "highlights" → `rank_aesthetics` (v1.1; v1 falls back to a heuristic: highest resolution + highest embedding-distance-to-centroid inside the current filter).
        - Phrases like "summarize this video" + a video `subject_id` → `summarize_video` (v1.1; v1 returns "Video summarization arrives in a later release. Here are the sampled keyframes:" + the video's stored keyframes).
        - Everything else → `search_text` (`/search/text`) — the default.
        - The router is a small function today so it can be swapped for an Azure OpenAI **tool-calling** call later without changing endpoints — the tools map 1-to-1 to the existing REST endpoints, so the LLM does no direct DB access.
    - `PATCH /api/chat/session/<id>` — rename a session (title).
    - `DELETE /api/chat/session/<id>`.

13. **`admin` blueprint** (role-gated to `admin`).
    - User list, force-revoke tokens, re-run ingestion, view queue depth, adjust per-user storage quota.

14. **CLIP ingestion worker** — a `flask` app command / separate process (`python -m server.worker`) that drains `ingestion_job` rows. Two paths depending on `subject_type`:

    **For `asset` (photo/video):**
    - Verify blob hash matches (defense against pre-upload tampering).
    - Extract EXIF + basic metadata; write to `asset`.
    - Compute perceptual hash (`imagehash.phash`) → `asset.perceptual_hash`.
    - Generate poster/thumbnail. For **videos**, sample keyframes via `av` (e.g., one per 2 seconds capped at 32 frames), store poster blob (mid-frame), and emit one `asset_embedding` row per sampled frame with `frame_offset_ms`.
    - Run CLIP **image** encoder to produce embedding(s); persist to `asset_embedding`.
    - **CLIP auto-tagging**: score each asset embedding against a curated **zero-shot label prompt bank** (e.g., "a photo of a dog", "a beach at sunset", "a screenshot of a document") stored as one-time-precomputed text embeddings in a `label_bank` table. Each prompt has a target tag name that is either bare (`document`, `screenshot`) or explicitly `topic:*` (`topic:beach`, `topic:sunset`) — the label bank is forbidden from minting tags in the reserved `people:*`, `place:*`, `event:*` namespaces (those are user-curated only; the writer path enforces the same rule). Attach top-N labels above threshold as `asset_tag(source='clip_auto', confidence=…)`. Threshold is configurable per label so noisy prompts can be tightened without a redeploy.

    **For `entry` (diary entry):**
    - Re-derive `body_text` from `body_md` (defensive; the API also does this on save).
    - Chunk `body_text` into ≤ 77-token windows using CLIP's own BPE tokenizer, with ~10-token overlap so a sentence spanning a boundary isn't split mid-thought. Store one `diary_entry_embedding` row per chunk with `chunk_index` and `chunk_start_offset`.
    - Run CLIP **text** encoder over each chunk in a batch; persist embeddings.
    - Auto-tag entries with the same `label_bank` — because both text and image chunks live in the same 512-d space, the same prompt bank works for both without any change. Attach `diary_entry_tag(source='clip_auto', …)`.

    **Common tail (both paths):**
    - Refresh the parent aggregate (`diary_embedding` for entries; skip for assets since assets don't have an aggregate). Mean-pool over the newest set of chunk embeddings.
    - Update `ingestion_job.state`; on failure, exponential backoff via a `next_attempt_at` column.

10. Create a `test` folder with **pytest** cases for every scenario above.
    - Use a fake blob storage (in-memory or `Azurite` in CI) and a temporary SQLite DB per test.
    - Stub CLIP with a deterministic small model or a random-but-seeded embedding to make search tests reproducible.
    - Cover: unauthenticated access denied, ownership boundary, share-link expiry, dedup skip on second upload, ingestion happy path for both asset and entry, idempotent diary import (same title + same `source_hash` = no-op; same title + different `source_hash` = replace `body_md`/`body_text` and re-embed; new title = create), Google Keep Takeout filter behaviour (`tag` and `is_archived` required — request missing either returns `400`; tag match is case-insensitive; `isArchived` mismatch counted in `filtered_out_by_archived`; `isTrashed` always skipped), **Google Keep title-date extraction** (titles starting with `yyyy-MM-dd` populate `entry.entry_date` from the title, not from `userEditedTimestampUsec`; `MM/dd/yyyy` accepted as an alternate format; leading date + separator stripped from the persisted `entry.title`; malformed date like `2026-13-40` counted in `skipped_no_date`; note without any leading date counted in `skipped_no_date` and not persisted), **diary listing sort** (`GET /api/diary/<id>/entry` returns `entry_date DESC` by default, with `from`/`to` filtering on `entry_date`), Android local-delete-after-upload only firing after `POST /api/asset` succeeds **and** the follow-up GET confirms persistence, near-duplicate detection via `pHash`, text-search precision on a fixture set that mixes photos and diary entries (verifies cross-modal ranking is sensible: a text query about "beach" should rank both beach photos and beach-mentioning diary entries), **tag-namespace enforcement** (CLIP auto-tagger rejected when writing `people:*`/`place:*`/`event:*`; user route accepted; malformed `foo:` and `:bar` names rejected; `POST /api/tag/<id>/promote-to-album` produces a monotonically-ordered `album_asset.sort_key` sequence), **`sort_key` fractional-indexing** (insert-between correctness across 100 random shuffles, no key collisions, no bulk renumber), **`POST /api/asset` tag payload** (personal_tags attached with `source='user'`, reserved namespaces still gated to user route, namespace-malformed entries in the array rejected without dropping the whole upload), **pHash precheck + supersede semantics**: (a) `space_saver` incoming when a `full` copy exists (Hamming ≤ 4) returns `near_duplicate_of` and the client skips the upload, (b) `full` incoming when a `space_saver` copy exists uploads with `supersedes`, server sets `superseded_by` and rejects a `supersedes` id whose pHash is Hamming > 4 with `409`, (c) same-quality Hamming-1 pair uploads both and surfaces in `/api/duplicates`, (d) supersede sweep soft-deletes rows past the grace period, (e) `GET /api/duplicates` hides rows already carrying `superseded_by`.
    - If files are created by tests, put their patterns in the `test` folder's `.gitignore`.
    - Track coverage with `pytest-cov`; target ≥ 80 %.

---

### MCP Server (Agent Integration)
Purpose: expose the user's albums, photos, videos, and diaries as **tools** and **resources** to external LLM agents (Claude Desktop, Copilot CLI, Cursor, Continue, custom agents) via the [Model Context Protocol](https://modelcontextprotocol.io/). The MCP server is a **thin translation layer** over the existing Web API — it does **not** re-implement business logic, access the database directly, or hold long-lived credentials of its own. Every call goes back through the same REST endpoints the SPA uses, so ACL, quota, storage-used accounting, PIN gating on the trash view, and audit trails are enforced in exactly one place.

1. **Repository placement**: a new `mcp-server/` folder alongside `server/`, `android-client/`, `test/`, and `deployment/`. Its own `.gitignore` (Python venv + build artifacts).

2. **Runtime + SDK**: Python **`mcp`** SDK (the official reference SDK). Support **both** transports so it works everywhere agents live:
    - **`stdio`** — for locally-launched agents (Claude Desktop, Copilot CLI, Cursor). Entry point `python -m mcp_server.stdio`.
    - **`streamable-http`** with SSE — for hosted / remote agents. Entry point `python -m mcp_server.http --port 8765`, mounted at `/mcp` behind the same Azure App Service; a second App Service app slot (`memory-hub-mcp`) is easier than sharing a port with Flask.

3. **Auth model — per-user API tokens, no shared secret**:
    - New Web API endpoint `POST /api/user/api-token` — the signed-in user (from the web UI, "MCP access" section of the User-info modal) generates a **scoped, opaque, revokable API token**. Server stores an argon2 hash in a new `api_token` table `(id, user_id, hash, name, scopes[], created_at, last_used_at, expires_at, revoked_at)`. Scopes: `read_assets`, `read_diaries`, `search`, `write_albums`, `write_tags`, `write_pins`, `write_diary_entries` — the user checks boxes at generation time.
    - New Web API endpoint `DELETE /api/user/api-token/<id>` — revoke.
    - The MCP server takes the token from either (a) an env var `MEMORY_HUB_API_TOKEN` (stdio) or (b) a per-request `Authorization: Bearer …` header (streamable-http). It never sees the user's password or OAuth refresh token. The Flask API accepts these tokens on any endpoint via a new `X-Api-Token` or `Authorization: Bearer` header, resolves to the owning user, and enforces scopes at the request-handler level.
    - Each MCP tool call maps to one or more REST calls under the caller's token; a scope check happens **on the Flask side**, not in the MCP layer — the MCP server is not a policy enforcement point.

4. **Tools exposed** (each maps to a REST endpoint 1:1 unless noted; input schemas are declared as JSON Schema and returned by `tools/list`):
    - `search_media` `{query: string, k?: number, filter?: {kind?: "photo"|"video"|"diary_entry"}}` → `POST /api/search/text`. Returns a list of hits `{kind, id, title, capture_ts|entry_date, score, preview_url (short-lived read SAS)}`.
    - `find_similar` `{subject_type: "asset"|"diary_entry", subject_id: string, k?: number}` → `POST /api/search/similar`.
    - `list_albums` `{limit?: number, cursor?: string}` → `GET /api/album?…` — paginated.
    - `get_album` `{album_id: string}` → `GET /api/album/<id>` — returns album metadata + a shallow list of member assets with preview URLs.
    - `create_album` `{title: string, description?: string, asset_ids?: string[], type?: "album"|"project"}` → `POST /api/album`, then bulk-add. Requires `write_albums` scope.
    - `add_to_album` `{album_id: string, asset_ids: string[]}` → `POST /api/album/<id>/items`.
    - `list_diaries` / `get_diary_entries` `{diary_id: string, from?: date, to?: date, q?: string}` → mirrors `GET /api/diary/<id>/entry`.
    - `get_diary_entry` `{entry_id: string}` — returns full `body_md` + attached-asset preview URLs. This is the canonical "let the agent read the note" tool.
    - `create_diary_entry` `{diary_id: string, title: string, body_md: string, entry_date?: date, mood?: string, location?: string}` → `POST /api/diary/<id>/entry` with `source='manual_api'` and `source_hash=SHA256(body_md)`. Idempotent-upsert semantics from the existing endpoint carry over — an agent that re-generates the same entry doesn't create duplicates. Requires `write_diary_entries` scope.
    - `pin_resource` / `unpin_resource` `{resource_type: "asset"|"album"|"diary"|"tag", resource_id}` → `POST /api/pin` / `DELETE /api/pin/<id>`. Pinning a `tag` (e.g., `people:michelle`, `travel:canada`) surfaces it in the left rail's Pinned section. Requires `write_pins` scope.
    - `apply_tag` / `remove_tag` `{subject_type: "asset"|"diary_entry", subject_id, tag_name}` → `POST` / `DELETE /api/asset/<id>/tag`. `tag_name` follows the `namespace:name` convention (`people:michelle`, `topic:beach`); reserved-namespace writes (`people:*`, `place:*`, `event:*`) go through this user-scoped path only — the CLIP auto-tagger cannot touch them. Requires `write_tags` scope.
    - `promote_tag_to_album` `{tag_name: string, delete_tag?: boolean}` → `POST /api/tag/<id>/promote-to-album`. Turns a namespaced tag (typically `event:auto-*` or `travel:*`) into a curated album with initial `sort_key`s in `capture_ts` order. Requires `write_albums` scope.
    - `get_storage_quota` `{}` → `GET /api/storage/quota`. Lets an agent decide whether to warn the user before doing a big import.
    - `find_duplicates` `{threshold?: number}` → `GET /api/duplicates`. Returns clusters. **Deleting** duplicates is *not* an MCP tool by design — irreversible destructive actions stay behind the web UI's PIN-gated trash flow. An agent can *suggest* which ones to delete but the human hits the button.

5. **Resources exposed** (`resources/list` + `resources/read`) — these give agents *browsable* content, distinct from tools:
    - `memory-hub://album/{id}` — album metadata + member list as JSON.
    - `memory-hub://diary/{id}` — diary metadata + entry list.
    - `memory-hub://diary/{id}/entry/{entry_id}` — a single entry: JSON `{title, entry_date, body_md, attachments: [preview_url…]}`. This is the shape an agent will most often pull into its own context to answer a user question about "what did I write on the trip".
    - `memory-hub://asset/{id}/preview` — MIME-typed image bytes (streamed from the read SAS server-side so the agent never handles the SAS URL directly and we don't leak signed URLs into logs).
    - Resource URIs are stable and shareable — a user can paste one into an agent session to "attach" the album or entry as context.

6. **Prompts exposed** (`prompts/list` + `prompts/get`) — reusable prompt templates that pre-shape common agent workflows:
    - `curate-trip-album` — takes `{destination, date_range}`, runs a `search_media` for the destination + date, and prompts the model to suggest a curated album title + subset + short description. The template returns messages the agent then sends to its own model — the MCP server doesn't do LLM inference itself.
    - `summarize-diary-week` — takes `{diary_id, week_of}`, pulls the entries via `get_diary_entries`, and asks the model to produce a weekly digest.
    - `find-photos-for-entry` — takes `{entry_id}`, runs `find_similar` to surface photos that "feel like" the entry.
    - Prompts are stored as templated files in `mcp-server/prompts/*.md` with a small YAML front-matter block declaring arguments; loading is dynamic so the user can add new templates without a redeploy.

7. **Configuration & discovery**:
    - Ship a copy-pasteable snippet for each supported host in `mcp-server/README.md`:
        - Claude Desktop `claude_desktop_config.json` snippet with `command`, `args`, and `env: { MEMORY_HUB_API_TOKEN }`.
        - Copilot CLI `mcp.json` snippet.
        - Cursor / Continue equivalents.
    - `.well-known/mcp` on the streamable-http endpoint returns transport details so hosts that support discovery can wire up automatically.

8. **Observability**:
    - Structured logs for every tool call: `{tool, user_id, arg_summary, downstream_status, latency_ms}`, redacting `body_md` bodies to a length + hash.
    - The MCP server emits its own OpenTelemetry traces to the shared Application Insights connection string, tagged `service.name=mcp-server`, so a slow agent call is traceable across the MCP → Flask → Postgres/Blob hop.

9. **Deployment**:
    - **Streamable-HTTP**: same App Service plan as the web app, deployed as a **second Web App** (`memory-hub-mcp`), same managed identity, same VNet integration, same Key Vault reference for the Flask base URL. This keeps the plan single-tenant and cost-flat.
    - **stdio**: users install via `pipx install memory-hub-mcp` from an internal PyPI feed (or `git+https://…` for personal use), so the local agent host launches it as a subprocess.
    - Bicep in `deployment/` gets one extra `Microsoft.Web/sites` for the MCP web app, no new plan.
    - CI builds an MCP wheel alongside the Flask deploy zip; the streamable-http Web App consumes the wheel via a zip deploy.

10. **Testing** — `test/mcp/` fixtures:
    - Unit tests for each tool's argument validation + REST-call composition (mocked Flask).
    - Contract tests against a live-in-memory Flask + Azurite + Postgres.
    - Cover: token scoping (a `read_assets`-only token cannot call `create_album`), storage-quota surfacing via `get_storage_quota`, idempotent `create_diary_entry`, absence of destructive-delete tooling.

11. **Explicitly out of scope for v1** (leave hooks, don't build):
    - Tools for **face-cluster management** (People view) — depends on the v1.1 face pipeline.
    - Tools for **video summarization** — depends on the v1.1 captioner.
    - **Multi-user tenancy from a single MCP process** (an "admin agent" that impersonates users) — a future admin scope.

---

### Web UI
1. Create the SPA with **ReactJS** + **Tailwind CSS**. Vite for the build. Use `@headlessui/react` + `@heroicons/react` for accessible primitives; keep component styling utility-first with a small `tailwind.config.js` theme (brand color, one custom font, standard spacing).

2. **Overall layout — 3-pane, Pixora-style** (see reference mock [`album_ui_design2.webp`](./album_ui_design2.webp) at the repo root):
    - **Left rail (`w-64`, collapsible to icons)** — user's navigation tree, grouped into sections:
        - **Top**: search box (filters the current center-pane view — a *local* filter, not a semantic search; semantic search lives in the AI chat on the right).
        - **Section 1**: **Library** (all owned photos + videos, flat, newest first), **Collection** (= Albums list), **Recently Saved** (last 7 days).
        - **Section 2 — Pinned**: **Video** (`kind = video` filter), **People** (`GET /api/tag/namespace?ns=people` — each entry is a `people:*` tag rendered as an album-like card with cover + count; v1 populates via user-attached tags in the People view, v1.1 face clustering just *proposes* `people:*` candidates for user promotion — no bespoke face-cluster table needed), **Deleted** (soft-deleted assets, PIN-protected — padlock icon).
        - **Section 3 — Projects / Media Type**: **Memories** (auto smart-groups persisted as `event:auto-*` tags by the nightly `/search/group?persist=true` job; the rail reads `GET /api/tag/namespace?ns=event` — each memory is addressable, pinnable, and promotable to a real album via one click), **Tags** (all populated namespaces — `travel:*`, `topic:*`, user-defined — rendered as album-like cards from `GET /api/tag/namespace`; expanding a namespace reveals its values in the center pane), **Live Photo** (Apple Live Photos — v1.1), **Shared Album**, and any user-created *Projects* (a Project is just an Album with `type = 'project'` — same table, different UI treatment: staging area before promotion to a real album).
        - **Section 4**: **Import** (in-flight ingestion queue view + Google Keep / file diary import entry point), **Duplicates** (near-duplicate clusters via `perceptual_hash` Hamming distance).
        - **Section 5 — bottom**: **storage-quota bar** ("X GB of Y GB used") driven by `GET /api/storage/quota`, and a **user pill** with avatar → click opens the User-info modal (change password / friendly name / DiceBear avatar).
    - **Center pane** — the active view's content. Above the grid is a **tab strip** modelled on the mock: each tab is a saved *source* — **Library** (always pinned), plus optional tabs for **Google Photos collection** (v1.1 connector) and **iCloud Photo** (v1.1 connector). For v1, only the Library tab is populated; other tabs are stubbed with a "coming soon" state. Grid layout: masonry-style, virtualized (`@tanstack/react-virtual`), infinite scroll by `capture_ts DESC`; per-card overlays for heart/pin, per-row date header ("Memories — 16-30 April 2025"), and a top-right toolbar (add / share / info / filter).
    - **Right rail — "Photo AI" chat panel (`w-96`, collapsible)** — this **replaces** the standalone Search view. It is the single entry point for **all** semantic operations. See item 3 below.

3. **"Photo AI" chat panel** — the semantic-search + assist surface.
    - Header: model badge ("Photo AI 4.2" is cosmetic — the real backend is CLIP + a small router; keep the label configurable), a "new chat" (`+`) icon, and close (`×`).
    - **Suggested-action chips** displayed on an empty chat (mirrors the mock):
        - "Find specific moments — Search photos by activity or objects." → `POST /api/chat/message` with intent = `search_text` → routes to `POST /api/search/text`.
        - "Create a quick album — Group photos into a new collection." → intent = `group_and_promote` → routes to `POST /api/search/group` then `POST /api/album` on user confirmation.
        - "Suggest best shots — Pick the most visually appealing photos." → intent = `rank_aesthetics` → routes to a NIMA / aesthetics scorer (**v1.1** — for v1 return a sensible fallback of "highest-resolution + most-distinct-embedding" picks).
        - "Summarize video" → **v1.1** (needs Whisper for audio + a captioner for frames); v1 returns a placeholder note.
        - "Recommend related photos" → intent = `find_similar` → routes to `POST /api/search/similar` seeded from the currently-selected asset or the last search result.
    - **Free-text input** at the bottom (`Tell AI what to do next`). Each user turn is a message; the server classifies it against the intent set above with a small rule-based router (v1) and hands off to the relevant existing endpoint. Later this can be swapped for an Azure OpenAI-backed router with tool-calling.
    - **Results render inline in the chat**, not in the center grid: an assistant turn is a bubble with a short natural-language summary ("Here are 12 photos from the beach in April 2025") plus an embedded horizontally-scrolling result strip; the user can then click a result to open it in the center pane, or click "show all in grid" to pipe the result IDs into the center pane's filter state.
    - **Conversation state persists per user** in two new tables (`chat_session`, `chat_message`) so opening the panel later resumes the last thread. A `+` on the header starts a new session.
    - **Cross-modal by default**: because the same `/search/text` call hits both `asset_embedding` and `diary_entry_embedding`, a chat query like "beach trip 2025" surfaces photos, videos, and diary entries together in one result strip, colour-tagged by kind.
    - **Access-scoped**: every intent's downstream call runs under the caller's session, so the AI panel can never leak content the user doesn't own or hasn't been granted `permission` on.

4. **Views** (route-level; each renders inside the 3-pane shell):
    - **Login**, **Signup / Google callback** (no shell).
    - **Library** (default), **Collection** (album grid → album detail with drag-to-reorder), **Recently Saved**, **Video**, **People** (v1.1), **Deleted** (PIN gate + restore / permanent-delete actions), **Memories**, **Shared Album** (own + Shared-with-me merged, toggle in header), **Projects** (album `type='project'` list), **Import** (queue + Google Keep / file diary importer — Google Keep flow is the drop-a-Takeout-zip + tag filter + `isArchived` toggle already specced), **Duplicates** (pHash clusters, per-cluster "keep this / delete others" bulk action).
    - **Diaries** — kept as a top-nav item (not in the left rail sections above; put it under **Projects** as a distinct kind alongside Albums so the rail stays photo-first). Per-diary view is the same read-only Markdown timeline as before; no in-browser editing.
    - **User info modal** (change password, friendly name, DiceBear avatar picker — same functionality as before, moved from a dedicated page into a modal launched from the bottom-left user pill).
    - For avatar, use **DiceBear** (open-source, MIT). Ship the `@dicebear/core` npm package inside the SPA bundle so avatars are generated **client-side, on demand, with a live preview** — the user can pick a style (`avataaars`, `bottts`, `lorelei`, `notionists`, `personas`, etc.), tweak a `seed` string, choose a `backgroundColor`, and re-roll deterministically until they're happy. On save, the SPA rasterizes the SVG to PNG (`canvas.toBlob`) and POSTs it through the same avatar upload endpoint as a direct file upload, so DB storage is uniform (`avatar_blob_key` regardless of source). The generator config (`style`, `seed`, `backgroundColor`, `flip`, `rotate`) is also persisted in a `user.avatar_generator_json` column so the picker reopens with the user's last choice pre-filled and any future edit starts from where they left off — this is the "edit on demand" gap Multiavatar can't cover, since Multiavatar has no styling parameters at all. Direct file upload (jpg/png/webp) remains supported as an alternative for users who want to bring their own photo.
    - Support "keep me signed in" by persisting the refresh token in an **HttpOnly, Secure, SameSite=Lax** cookie set by the server; the SPA never touches the refresh token from JS.
    - Access token lives in memory only; a silent refresh runs a minute before expiry.
    - Photo/video upload flow uses the `precheck → upload-url → asset` sequence; the browser PUTs blobs directly to Azure Blob Storage. A per-file progress bar reads from `XHR`/`fetch` upload events.
    - Search UI shows CLIP-suggested tags as ghost-outlined chips (`ring-1 ring-slate-300` vs solid `bg-brand-500` for user tags) so the user can visually distinguish them from their own tags and can promote or dismiss with a single click.

5. After the SPA is built, update the Web API to host the SPA at `/` and `/index` (Flask static folder pointing at `server/ui/dist/`, with a catch-all route returning `index.html` so client-side routes work on refresh).

6. Create or update `readme.md` for how to set up, run tests, run the worker, seed a dev user, and deploy.

---

### Data Ingestion (Android Client)
1. Kotlin + **WorkManager** app. Single responsibility: **photo and video upload** from user-configured folders on the device. Diary ingestion is handled entirely by the web UI (Google Keep Takeout import + file upload), not by the Android app.

2. Auth: reuse the same OAuth 2.0 endpoints as the web SPA (Google sign-in via Android `Credential Manager`), exchange for the same refresh/access tokens; store the refresh token in Android **EncryptedSharedPreferences**.

3. Photo/video upload worker (constraints: unmetered network, charging optional user setting, retry with `ExponentialBackoff`):
    - Enumerate new items under the user-selected **watch folders** (see settings below). Use `DocumentFile` / `MediaStore` depending on whether the folder is a `content://` tree URI or a plain MediaStore bucket; persist a `last_seen_generation` per folder so re-enumeration is incremental.
    - For each candidate, resolve its **upload profile** (the folder-group profile assigned to the watch folder — see Settings). All per-file decisions below read from that profile, not from global flags.
    - **Optional pre-upload resize (profile-level `upload_quality`)**: if the profile's quality is `space_saver`, downscale photos in-memory to a max long-edge of **2048 px** (JPEG q=85 re-encode; preserves EXIF orientation, capture time, GPS) and transcode videos to **1080p H.264 @ 8 Mbps** using `MediaCodec`; if `full`, upload the original bytes unchanged. The Google-Photos analogue is deliberate. Resize happens *before* the SHA-256 pass so `sha256` addresses the actual bytes that land in blob storage (otherwise dedup would break — two devices resizing the same source would still upload twice).
    - Compute `SHA-256` on-device (streamed; no full-file load in memory) on whatever bytes the resize step produced.
    - Compute the **on-device pHash** on the resized bytes (`imghdr` + a small pure-Kotlin DCT-pHash port, or a JNI wrapper around `pHash`); videos use the poster frame. This runs on the resized bytes so it matches whatever the server persists as `asset.perceptual_hash`.
    - Call `POST /api/asset/precheck` with `{sha256, size, phash, upload_quality}`. Three response cases:
        1. `exists=true` (bit-exact hit) → skip upload, jump to `POST /api/asset` with the same metadata.
        2. `near_duplicate_of` present → resolve per this **supersede policy** using the incoming `upload_quality` vs `near_duplicate_of.upload_quality`:
            - `space_saver` incoming **and** existing is `full` → **skip the upload entirely**, mark `upload_state` done, increment discovered count. No bandwidth wasted, no dedup nag later. The user already has the higher-quality copy on the server.
            - `full` incoming **and** existing is `space_saver` → upload the full copy, then call `POST /api/asset` with `supersedes = near_duplicate_of.asset_id`. Server sets `superseded_by` on the old asset; the nightly cleanup job soft-deletes superseded rows after a grace period (default 7 days, configurable) so a mis-flagged supersede is recoverable from the Deleted view.
            - Same quality on both sides (`full`↔`full` or `space_saver`↔`space_saver`) → upload anyway. Bursts and near-identical frames should not be auto-collapsed; `/api/duplicates` handles them with the user in the loop.
        3. Neither hit → `POST /api/asset/upload-url`, `PUT` the blob to the returned SAS URL, then `POST /api/asset` — include the profile's **`personal_tags`** in the request body as `{tags: ["travel:daily-driver", "device:pixel-9", …]}`; the server attaches them with `source='user'` (namespace-validated per the `tag` blueprint rules) so every photo lands pre-tagged. Always include the resolved profile's `upload_quality` as a top-level field (persisted to `asset.upload_quality`); it also lands in `exif_json.upload_quality` for legacy provenance.
    - Persist per-file state in a Room database (`upload_state`) so a killed process resumes cleanly. `upload_state` also records the resolved `profile_id`, `resized: bool`, and `original_size_bytes` so a retry doesn't re-resize a file whose resized copy is already cached.
    - Auto-attach each upload to an "Auto: <device_label>" album owned by the user, so a fresh install shows everything in one place until the user curates.
    - **Post-upload local delete (profile-level `delete_local_after_upload`)**: if the profile's toggle is on, the worker deletes the source file only **after** `POST /api/asset` returns 200 **and** a follow-up `GET /api/asset/<id>` confirms the server-side row is persisted. On any earlier step failure, the local file is left untouched. Deletions go through `DocumentFile.delete()` (SAF) or `MediaStore` update depending on the URI kind; on Android 11+ this may prompt the user the first time per folder to grant write permission — the settings screen explains this up front and offers a "grant write access" button per configured folder. Under `space_saver`, this deletes the original — the local device keeps no full-resolution copy after successful upload (matching Google Photos' "free up space" behaviour).

4. **Settings screen** — organised around **upload profiles** (folder-groups). A profile is a named policy; each watch folder is assigned to exactly one profile, and profiles are the unit at which per-file behaviour is configured. This lets a user say "Camera + Screenshots share one policy, but WhatsApp Images uses a different one" without duplicating settings per folder.
    - **Upload profiles** — top-level list. Each profile has:
        - `name` (user-supplied, e.g., "Daily driver", "Space-saver bulk", "Received media").
        - **`personal_tags`** (chip-input, autocomplete against `GET /api/tag?prefix=…`) — tag names auto-applied on upload for every asset in folders under this profile. Namespaced (`device:pixel-9`, `source:whatsapp`, `travel:2026-trip`) or bare. Namespace validation matches the server rule (`^[a-z0-9_-]+:[a-z0-9 _-]+$`). CLIP auto-tags are still added independently on the server (into `topic:*`/bare) and don't collide.
        - **`delete_local_after_upload`** (boolean) — the same "delete local copy after successful upload" toggle, moved from per-folder to per-profile. First-time-per-folder write-permission prompts still fire per folder.
        - **`upload_quality`** (enum: `full` / `space_saver`) — chooses the pre-upload resize policy. UI copy: **Full** ("Original resolution — best quality, uses more storage") vs **Space saver** ("Compressed to 2048 px / 1080p — smaller uploads, faster on cellular"). Mirrors Google Photos' "Storage saver" vs "Original quality".
        - **`upload_videos`** (boolean; default on) — replaces the old global "photos only" switch, now per profile so a user can e.g. sync WhatsApp photos-only while syncing DCIM in full.
        - Optional: **`target_albums`** (multi-select of the user's albums or `event:auto-*` tags) — every upload from this profile's folders is auto-added as an `album_asset`/`asset_tag` row. Useful for a "Travel 2026" folder that should also land in the "Travel 2026" album.
    - **Default profile**: on first launch a `Default` profile is created (`personal_tags=[]`, `delete_local_after_upload=false`, `upload_quality=full`, `upload_videos=true`) and every newly-added folder is assigned to it. Users can create additional profiles from the profiles list, edit them in place, and re-assign folders.
    - **Watch folders** — list of folders the app scans for uploads. Add via the system directory picker (`ACTION_OPEN_DOCUMENT_TREE`, so the URI is persistable across reboots). Each row shows the folder path, item count discovered so far, last scan time, an inline dropdown showing the **assigned profile** (tap to switch to a different profile), and a "grant write access" button when SAF write-permission isn't yet granted. Users can add multiple folders (e.g., DCIM/Camera, Pictures/Screenshots, WhatsApp Images), group them under whichever profiles they want, and one profile can back many folders.
    - **Room storage**: two new tables — `upload_profile(id, name, personal_tags_json, delete_local_after_upload, upload_quality, upload_videos, target_albums_json, created_at, updated_at)` and `watch_folder(uri, display_path, profile_id fk, last_seen_generation, last_scan_at, discovered_count)`. Existing `upload_state` gains `profile_id` (nullable during migration; back-filled on first re-scan).
    - **Global switches** (stay global — they gate the worker itself, not per-file behaviour): "upload only on Wi-Fi", "upload only while charging".
    - **Storage**: clear local cache, view uploaded-count / pending-count (broken down per profile).
    - **Account**: sign out (revokes the refresh token server-side).
    - Settings are persisted in a small Room table (`app_settings` KV + `watch_folder(uri, delete_after_upload, last_seen_generation)`), backed up via Android auto-backup so a reinstall restores the user's watch list.

---

### CLIP & Search Notes (implementation guardrails)
- **One shared model instance** in the API process for query encoding; the worker owns its own instance to keep ingestion decoupled.
- Dimension: **512** for ViT-B/32; if we later upgrade to ViT-L/14 (768), do it behind the `model` column on `asset_embedding` / `diary_entry_embedding` and keep both indices during migration. Never mix dimensions in a single index.
- **Same-space assumption**: CLIP's text and image encoders map to the same 512-d unit-sphere-normalized space. All embeddings — asset, entry chunk, and query — must be `L2`-normalized at write and query time. Cosine similarity then reduces to a dot product, which is what `pgvector`'s HNSW index expects with `vector_ip_ops`.
- **Access-scoped ANN**: every search filters `WHERE (owner_id = :me OR EXISTS (permission …))` **before** the ANN step (Postgres HNSW with a `WHERE` pre-filter clause; on SQLite fallback, filter first then brute-force). This is the difference between correct and privacy-leaking search.
- **Video** search: keyframe hits collapse to their parent asset by max-score; return the best-matching frame offset so the UI can seek there.
- **Diary chunk** search: chunk hits collapse to their parent entry by max-score, but the API also returns the winning `chunk_start_offset` so the UI can scroll to and highlight the exact passage.
- **Cross-modal caveat**: image ↔ text scores are directly comparable (that's the whole point of CLIP's contrastive training), but the **magnitude** of image-to-image similarity tends to run higher than image-to-text — so when mixing kinds in one result list, re-rank by percentile-within-kind before merging if the raw scores skew the top results toward one modality. Ship it plain first, add the re-rank only if UX feedback demands it.
- **Grouping** is ad-hoc (mini-batch k-means over the caller's embeddings on request), not persisted, so re-runs after new uploads produce fresh clusters without stale rows.

---

### Deployment
Target: **Azure**, IaC in **Bicep** under `deployment/`. Everything runs under a **user-assigned managed identity** so we never store secrets outside Key Vault.

Resources:
| Resource | Purpose | Notes |
|---|---|---|
| **Azure App Service** (Linux, Premium v3 P1v3 to start) | Hosts the Flask web API + static SPA in **one** Web App. Also hosts the CLIP ingestion pipeline as an **Azure WebJob** in the same App Service plan — the WebJob shares the app's file system, environment variables, and managed identity, so no separate compute or credentials to wire up. | Deploy from a zip / OCI image built in CI. Use `SCM_DO_BUILD_DURING_DEPLOYMENT=false`; build the SPA in CI and ship the built assets in the deploy artifact. Enable "Always On" so the API doesn't cold-start. |
| **CLIP pipeline as a Triggered WebJob** | Scheduled job that drains queued `ingestion_job` rows. | Ship as `deployment/webjob/clip-pipeline/` containing `run.sh` (activates the pipenv env, then `python -m server.worker --drain`) and `settings.job` with a scheduler entry. See details below. |
| **Azure Database for PostgreSQL Flexible Server** | Metadata + diary text + `pgvector` for embeddings. | Private endpoint into the App Service VNet integration subnet; VNet integration on the App Service. Password stored in Key Vault; connection assembled at boot from a Key Vault reference. Prefer Entra-ID (`azure_ad_authentication = ON`) with the managed identity where the driver supports it, and fall back to the Key Vault password otherwise. |
| **Azure Blob Storage** | One container for `assets` (hash-named), one for `thumbnails`, one for `avatars`. | Lifecycle rule: move `assets` to Cool after 30 days no read, Archive after 180. Soft-delete + versioning ON. Change-feed OFF (not needed). |
| **Azure Key Vault** | JWT signing key, Google OAuth client secret, Postgres password. | RBAC-based access via managed identity; the App Service references secrets with `@Microsoft.KeyVault(SecretUri=…)` app settings so they're rotatable without redeploy. |
| **Azure Application Insights + Log Analytics** | Metrics, traces, app logs for **both** the web app and the WebJob (they share the App Insights connection string because they're the same App Service). | Instrument via `opentelemetry-instrumentation-flask` + `azure-monitor-opentelemetry-exporter`. |

**WebJob details (CLIP pipeline, once per day at midnight):**
- Type: **Triggered** (not Continuous), scheduled via a CRON expression in `settings.job`: `{ "schedule": "0 0 0 * * *" }` (App Service CRON is 6-field: second, minute, hour, day, month, day-of-week — this fires at 00:00:00 every day, in the App Service's configured `WEBSITE_TIME_ZONE`).
- The WebJob process loads the same Python virtualenv as the web app (both live under `D:\home\site\wwwroot\`), imports `server.worker`, and calls `drain(max_batch=…, deadline_minutes=…)` — the deadline is set so the job self-exits well before the next midnight even if the queue is large.
- The WebJob runs **only** during its scheduled window; between runs, `ingestion_job` rows sit in `queued` state and are visible in the admin UI so late-night uploads are auto-picked-up on the next tick.
- The web app **does not** import the CLIP model at API request time (except for text-query encoding, which is a single lightweight text-encoder pass). The image encoder is loaded exclusively inside the WebJob process to keep the API's memory footprint small.
- **Text search still works between runs**: a query only needs the text encoder (fast, always resident in the API process) and the already-persisted asset/entry embeddings. Newly uploaded assets simply don't appear in results until the next midnight run — surface this to the user in the UI with a "processing…" badge on any asset whose `ingestion_job.state != 'done'`.

**App Service plan sizing considerations:**
- P1v3 (2 vCPU, 8 GB RAM) is the practical minimum. CLIP ViT-B/32 needs ~1.5 GB resident during the WebJob run; the web app needs enough headroom for concurrent request handling. P2v3 (4 vCPU, 16 GB) if the daily photo volume grows past a few thousand and the WebJob starts blowing its overnight window.
- **No GPU on App Service.** ViT-B/32 on CPU handles hundreds of images per hour at batch=32; if throughput becomes a problem, revisit and either move the WebJob to a **Container Apps job** (GPU-optional) or run it on a scheduled **Azure Container Instance** with a GPU SKU — but keep it out of scope for v1 per the App Service preference.
- Turn on **Always On** for the web app. WebJobs on Triggered schedule also need Always On to fire reliably.

Networking: **VNet integration** on the App Service; private endpoint to Postgres and Blob Storage. SAS URLs still work for direct browser/Android upload because Blob's public endpoint stays reachable via the storage firewall's "allow trusted Microsoft services" list plus the SAS bearer, which is the auth on the wire.

Blob naming: `{container}/{sha256[0:2]}/{sha256[2:4]}/{sha256}` — the two-level prefix keeps partitions balanced under Azure Storage's internal sharding without changing the fact that `sha256` alone is unique.

CI/CD: GitHub Actions.
1. `test` job — pipenv install, run pytest with `Azurite` service container + Postgres service container, upload coverage.
2. `build` job — build the SPA bundle (Vite), place under `server/ui/dist/`; produce the App Service deploy zip (Python app + built SPA assets + the `App_Data/jobs/triggered/clip-pipeline/` WebJob folder inside it).
3. `deploy` job — `az webapp deploy --src-path` on dev on every merge to `main`; on tag push, run a Bicep `what-if` against prod, wait for manual approval, then deploy.
4. `deployment` job — `bicep build` + `az deployment sub what-if` on every PR that touches `deployment/`.

Bootstrap steps documented in `readme.md`:
1. `az login`, `az account set --subscription …`.
2. `az deployment sub create -f deployment/main.bicep -p env=dev` — provisions the whole stack empty.
3. Push the App Service zip (with the embedded WebJob).
4. Seed the label bank via a one-off `flask seed-labels` command (runs against the App Service through Kudu SSH, or locally against the Postgres private endpoint from a jump box).
5. Create the first admin user via `flask create-admin --email … --password …`.
6. Verify the WebJob is registered in the portal (App Service → WebJobs) and that the next scheduled run shows midnight local time.

---

### Addendum
- **Non-goals for v1**: face recognition (privacy + regulatory footprint too large for a personal-scale build); public-timeline / social features; multi-tenant billing; collaborative real-time diary editing.
- **Future**: OCR pass (`azure-ai-vision`) so screenshots and photographed pages become text-searchable (their extracted text becomes another `diary_entry_embedding`-style row anchored to the asset); Whisper transcription on video audio tracks so speech becomes searchable the same way; user-editable label bank so people can curate their own zero-shot vocabulary; per-album / per-diary cover auto-selection using CLIP similarity to the title; a stronger text-only encoder (e.g., `bge-small-en`) as a second embedding column on `diary_entry_embedding` for pure text-to-text ranking, kept alongside the CLIP text embedding rather than replacing it.
- **Cost sensitivity**: CLIP embed is the dominant cost. The worker should batch encode (`batch_size=32` on CPU, `128` on a T4). Cold-start is fine because the worker container is not user-facing. Diary text embeddings are much cheaper than image embeddings, so the throughput bottleneck stays the photo/video pipeline.
- **Backup**: Postgres geo-redundant backups (7-day PITR) — critically, this is where diary text lives, so the RPO matters more than for the blob-backed assets. Blob Storage soft-delete + versioning covers accidental deletes; a monthly `azcopy` snapshot to a second storage account in a paired region covers account-level loss.
