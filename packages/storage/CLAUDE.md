# packages/storage: photos and videos in private Supabase Storage buckets

## Purpose
Every Storage call the backend makes: signed read URLs for stored paths, signed upload URLs for new
files, listing what a folder holds, and the path rules that keep files in the right folder.
Bucket layout is described in [../../buckets.md](../../buckets.md).

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | public API used by services | `signed_images(kind, path_lists, expires_in)`, `create_upload(kind, file_name, **ids)`, `existing_files(kind, **ids)`, re-exports below |
| `storage_config.py` | media kinds, allowed types, credentials | `MEDIA_KINDS`, `MediaKind`, `ALLOWED_EXTENSIONS`, `REQUEST_TIMEOUT_SECONDS = 10`, `credentials()` |
| `paths.py` | pure path logic | `folder`, `extension`, `new_path`, `is_in_folder` |
| `client.py` | Storage REST calls via one shared `httpx.Client` | `sign`, `upload_url`, `existing`, `LIST_PAGE_SIZE = 1000` |
| `errors.py` | the one exception | `StorageError` |

## How it works
- A *kind* names a bucket + folder template: `"review"` → `reviews_photos_and_videos`,
  `users/{user_id}/`; `"dish"` → `dish_and_kitchen_photos_videos`, `dishes_pics/{kitchen_id}/{dish_id}/`.
- The DB stores bucket-relative paths (`users/<uuid>/<hex>.jpg`). Responses get
  `signed_images(...)` → for each input list, `[{"path", "url"}]` in order, all signed in one
  `POST /object/sign/<bucket>`.
- Upload flow (`/media/upload-url`): `create_upload` → `new_path` (folder + `uuid4().hex` + original
  extension) → `client.upload_url` (`POST /object/upload/sign/...`, URL valid 2 h). The app PUTs the
  file, then sends the path to `/orders/review` or `/review/edit`, where
  `services.reviews.check_uploaded` uses `is_in_folder` + `existing_files`.
- Auth: `SUPABASE_URL` + `SUPABASE_SECRET_KEY` (service role) from `.env`, read lazily on first call.

## Invariants & gotchas
- `client.sign` never raises: unsignable paths (missing file, Storage down) get `url: None` and the
  response still succeeds. `upload_url` and `existing` raise `StorageError`, which `app/main.py` turns
  into a 502.
- Paths never start with `/` and never include the bucket name. `is_in_folder` accepts only one file
  directly in the folder: no subfolders, `..`, backslashes, hidden files (`.emptyFolderPlaceholder`),
  or disallowed extensions. Non-string entries in stored lists are dropped with a warning.
- Allowed types: `jpg jpeg png webp heic gif mp4 mov webm` (case-insensitive; a name needs a stem).
- The secret key bypasses bucket policies: send it only in headers, never log it
  (`Credentials.__repr__` hides it).
- Keep calls going through the module attribute (`client.sign(...)`): `tests/conftest.py`
  monkeypatches `client.sign`, `client.upload_url`, `client.existing`; a
  `from .client import sign` would bypass the fake.
- `folder(kind, **ids)` needs exactly the IDs its template names (missing one → `KeyError`).
- No code deletes files: removed review images and deleted rows leave files behind.

## How to extend
Three private buckets exist (`buckets.md`; no code creates buckets):
`reviews_photos_and_videos`, `dish_and_kitchen_photos_videos` (also holds
`kitchen_display_pics/<kitchen_id>/`, no kind yet) and `posts_photos_videos` (`kitchens/<kitchen_id>/`,
no kind yet). New media kind (e.g. `"post"` → `posts_photos_videos`, `kitchens/{kitchen_id}/`): add a
`MEDIA_KINDS` entry → widen `UploadUrlIn.kind` in `app/schemas/media.py` → make
`services/media.upload_urls` pass that kind's IDs (it passes only `user_id` today) → validate saved
paths with `is_in_folder` before storing → update `buckets.md` and `docs/End-Points.md`.

## Tests
`tests/test_storage_paths.py` (path rules, no network), `tests/test_storage_live.py` (real Storage,
`live_storage` marker, skipped without keys), and the fake in `tests/conftest.py::fake_storage` used by
every endpoint test.
