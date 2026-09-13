"""Phase 0: security, approval gate, timezones, limits, recovery, migrations."""

from datetime import datetime, timedelta

import httpx
import pytest

from config import settings
from database.models import PostStatus
from tests.conftest import connect_linkedin, make_post


def _page_paths():
    from dashboard.routers.brand import router as brand_router
    from dashboard.routers.home import router as home_router
    from dashboard.routers.engage import router as engage_router
    from dashboard.routers.plan import router as plan_router
    from dashboard.routers.profile import router as profile_router
    from dashboard.routers.settings import router as settings_router
    from dashboard.routers.studio import router as studio_router
    from dashboard.routes import router
    from dashboard.security import router as sec_router
    paths = set()
    routers = (home_router, brand_router, studio_router, engage_router, plan_router, profile_router, settings_router)
    extra = [r for rt in routers for r in rt.routes]
    for r in list(router.routes) + list(sec_router.routes) + extra:
        methods = getattr(r, "methods", set()) or set()
        if "GET" in methods and "{" not in r.path and not r.path.startswith("/api/"):
            paths.add(r.path)
    return sorted(paths)


def test_every_page_renders(client):
    paths = _page_paths()
    assert "/" in paths and "/settings" in paths
    for path in paths:
        r = client.get(path, follow_redirects=False)
        assert r.status_code in (200, 303), f"{path} -> {r.status_code}"


def test_core_apis(client):
    for path in ("/api/queue", "/api/stats", "/api/history", "/api/history?status=failed",
                 "/api/schedule", "/api/calendar", "/api/next-slots"):
        assert client.get(path).status_code == 200, path


# ── CSRF / login ──────────────────────────────────────────────

