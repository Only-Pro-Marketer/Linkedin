# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Run and test

```bash
source .venv/bin/activate            # Python 3.12
python app.py                        # http://127.0.0.1:8000 (no reload unless RELOAD=true)
SCHEDULER_ENABLED=false python app.py  # UI only, no background jobs
python -m pytest -q                  # temp DB + fake Claude; no keys or network needed
```

Startup runs `init_database()` (create tables → versioned migrations in `database/migrations.py` → seed the calendar), applies Settings overrides, and moves interrupted `POSTING` posts and `publishing` comments to FAILED/unknown.

## Rules the code relies on

- **Approval gate.** Only `APPROVED`/`SCHEDULED` posts are published (`linkedin/poster.py`). `unschedule` returns a never-approved post to QUEUED. Engage publishes only `approved` drafts (`engagement/publisher.py`). Never add a path that publishes without approval.
- **Limits.** `POSTS_PER_DAY` applies to every publish path; `MIN_HOURS_BETWEEN_POSTS` to automatic ones; `ENGAGE_DAILY_CAP` to comments. Comments: one per scheduler tick, spaced 90–180 s; 403 → manual mode; 429 → pause; timeout/5xx → `unknown`, never retried automatically.
- **All Claude calls go through `llm.py`** (`complete`, `complete_json` with a Pydantic schema). It adds the brand voice + knowledge packs as a cached system prompt, logs usage, and raises `LLMError` subclasses. Don't send `temperature`. Wrap scraped or pasted third-party text with `llm.untrusted()`.
- **Every new post goes through `content/pipeline.create_queued_post`**: format → auto-fix → audit → optional AI repair → review (fact-check + reach score) → save. Don't insert `QueuedPost` rows elsewhere.
- **No invented facts.** Prompts only allow facts from `soul/soul.md` and user notes; missing facts become `[placeholders]`, which the quality audit blocks.
- **Time.** The DB stores naive UTC. Send datetimes to the browser with `dashboard.common.to_iso()` ("…Z"); parse input with `parse_client_dt()` (naive = `POSTING_TIMEZONE`).
- **Quality engine.** `content/humanizer.audit(text, kind)` for kinds post/comment/reply; rules are data in `content/quality_rules.py`. Keep `auto_fix` idempotent.

## Layout

- `dashboard/routers/*.py`: newer pages (home, studio, plan, engage, brand, profile, settings, quality, stats). `dashboard/routes.py`: older pages and APIs. Pages call `dashboard.common.render()`, which adds the nav and status context. Sidebar entries for new pages live in `NAV_CREATE` / `NAV_ENGAGE` / `NAV_SETUP` in `dashboard/common.py`.
- Front end: Jinja templates + Tailwind CDN + vanilla JS. Shared helpers: `static/js/app.js` (`App.api`, `App.confirm`, `App.busy`, `App.qualityBadge`, …), `static/js/post-editor.js` (`PostEditor`, `PostEditor.attach`), `static/css/components.css`. Escape all dynamic HTML with `esc()` and URLs with `safeUrl()`. Anything that publishes needs `App.confirm`.
- `studio/`: writer (formula drafts), repurposer, hook_lab, planner (enforces pillar/formula guardrails), voice (Learn my voice), profile (optimizer). `studio/base.run_tool` records each run in `StudioRun`.
- `engagement/`: comment_drafter (T1–T7), reply_handler (parse → filter → R1–R5), publisher, followups. Reply threading: `parentComment` is always the TOP-level comment URN.
- `knowledge/`: vendored markdown from linkedin-skills (MIT); `knowledge/loader.PACKS` maps features to files.
- Security: `dashboard/security.py` (same-origin check on writes, optional password login), `utils/netguard.py` (public URLs only).

## Adding things

- New page: a router in `dashboard/routers/`, include it in `app.py`, add a nav entry, and add the router to `_page_paths()` in `tests/test_safety.py`.
- New table: add the model; `create_all` creates it. A new column on an existing table needs a step in `database/migrations.py`.
- New UI-editable setting: add it to `app_settings.EDITABLE` and to `FIELDS` in `dashboard/routers/settings.py`.
- Tests: use the `client`, `db` and `fake_llm` fixtures (`fake_llm["text"][feature]`, `fake_llm["json"][feature]`), and `httpx.MockTransport` for LinkedIn.

## LinkedIn API gotchas

- LinkedIn drops everything after ~25 newlines; the formatter and quality audit enforce it.
- `\r` causes silent truncation; always normalize to `\n`.
- Posts: 3000 chars via `/rest/posts`; special characters are escaped in `linkedin/api_client.py`. Comments: 1250 chars.
- After publishing, the post is fetched back to verify its content.
- The comments API call (`/rest/socialActions/{urn}/comments`) and its URN handling haven't been verified against live LinkedIn yet. Test them on your own post first.
