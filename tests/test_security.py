"""Security hardening: DNS rebinding, clickjacking headers, open redirects, upload paths, SSRF edge cases."""

import os

from tests.conftest import make_post


def test_unknown_host_header_is_rejected(client):
    """DNS rebinding: a page on evil.example pointed at 127.0.0.1 sends Host: evil.example."""
    assert client.get("/", headers={"Host": "evil.example:8000"}).status_code == 400
    r = client.post("/api/queue/bulk-approve", json={"post_ids": []},
                    headers={"Host": "evil.example", "Origin": "http://evil.example", "X-Requested-With": "x"})
    assert r.status_code == 400
    assert client.get("/api/queue").status_code == 200  # the normal host still works


def test_allowed_hosts_defaults_to_loopback(monkeypatch):
    from config import settings
    from dashboard.security import allowed_hosts
    monkeypatch.setattr(settings, "ALLOWED_HOSTS", "")
    monkeypatch.setattr(settings, "HOST", "127.0.0.1")
    assert set(allowed_hosts()) == {"localhost", "127.0.0.1", "::1"}
    monkeypatch.setattr(settings, "HOST", "0.0.0.0")
    monkeypatch.setattr(settings, "DASHBOARD_PASSWORD", "pw")
    assert allowed_hosts() == ["*"]


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_login_next_cannot_redirect_off_site():
    from dashboard.security import _safe_next
    for bad in ("//evil.com", "/\\evil.com", "https://evil.com", "/\tevil.com", "evil.com", ""):
        assert _safe_next(bad) == "/", bad
    assert _safe_next("/queue?tab=failed") == "/queue?tab=failed"


def test_video_upload_filename_cannot_escape_the_folder(client, db, monkeypatch):
    import content.gif_generator as gg
    seen = {}

    class FakeGenerator:
        def generate_for_post(self, db, post_id, mode, gif_params):
            seen["path"] = gif_params["file_path"]
            return {"success": False, "error": "stop"}

    monkeypatch.setattr(gg, "GifGenerator", FakeGenerator)
    post = make_post(db)
    client.post(f"/api/queue/{post.id}/upload-video",
                files={"file": ("clip.b/../../../../evil", b"data", "video/mp4")})
    assert os.path.dirname(seen["path"]) == os.path.join("dashboard", "static", "videos", "uploads")
    assert seen["path"].endswith(".mp4") and ".." not in seen["path"]


def test_templates_escape_safely():
    """No page may bring back a quote-unsafe escaper, override esc(), or build inline JS from data."""
    import pathlib
    import re
    for f in pathlib.Path("dashboard/templates").glob("*.html"):
        text = f.read_text()
        if f.name != "base.html":
            assert not re.search(r"function esc\(", text), f"{f.name} redefines esc()"
        assert not re.search(r"textContent = \w+;\s*return \w+\.innerHTML", text), f"{f.name} has a quote-unsafe escaper"
        bad = [line.strip() for line in text.splitlines() if re.search(r"on\w+=\"[^\"]*'\$\{", line)]
        assert not bad, f"{f.name} builds inline JS from data: {bad[:2]}"


def test_competitor_url_must_be_linkedin(client):
    ok = client.post("/api/competitors", json={"name": "Dan", "linkedin_url": "linkedin.com/in/dan"})
    assert ok.status_code == 200
    assert client.post("/api/competitors", json={"name": "X", "linkedin_url": "javascript:alert(1)"}).status_code == 422
    assert client.post("/api/competitors", json={"name": "X", "linkedin_url": "https://evil.example/in/x"}).status_code == 422
    client.delete(f"/api/competitors/{ok.json()['id']}")


def test_database_is_owner_only(app):
    from config import settings
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    assert os.stat(db_path).st_mode & 0o077 == 0


def test_netguard_blocks_ipv4_mapped_ipv6():
    from utils.netguard import _is_public_ip
    assert not _is_public_ip("::ffff:127.0.0.1")
    assert not _is_public_ip("::ffff:10.0.0.1")
    assert not _is_public_ip("fe80::1%en0")
    assert _is_public_ip("8.8.8.8")
