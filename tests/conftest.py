"""Test setup: isolated temp database, no scheduler, no real API keys."""

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # templates/static paths are relative to the repo root

_TMP = tempfile.mkdtemp(prefix="ce-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["DASHBOARD_PASSWORD"] = ""
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["POSTING_TIMEZONE"] = "America/Toronto"
os.environ["APIFY_TOKEN"] = ""
os.environ["KIE_API_KEY"] = ""  # never call real image services from tests
os.environ["GEMINI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from database.engine import init_database
    init_database()
    import app as appmod
    return appmod.app


@pytest.fixture
def client(app):
    with TestClient(app) as c:  # runs the lifespan (DB init, recovery)
        c.headers.update({"X-Requested-With": "tests"})
        yield c


@pytest.fixture
def db(app):
    from database.engine import SessionLocal
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_tables(app):
    """Each test starts with empty post/token/settings tables and default limits."""
    from config import settings
    saved = {k: getattr(settings, k) for k in ("POSTS_PER_DAY", "MIN_HOURS_BETWEEN_POSTS", "DASHBOARD_PASSWORD",
                                               "ENGAGE_DAILY_CAP", "AUTO_REPAIR", "FACT_CHECK_ENABLED",
                                               "AUTORESEARCH_ENABLED", "MIN_QUEUE_SIZE")}
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
    from database.engine import SessionLocal
    from database import models as m
    s = SessionLocal()
    for model in (m.PostPerformance, m.QueuedPost, m.OAuthToken, m.AppSetting, m.StudioRun, m.HookEntry,
                  m.EngagementDraft, m.ContentPlanItem, m.ContentPlan, m.LLMUsage):
        s.query(model).delete()
    s.commit()
    s.close()


DEFAULT_FAKE_POST = (
    "I cut our onboarding call from 60 to 25 minutes in March.\n\n"
    "Clients started asking better questions in week one.\n\n"
    "The trick was sending the 3-page brief two days before the call.\n\n"
    "What is one meeting you shortened that got better?"
)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace every Claude call with canned responses (no network, no key).

    state["text"][feature] -> text for llm.complete
    state["json"][feature] -> dict validated into the requested schema
    state["calls"] records the features called.
    """
    import llm

    state = {"calls": [], "text": {}, "json": {}}

    def complete(feature, user, **kw):
        state["calls"].append(feature)
        return llm.LLMResult(state["text"].get(feature, DEFAULT_FAKE_POST), "fake-model", "end_turn", {})

    def complete_json(feature, user, schema, **kw):
        state["calls"].append(feature)
        if feature not in state["json"]:
            raise llm.LLMError(f"No fake JSON configured for {feature}")
        return schema.model_validate(state["json"][feature])

    def complete_json_loose(feature, user, **kw):
        state["calls"].append(feature)
        return state["json"].get(feature, {})

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(llm, "complete_json", complete_json)
    monkeypatch.setattr(llm, "complete_json_loose", complete_json_loose)
    return state


def make_post(db, **fields):
    """Insert a QueuedPost with sensible defaults."""
    from database.models import PostStatus, QueuedPost
    data = {"content": "Line one of a test post.\n\nLine two with a number: 42.", "status": PostStatus.QUEUED, "topic": "test"}
    data.update(fields)
    post = QueuedPost(**data)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def connect_linkedin(db):
    from auth.token_manager import TokenManager
    TokenManager(db).store_token(access_token="test-token", expires_in=3600, person_urn="urn:li:person:abc123")
