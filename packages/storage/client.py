"""The Supabase Storage HTTP calls (https://<project>.supabase.co/storage/v1), with the secret key.

Each function makes one call per bucket (list pages aside). The key goes only in headers and is
never logged.
"""

import logging
from urllib.parse import quote

import httpx

from .errors import StorageError
from .storage_config import REQUEST_TIMEOUT_SECONDS, credentials

logger = logging.getLogger(__name__)

LIST_PAGE_SIZE = 1000

# One client for the process: keeps connections open between calls. Safe to share across threads.
_http = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)


def _api() -> str:
    return credentials().url + "/storage/v1"


def _post(endpoint: str, body: dict | None = None):
    key = credentials().key
    try:
        response = _http.post(_api() + endpoint, json=body or {},
                              headers={"apikey": key, "Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        raise StorageError(f"Storage unreachable ({type(exc).__name__}: {exc})") from exc
    if response.status_code >= 400:
        raise StorageError(f"Storage answered {response.status_code}: {response.text[:300]}")
    return response.json()


def sign(bucket: str, paths: list[str], expires_in: int) -> dict[str, str | None]:
    """Signed download URLs valid for expires_in seconds, in one call for all paths.
    A path Storage can't sign (e.g. never uploaded) maps to None, and so does every path when
    Storage can't be reached, so a reader still gets the rest of its response."""
    urls: dict[str, str | None] = dict.fromkeys(paths)
    if not urls:
        return urls
    try:
        items = _post(f"/object/sign/{quote(bucket)}", {"expiresIn": expires_in, "paths": list(urls)})
        api = _api()
    except StorageError as exc:
        logger.warning("Could not sign %d files in %s: %s", len(urls), bucket, exc)
        return urls
    for item in items if isinstance(items, list) else []:
        path, signed = item.get("path"), item.get("signedURL")
        if path in urls and signed:
            urls[path] = api + signed
    unsigned = [path for path, url in urls.items() if url is None]
    if unsigned:
        logger.warning("%d of %d files in %s could not be signed (not uploaded?): %s",
                       len(unsigned), len(urls), bucket, unsigned[:5])
    return urls


def upload_url(bucket: str, path: str) -> str:
    """A signed URL the app can PUT one file to, at exactly this path (valid for 2 hours)."""
    data = _post(f"/object/upload/sign/{quote(bucket)}/{quote(path, safe='/')}")
    relative = data.get("url") if isinstance(data, dict) else None
    if not relative:
        raise StorageError(f"Storage returned no upload URL for {bucket}/{path}")
    return _api() + relative


def existing(bucket: str, folder: str) -> set[str]:
    """Paths of the files directly inside folder (subfolders and placeholders excluded)."""
    names: set[str] = set()
    offset = 0
    while True:
        page = _post(f"/object/list/{quote(bucket)}",
                     {"prefix": folder, "limit": LIST_PAGE_SIZE, "offset": offset})
        page = page if isinstance(page, list) else []
        # folders come back with id null
        names.update(folder + item["name"] for item in page
                     if item.get("id") is not None and item.get("name"))
        if len(page) < LIST_PAGE_SIZE:
            return names
        offset += LIST_PAGE_SIZE
