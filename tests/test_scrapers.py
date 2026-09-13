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
