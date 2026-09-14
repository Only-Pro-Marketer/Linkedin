"""Front-end rules the dashboard relies on: CSS layout, asset caching, scheduling feedback."""

import pathlib
import re

from tests.conftest import make_post


def test_static_assets_are_versioned(client):
    """Each restart gets a new ?v=, so browsers don't keep an old stylesheet after an update."""
    html = client.get("/schedule").text
    for asset in ("/static/css/styles.css", "/static/css/components.css", "/static/js/app.js"):
        assert re.search(re.escape(asset) + r"\?v=\d+", html), asset


def test_scheduling_in_the_past_explains_why(client, db):
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/schedule", json={"scheduled_time": "2020-01-01T10:00:00"})
    assert r.status_code == 400
    assert "already passed" in r.json()["error"]


def test_layout_fills_wide_screens_and_never_scrolls_sideways():
    """.app-content must be allowed to shrink (min-width: 0), or one wide row stretches every page past a
    phone screen; the content column grows with the screen up to --content-max instead of a fixed 1200px."""
    css = pathlib.Path("dashboard/static/css/styles.css").read_text()
    assert "min-width: 0" in re.search(r"\.app-content \{(.*?)\}", css, re.S).group(1)
    assert "var(--content-max)" in re.search(r"\.content-wrapper \{(.*?)\}", css, re.S).group(1)
    assert int(re.search(r"--content-max:\s*(\d+)px", css).group(1)) >= 1400


def test_transform_animations_do_not_keep_filling():
    """A transform animation that keeps filling after it ends ("both"/"forwards") turns its element
    into the containing block for position: fixed children, so modals inside .page-enter open
    below the fold on long pages. Entrance animations must use "backwards". Exit animations
    (fadeOut on a card about to be removed) may keep "forwards" so the element stays hidden."""
    css = pathlib.Path("dashboard/static/css/styles.css").read_text()
    exit_anims = {"fadeOut"}
    transform_anims = {
        name for name, body in re.findall(r"@keyframes\s+([\w-]+)\s*\{(.*?)\}\s*\}", css, re.S)
        if "transform" in body and name not in exit_anims
    }
    assert {"fadeInUp", "slideInRight"} <= transform_anims
    for rule in re.findall(r"animation:\s*([^;]+);", css):
        name = rule.split()[0]
        if name in transform_anims:
            assert not re.search(r"\b(both|forwards)\b", rule), f"animation '{rule}' keeps filling"
