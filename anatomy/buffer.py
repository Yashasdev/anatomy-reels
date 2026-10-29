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


def post_metadata(service: str, title: str) -> dict | None:
    service = service.lower()
    if service == "instagram":
        return {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    if service == "youtube":
        # Vertical videos under 3 minutes are published as Shorts automatically.
        return {"youtube": {
            "title": title[:100], "privacy": "public", "categoryId": "27",  # 27 = Education
            "madeForKids": False, "notifySubscribers": True, "embeddable": True,
        }}
    return None


def schedule_video(channel: dict, text: str, video_url: str, due_at_utc_iso: str, title: str = "",
                   thumbnail_ms: int = 1500) -> str:
    # Networks don't accept a separate cover image through Buffer; Instagram and TikTok use the frame at
    # thumbnailOffset as the cover, which is why the cover is built into the end of the video.
    video = {"url": video_url, "metadata": {"thumbnailOffset": thumbnail_ms}}
    post_input = {
        "channelId": channel["id"],
        "text": text,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due_at_utc_iso,
        "assets": [{"video": video}],
    }
    metadata = post_metadata(channel["service"], title)
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
