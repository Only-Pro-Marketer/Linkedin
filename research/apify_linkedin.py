"""Apify helpers for LinkedIn data (optional; needs APIFY_TOKEN).

Engage, Competitors and the profile import also work without this: the user
pastes text. With a token the app can fetch posts and comments. Actor IDs live
in config because public actors change; field mapping is defensive because
each actor names its fields differently.

`run_actor_items` works with apify-client 3.x (Run models, `run_timeout`) and
older versions (dict runs, `timeout_secs`).
"""

import inspect
import json
import logging
import re
import time
from datetime import timedelta

from config import settings
from linkedin.url_parser import build_parent_comment_urn, parse_linkedin_url

logger = logging.getLogger(__name__)

CACHE_SECONDS = 600
_cache: dict = {}
NO_TOKEN = ("Automatic LinkedIn fetching needs an Apify token. Add APIFY_TOKEN to .env "
            "(console.apify.com → Settings → API & Integrations) and restart the app. "
            "Until then, paste posts in by hand.")
FAILED_STATES = {"FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT", "TIMEDOUT"}


class ApifyError(RuntimeError):
    """A fetch failed; the message is safe to show to the user."""


def available() -> bool:
    return bool(settings.APIFY_TOKEN)


def _field(obj, dict_key: str, attr: str):
    value = obj.get(dict_key) if isinstance(obj, dict) else getattr(obj, attr, None)
    return getattr(value, "value", value)  # enums → their value


def _friendly(e: Exception) -> str:
    text = str(e)
    low = text.lower()
    status = getattr(e, "status_code", None)
    if status == 401 or ("token" in low and ("invalid" in low or "not valid" in low)):
        return "Apify rejected the token. Check APIFY_TOKEN in .env."
    if status == 402 or "insufficient" in low or "credit" in low or "usage limit" in low:
        return "Your Apify account is out of credit or over its usage limit."
    if status == 404 or "not found" in low:
        return "That Apify actor wasn't found. Check the actor ID in .env."
    return f"Apify error: {text[:200]}"


def _as_dict(item) -> dict:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def run_actor_items(actor_id: str, run_input: dict, *, timeout_s: int = 180, limit: int | None = None,
                    client=None) -> list[dict]:
    """Run an actor, wait for it, and return its dataset items. Raises ApifyError."""
    if client is None:
        if not available():
            raise ApifyError(NO_TOKEN)
        from apify_client import ApifyClient
        client = ApifyClient(settings.APIFY_TOKEN)

    actor = client.actor(actor_id)
    kwargs: dict = {"run_input": run_input}
    try:
        params = inspect.signature(actor.call).parameters
    except (TypeError, ValueError):
        params = {}
    if "run_timeout" in params:
        kwargs["run_timeout"] = timedelta(seconds=timeout_s)
    elif "timeout_secs" in params:
        kwargs["timeout_secs"] = timeout_s
    if "logger" in params:
        kwargs["logger"] = None  # don't stream the actor's own log into ours

    try:
        run = actor.call(**kwargs)
    except Exception as e:
        logger.warning("Apify actor %s failed: %s", actor_id, e)
        raise ApifyError(_friendly(e)) from e
    if not run:
        raise ApifyError(f"The Apify run for {actor_id} didn't finish.")
    status = str(_field(run, "status", "status") or "").upper()
    if status in FAILED_STATES:
        raise ApifyError(f"The Apify run for {actor_id} {status.lower().replace('_', ' ')}.")
    dataset_id = _field(run, "defaultDatasetId", "default_dataset_id")
    if not dataset_id:
        raise ApifyError(f"The Apify run for {actor_id} returned no data.")

    try:
        dataset = client.dataset(dataset_id)
        items = dataset.list_items(limit=limit).items if limit else list(dataset.iterate_items())
    except Exception as e:
        raise ApifyError(_friendly(e)) from e
    return [_as_dict(i) for i in items]


def _run(actor_id: str, run_input: dict, limit: int = 200) -> list[dict]:
    """Cached run for Engage lookups (the same post is often fetched twice)."""
    key = (actor_id, json.dumps(run_input, sort_keys=True))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    items = run_actor_items(actor_id, run_input, timeout_s=180, limit=limit)
    _cache[key] = (time.time(), items)
    return items


def _first(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("fullName") or v.get("text") or \
                " ".join(x for x in (v.get("firstName"), v.get("lastName")) if x)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _comment_id(value) -> str | None:
    m = re.search(r"(\d+)\)?\s*$", str(value or ""))
    return m.group(1) if m else None


def fetch_post(url: str) -> dict:
    """{"text", "author"} for one post."""
    items = _run(settings.APIFY_POST_ACTOR, {"urls": [url], "limitPerSource": 1, "deepScrape": False}, limit=3)
    if not items:
        raise ApifyError("Apify returned nothing for that post.")
    post = items[0]
    text = _first(post, "text", "commentary", "content", "postText")
    if not text:
        raise ApifyError("Couldn't read the post's text.")
    return {"text": text, "author": _first(post, "author", "authorName", "author_name", "name")}


def fetch_post_comments(url: str) -> list[dict]:
    """Comments with IDs: [{author, text, comment_urn (top-level), reply_urn}]."""
    post_urn = parse_linkedin_url(url)["post_urn"]
    if not post_urn:
        raise ApifyError("Couldn't read a post ID from that link.")
    items = _run(settings.APIFY_COMMENTS_ACTOR, {"postIds": [url], "limit": 100}, limit=500)
    out: list[dict] = []

    def add(c: dict, top_id: str | None) -> None:
        text = _first(c, "text", "comment", "commentary", "content")
        if not text:
            return
        cid = _comment_id(c.get("comment_id") or c.get("commentId") or c.get("id") or c.get("urn"))
        top = top_id or cid
        out.append({
            "author": _first(c, "author", "authorName", "author_name", "name", "commenter"),
            "text": text,
            "comment_urn": build_parent_comment_urn(post_urn, top) if top else None,
            "reply_urn": build_parent_comment_urn(post_urn, cid) if top_id and cid else None,
        })

    for c in items:
        parent = c.get("parentCommentId") or c.get("parent_comment_id")
        add(c, _comment_id(parent) if parent else None)
        own_id = _comment_id(c.get("comment_id") or c.get("commentId") or c.get("id") or c.get("urn"))
        for reply in c.get("replies") or []:
            add(reply, own_id)
    return out