def test_cross_site_write_is_blocked(client):
    r = client.post("/api/queue/bulk-approve", json={"post_ids": []},
                    headers={"X-Requested-With": "", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_form_post_allowed(client):
    r = client.post("/api/queue/bulk-approve", json={"post_ids": []},
                    headers={"X-Requested-With": "", "Origin": "http://testserver"})
    assert r.status_code == 200


def test_login_required_when_password_set(client):
    settings.DASHBOARD_PASSWORD = "s3cret"
    assert client.get("/", follow_redirects=False).status_code == 303
    assert client.get("/api/stats").status_code == 401
    bad = client.post("/login", data={"password": "nope", "next": "/"}, follow_redirects=False)
    assert bad.status_code == 401
    ok = client.post("/login", data={"password": "s3cret", "next": "/"}, follow_redirects=False)
    assert ok.status_code == 303
    assert client.get("/api/stats").status_code == 200


# ── Approval gate ─────────────────────────────────────────────

def test_post_now_refuses_unapproved_post(client, db):
    post = make_post(db)
    r = client.post(f"/api/post-now/{post.id}")
    assert r.status_code == 409
    db.refresh(post)
    assert post.status == PostStatus.QUEUED


def test_unschedule_never_approved_goes_back_to_review(client, db):
    post = make_post(db)
    assert client.post(f"/api/queue/{post.id}/schedule", json={"scheduled_time": "2031-03-10T09:00"}).status_code == 200
    r = client.post(f"/api/queue/{post.id}/unschedule")
    assert r.json()["post_status"] == "queued"


def test_unschedule_approved_stays_approved(client, db):
    post = make_post(db)
    client.post(f"/api/queue/{post.id}/approve", json={})
    client.post(f"/api/queue/{post.id}/schedule", json={"scheduled_time": "2031-03-10T09:00"})
    r = client.post(f"/api/queue/{post.id}/unschedule")
    assert r.json()["post_status"] == "approved"


# ── Timezones ─────────────────────────────────────────────────

@pytest.mark.parametrize("picked, utc_hour", [("2031-01-15T09:00", 14), ("2031-07-15T09:00", 13)])
def test_schedule_uses_posting_timezone(client, db, picked, utc_hour):
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/schedule", json={"scheduled_time": picked})
    assert r.status_code == 200
    assert r.json()["scheduled_time"] == f"{picked[:10]}T{utc_hour:02d}:00:00Z"
    db.refresh(post)
    assert post.scheduled_time.hour == utc_hour


def test_schedule_accepts_explicit_offset(client, db):
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/schedule", json={"scheduled_time": "2031-01-15T09:00:00+01:00"})
    assert r.json()["scheduled_time"] == "2031-01-15T08:00:00Z"


def test_schedule_rejects_past_time(client, db):
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/schedule", json={"scheduled_time": "2020-01-01T09:00"})
    assert r.status_code == 400


# ── Limits ────────────────────────────────────────────────────

def test_daily_cap(db):
    from linkedin.poster import LinkedInPoster
    settings.POSTS_PER_DAY = 1
    make_post(db, status=PostStatus.POSTED, posted_at=datetime.utcnow())
    blocked = LinkedInPoster(db).check_limits(enforce_gap=False)
    assert blocked and blocked.code == "limit"


def test_min_gap_between_automatic_posts(db):
    from linkedin.poster import LinkedInPoster
    settings.POSTS_PER_DAY = 10
    settings.MIN_HOURS_BETWEEN_POSTS = 3
    make_post(db, status=PostStatus.POSTED, posted_at=datetime.utcnow() - timedelta(hours=1))
    poster = LinkedInPoster(db)
    assert poster.check_limits(enforce_gap=True).code == "limit"
    assert poster.check_limits(enforce_gap=False) is None


# ── Publishing with a mocked LinkedIn API ─────────────────────

def _mock_linkedin(monkeypatch, status=201):
    import linkedin.poster as poster_mod
    from linkedin.api_client import LinkedInAPIClient

    sent = {}

    def handler(request: httpx.Request):
        if request.method == "POST" and request.url.path == "/rest/posts":
            import json
            sent["commentary"] = json.loads(request.content)["commentary"]
            if status >= 400:
                return httpx.Response(status, text="boom")
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"})
        if request.method == "GET" and request.url.path.startswith("/rest/posts/"):
            return httpx.Response(200, json={"commentary": sent.get("commentary", "")})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(poster_mod, "LinkedInAPIClient", lambda token: LinkedInAPIClient(token, transport=transport))
    return sent


def test_post_now_publishes_approved_post(client, db, monkeypatch):
    _mock_linkedin(monkeypatch)
    connect_linkedin(db)
    post = make_post(db)
    client.post(f"/api/queue/{post.id}/approve", json={})
    r = client.post(f"/api/post-now/{post.id}")
    assert r.status_code == 200, r.text
    db.refresh(post)
    assert post.status == PostStatus.POSTED
    assert post.linkedin_post_id == "urn:li:share:999"
    assert post.attempt_count == 1


def test_api_error_marks_failed_and_retry_works(client, db, monkeypatch):
    _mock_linkedin(monkeypatch, status=500)
    connect_linkedin(db)
    post = make_post(db)
    client.post(f"/api/queue/{post.id}/approve", json={})
    r = client.post(f"/api/post-now/{post.id}")
    assert r.status_code == 502
    db.refresh(post)
    assert post.status == PostStatus.FAILED and "500" in post.last_error
    failed = client.get("/api/history?status=failed").json()
    assert [p["id"] for p in failed] == [post.id]
    assert client.post(f"/api/queue/{post.id}/retry").json()["status"] == "approved"


def test_stale_posting_recovered_as_failed(db):
    from linkedin.poster import recover_stale_posts
    post = make_post(db, status=PostStatus.POSTING)
    post.updated_at = datetime.utcnow() - timedelta(minutes=30)
    db.commit()
    assert recover_stale_posts(db) == 1
    db.refresh(post)
    assert post.status == PostStatus.FAILED


# ── Misc ──────────────────────────────────────────────────────

def test_sample_data_endpoint_removed(client):
    assert client.post("/api/analytics/generate-sample-data").status_code in (404, 405)


def test_profile_url_saved_in_db_not_env(client, db):
    from database.models import AppSetting
    assert client.post("/api/profile/set-url", json={"linkedin_profile_url": "javascript:alert(1)"}).status_code == 400
    r = client.post("/api/profile/set-url", json={"linkedin_profile_url": "https://www.linkedin.com/in/jane-doe"})
    assert r.status_code == 200
    assert db.get(AppSetting, "LINKEDIN_PROFILE_URL").value.endswith("jane-doe")


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost:8000", "file:///etc/passwd",
                                 "http://169.254.169.254/latest/meta-data", "ftp://example.com"])
def test_netguard_blocks_unsafe_urls(url):
    from utils.netguard import UnsafeURLError, check_public_url
    with pytest.raises(UnsafeURLError):
        check_public_url(url)


def test_migrations_are_idempotent(app):
    from database.engine import engine
    from database.migrations import run_migrations
    assert run_migrations(engine) == []


def test_tone_regex_stops_at_line_end(db):
    from analytics.pattern_analyzer import PatternAnalyzer
    assert PatternAnalyzer(db)._extract_tone("TONE: authoritative\nANGLE: story") == "authoritative"
