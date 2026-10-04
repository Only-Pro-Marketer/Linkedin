"""Apify-backed scraping (clear errors, apify-client 3.x support) and the autoresearch gate."""

from datetime import timedelta

import pytest

from config import settings
from research.apify_linkedin import ApifyError, run_actor_items


class FakeRun:  # apify-client 3.x returns models, not dicts
    def __init__(self, dataset_id="ds1", status="SUCCEEDED"):
        self.default_dataset_id = dataset_id
        self.status = status


class FakePage:
    def __init__(self, items):
        self.items = items


class FakeDataset:
    def __init__(self, items):
        self._items = items

    def list_items(self, limit=None):
        return FakePage(self._items[:limit] if limit else self._items)

    def iterate_items(self):
        return iter(self._items)


class ActorV3:
    def __init__(self, run):
        self.run, self.kwargs = run, None

    def call(self, *, run_input=None, run_timeout=None):
        self.kwargs = {"run_input": run_input, "run_timeout": run_timeout}
        return self.run


class ActorOld:
    def __init__(self, run):
        self.run, self.kwargs = run, None

    def call(self, *, run_input=None, timeout_secs=None):
        self.kwargs = {"run_input": run_input, "timeout_secs": timeout_secs}
        return self.run


class FakeClient:
    def __init__(self, actor, items):
        self._actor, self._items = actor, items

    def actor(self, actor_id):
        return self._actor

    def dataset(self, dataset_id):
        return FakeDataset(self._items)


def test_run_actor_items_supports_apify_client_v3():
    actor = ActorV3(FakeRun())
    items = run_actor_items("a/b", {"x": 1}, timeout_s=90, client=FakeClient(actor, [{"text": "hi"}]))
    assert items == [{"text": "hi"}]
    assert actor.kwargs == {"run_input": {"x": 1}, "run_timeout": timedelta(seconds=90)}


def test_run_actor_items_supports_old_dict_runs():
    actor = ActorOld({"defaultDatasetId": "ds1", "status": "SUCCEEDED"})
    items = run_actor_items("a/b", {}, timeout_s=60, limit=1, client=FakeClient(actor, [{"a": 1}, {"a": 2}]))
    assert items == [{"a": 1}] and actor.kwargs["timeout_secs"] == 60


def test_failed_run_raises_a_clear_error():
    with pytest.raises(ApifyError, match="failed"):
        run_actor_items("a/b", {}, client=FakeClient(ActorV3(FakeRun(status="FAILED")), []))


def test_scrapers_explain_a_missing_token(client, db, monkeypatch):
    from database.models import Competitor
    monkeypatch.setattr(settings, "APIFY_TOKEN", "")
    monkeypatch.setattr(settings, "LINKEDIN_PROFILE_URL", "https://www.linkedin.com/in/someone/")
    comp = Competitor(name="Dan", linkedin_url="https://www.linkedin.com/in/dbolzmann/")
    db.add(comp)
    db.commit()
    try:
        r = client.post(f"/api/competitors/{comp.id}/scrape")
        assert r.status_code == 400 and "APIFY_TOKEN" in r.json()["error"]
        db.refresh(comp)
        assert comp.scrape_status == "failed"
        r = client.post("/api/profile/scrape")
        assert r.status_code == 400 and "APIFY_TOKEN" in r.json()["error"]
    finally:
        db.delete(comp)
        db.commit()


def test_manual_autoresearch_waits_for_real_posts(client):
    settings.AUTORESEARCH_ENABLED = True  # restored after the test by conftest
    r = client.post("/api/autoresearch/run")
    assert r.status_code == 400 and "published posts" in r.json()["error"]


