"""Upload a finished MP4 to the brand's Cloudflare R2 bucket and return its public URL.

Buffer downloads the video when the post goes out, so the URL must be public,
direct (no redirect), HTTPS, and must not expire.

The bucket and its public URL are in the brand's config.json; the account ID and keys are secrets.
"""

from __future__ import annotations

from pathlib import Path

import boto3
import requests

from .secrets import env


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{env('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
        aws_access_key_id=env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def public_url(r2: dict, key: str) -> str:
    return f"{r2['public_base_url'].rstrip('/')}/{key}"


def is_public(url: str) -> int:
    """The HTTP status Buffer would get for this URL (200 means it can download it)."""
    return requests.head(url, timeout=30, allow_redirects=False).status_code


def upload_to_r2(path: Path, key: str, r2: dict, content_type: str = "video/mp4") -> str:
    _client().upload_file(str(path), r2["bucket"], key, ExtraArgs={"ContentType": content_type})
    url = public_url(r2, key)
    status = is_public(url)
    if status != 200:
        raise RuntimeError(f"uploaded file is not publicly reachable at {url} (HTTP {status})")
    return url


def round_trip(r2: dict, key: str) -> str:
    """Upload a tiny file, read it back through the public URL, then delete it. Returns what went wrong, or ""."""
    body = f"setup check {key}\n".encode()
    s3 = _client()
    s3.put_object(Bucket=r2["bucket"], Key=key, Body=body, ContentType="text/plain")
    try:
        r = requests.get(public_url(r2, key), timeout=30, allow_redirects=False)
        if r.status_code != 200 or r.content != body:
            return (f"uploaded to bucket {r2['bucket']!r}, but {public_url(r2, key)} returned HTTP {r.status_code}; "
                    "the public URL in config.json may belong to a different bucket")
        return ""
    finally:
        s3.delete_object(Bucket=r2["bucket"], Key=key)
