"""CSS rules the dashboard layout relies on."""

import pathlib
import re


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