def test_a_blocked_profile_actor_is_reported_not_silent(db, monkeypatch):
    """Posts can scrape while the profile actor is blocked; the competitor says so."""
    import research.competitor_scraper as cs
    from database.models import Competitor

    comp = Competitor(name="dbolzmann", linkedin_url="https://www.linkedin.com/in/dbolzmann")
    db.add(comp)
    db.commit()

    def fake_run(actor, payload, timeout_s=None, **kw):
        if actor == cs.PROFILE_ACTOR:
            raise cs.ApifyError(
                "Apify error: This Actor requires full access to your account. You must approve its "
                "permissions before running it: https://console.apify.com/actors/2SyF0bVxmgGr8IVCZ?approvePermissions=true"
            )
        return []

    monkeypatch.setattr(cs, "run_actor_items", fake_run)
    monkeypatch.setattr(cs, "available", lambda: True)

    cs.CompetitorScraper(db).scrape_competitor(comp)

    assert comp.scrape_status == "partial"
    assert "waiting for your approval" in comp.scrape_error
    assert "console.apify.com" in comp.scrape_error


def test_photo_and_name_come_from_the_posts(db, monkeypatch):
    """Each post carries its author, so a competitor has a face even when the
    profile actor is blocked; only the follower count depends on that actor."""
    import research.competitor_scraper as cs
    from database.models import Competitor

    comp = Competitor(name="dbolzmann", linkedin_url="https://www.linkedin.com/in/dbolzmann")
    db.add(comp)
    db.commit()

    post = {
        "id": "p1",
        "content": "A post long enough to be stored by the scraper, with something to say.",
        "linkedinUrl": "https://www.linkedin.com/feed/update/urn:li:activity:1",
        "engagement": {"likes": 10, "comments": 2, "shares": 1},
        "author": {"name": "Daniela Anavitarte Bolzmann", "info": "Amazon content for 8-figure brands",
                   "avatar": {"url": "https://media.licdn.com/dms/image/v2/photo.jpg"}},
    }

    def fake_run(actor, payload, timeout_s=None, **kw):
        if actor == cs.PROFILE_ACTOR:
            raise cs.ApifyError("This Actor requires full access to your account. You must approve its permissions")
        return [post]

    monkeypatch.setattr(cs, "run_actor_items", fake_run)
    monkeypatch.setattr(cs, "available", lambda: True)

    cs.CompetitorScraper(db).scrape_competitor(comp)

    assert comp.profile_picture == "https://media.licdn.com/dms/image/v2/photo.jpg"
    assert comp.name == "Daniela Anavitarte Bolzmann"
    assert comp.headline == "Amazon content for 8-figure brands"
    assert comp.scrape_status == "partial"
    assert "Follower count" in comp.scrape_error


def test_error_text_never_carries_a_credential():
    """Scrape errors are stored on the competitor and shown in the UI."""
    from research.apify_linkedin import _friendly

    msg = _friendly(RuntimeError("Server error '500' for url 'https://api.apify.com/v2/acts/x/runs?token=abc123SECRET'"))
    assert "abc123SECRET" not in msg
    assert "token=***" in msg


def test_without_author_data_the_message_still_names_the_photo(db, monkeypatch):
    """Posts without an author must not claim the photo came from them."""
    import research.competitor_scraper as cs
    from database.models import Competitor

    comp = Competitor(name="someone", linkedin_url="https://www.linkedin.com/in/someone",
                      profile_picture="https://media.licdn.com/old-photo.jpg")
    db.add(comp)
    db.commit()

    def fake_run(actor, payload, timeout_s=None, **kw):
        if actor == cs.PROFILE_ACTOR:
            raise cs.ApifyError("This Actor requires full access to your account. You must approve its permissions")
        return [{"id": "p1", "content": "A post with enough text in it to be stored by the scraper."}]

    monkeypatch.setattr(cs, "run_actor_items", fake_run)
    monkeypatch.setattr(cs, "available", lambda: True)

    cs.CompetitorScraper(db).scrape_competitor(comp)

    assert comp.scrape_status == "partial"
    assert "Photo, headline and follower count" in comp.scrape_error
    assert "came from the posts" not in comp.scrape_error
