"""Minimal client for Buffer's GraphQL API (https://developers.buffer.com)."""

from __future__ import annotations

import json

import requests

from .secrets import env

API = "https://api.buffer.com"


class BufferError(RuntimeError):
    pass


def _gql(query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        API,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {env('BUFFER_API_KEY')}", "Content-Type": "application/json"},
        timeout=60,
    )
    if r.status_code != 200:
        raise BufferError(f"Buffer API HTTP {r.status_code}: {r.text[:500]}")
    body = r.json()
    if body.get("errors"):
        raise BufferError(f"Buffer API error: {body['errors']}")
    return body["data"]


def channels() -> list[dict]:
    """All channels across the account's organizations."""
    orgs = _gql("query { account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for org in orgs:
        data = _gql(
            f"query {{ channels(input: {{ organizationId: {json.dumps(org['id'])} }}) "
            "{ id name displayName service isQueuePaused } }"
        )
        out += data["channels"]
    return out


def channel_for(service: str, all_channels: list[dict], pinned: str | None = None) -> dict:
    """The channel to post to. With a pinned ID (config.json "channels"), only that exact channel will do,
    so a Buffer key pasted into the wrong brand's secret can't post to another brand's accounts."""
    if pinned:
        match = next((c for c in all_channels if c["id"] == pinned), None)
        if match is None:
            raise BufferError(f"the {service} channel {pinned} isn't in this Buffer account; "
                              "the brand's BUFFER_API_KEY secret may belong to another brand")
        if match["service"].lower() != service:
            raise BufferError(f"channel {pinned} is a {match['service']} channel, not {service}")
        return match
    matches = [c for c in all_channels if c["service"].lower() == service]
    if not matches:
        raise BufferError(f"no {service} channel is connected in Buffer")
    if len(matches) > 1:
        raise BufferError(f"several {service} channels; pin one in config.json \"channels\"")
    return matches[0]


def describe_input_types(names: list[str]) -> dict:
    """Introspect Buffer's schema so per-network metadata fields can be checked, not guessed."""
    out = {}
    for name in names:
        data = _gql(
            "query($n: String!) { __type(name: $n) { name inputFields { name "
            "type { kind name ofType { kind name ofType { kind name } } } } "
            "fields { name type { kind name ofType { kind name ofType { kind name } } } "
            "args { name type { kind name ofType { kind name } } } } enumValues { name } possibleTypes { name } } }",
            {"n": name},
        )
        out[name] = data["__type"]
        for f in (data["__type"] or {}).get("inputFields") or []:  # one level of nested input types
            t = f["type"]
            while t.get("ofType") and t["kind"] in ("NON_NULL", "LIST"):
                t = t["ofType"]
            if t["kind"] == "INPUT_OBJECT" and t["name"] not in out and t["name"] not in names:
                out[t["name"]] = _gql("query($n: String!) { __type(name: $n) { name inputFields { name "
                                      "type { kind name ofType { kind name } } } enumValues { name } } }",
                                      {"n": t["name"]})["__type"]
    return out


CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
"""


def post_metadata(service: str, title: str, first_comment: str | None = None) -> dict | None:
    """Per-network settings. `first_comment` goes on Instagram only (InstagramPostMetadataInput.firstComment)."""
    service = service.lower()
    if service == "instagram":
        return {"instagram": {"type": "reel", "shouldShareToFeed": True,
                              **({"firstComment": first_comment} if first_comment else {})}}
    if service == "youtube":
        # Vertical videos under 3 minutes are published as Shorts automatically.
        return {"youtube": {
            "title": title[:100], "privacy": "public", "categoryId": "27",  # 27 = Education
            "madeForKids": False, "notifySubscribers": True, "embeddable": True,
        }}
    return None


def schedule_video(channel: dict, text: str, video_url: str, due_at_utc_iso: str, title: str = "",
                   thumbnail_ms: int = 1500, notify: str | None = None, first_comment: str | None = None) -> str:
    """Schedule a video post. With `notify` (a note shown in the Buffer app), Buffer doesn't publish it: at the due
    time it pushes a notification, and Yashas finishes the post in Instagram, where a trending sound can be added
    (Buffer's API can't attach platform audio to an automatic post). `first_comment` is posted under an Instagram
    post as its first comment (Instagram only, never on a Notify-me post, which is finished by hand); check it was
    kept with first_comment(post_id)."""
    # Networks don't accept a separate cover image through Buffer; Instagram and TikTok use the frame at
    # thumbnailOffset as the cover, which is why the cover is built into the end of the video.
    video = {"url": video_url, "metadata": {"thumbnailOffset": thumbnail_ms}}
    post_input = {
        "channelId": channel["id"],
        "text": text,
        "schedulingType": "notification" if notify else "automatic",
        "mode": "customScheduled",
        "dueAt": due_at_utc_iso,
        "assets": [{"video": video}],
    }
    metadata = post_metadata(channel["service"], title, None if notify else first_comment)
    if notify and channel["service"].lower() == "instagram":
        metadata = {"instagram": {**(metadata or {}).get("instagram", {}), "stickerFields": {"music": notify}}}
    if metadata:
        post_input["metadata"] = metadata

    result = _gql(CREATE_POST, {"input": post_input})["createPost"]
    if "post" not in result:
        raise BufferError(f"Buffer refused the {channel['service']} post: {result.get('message')}")
    return result["post"]["id"]


def post_status(post_id: str) -> dict:
    """What Buffer knows about a post: status, when it went out, its link, the video it used, and its
    metrics once it's out (views, likes, comments, shares, saves, follows, watch time...)."""
    base = "status dueAt sentAt externalLink assets { source thumbnail %s }"
    metrics = " metricsUpdatedAt metrics { type value unit }"
    video = "... on VideoAsset { video { thumbnailOffset } }"
    for fields in (base % video + metrics, base % video, base % ""):
        try:
            return _gql("query($id: PostId!) { post(input: {id: $id}) { " + fields + " } }", {"id": post_id})["post"]
        except BufferError as e:
            last = e
    raise last


def first_comment(post_id: str) -> str | None:
    """The first comment Buffer has stored on an Instagram post (Post.metadata is a union per network; the Instagram
    member, InstagramPostMetadata, has firstComment). None if it wasn't kept."""
    post = _gql("query($id: PostId!) { post(input: {id: $id}) { metadata { ... on InstagramPostMetadata "
                "{ firstComment } } } }", {"id": post_id})["post"] or {}
    return (post.get("metadata") or {}).get("firstComment")


METRIC_FIELDS = "status sentAt externalLink metricsUpdatedAt metrics { type value }"


def post_metrics(post_ids: list[str], batch: int = 20) -> dict[str, dict | None]:
    """Status, link and metrics for many posts, `batch` per request. Posts Buffer can't find map to None."""
    out: dict[str, dict | None] = {}
    for i in range(0, len(post_ids), batch):
        chunk = post_ids[i:i + batch]
        params = ", ".join(f"$id{k}: PostId!" for k in range(len(chunk)))
        body = " ".join(f"p{k}: post(input: {{id: $id{k}}}) {{ {METRIC_FIELDS} }}" for k in range(len(chunk)))
        try:
            data = _gql(f"query({params}) {{ {body} }}", {f"id{k}": pid for k, pid in enumerate(chunk)})
            out.update({pid: data.get(f"p{k}") for k, pid in enumerate(chunk)})
        except BufferError:
            for pid in chunk:  # one deleted post fails the whole batch, so ask one at a time instead
                try:
                    out[pid] = _gql("query($id: PostId!) { post(input: {id: $id}) { " + METRIC_FIELDS + " } }",
                                    {"id": pid})["post"]
                except BufferError:
                    out[pid] = None
    return out


EDIT_POST = """
mutation EditPost($input: EditPostInput!) {
  editPost(input: $input) {
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
"""


def replace_video(post_id: str, service: str, video_url: str, thumbnail_ms: int, title: str = "",
                  first_comment: str | None = None) -> str:
    """Swap a queued post's video for a new render (same post, time and caption). The edit sends the metadata again,
    so an Instagram post's first comment is passed back in to keep it."""
    edit = {"id": post_id, "assets": [{"video": {"url": video_url, "metadata": {"thumbnailOffset": thumbnail_ms}}}]}
    metadata = post_metadata(service, title, first_comment)
    if metadata:
        edit["metadata"] = metadata
    result = _gql(EDIT_POST, {"input": edit})["editPost"]
    if "post" not in result:
        raise BufferError(f"Buffer refused the edit to post {post_id}: {result.get('message')}")
    return result["post"]["id"]
