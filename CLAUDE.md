# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
source .venv/bin/activate
python app.py                    # Starts FastAPI on http://localhost:8000 with hot-reload
```

The app auto-creates SQLite tables on startup (`init_database()` in `database/engine.py`), starts the APScheduler background jobs, and mounts the dashboard. No separate migration step needed — column additions are handled via `ALTER TABLE` in `engine.py`.

There are no tests or linting configured in this project.

## Architecture

This is a **FastAPI + SQLAlchemy + SQLite** application that automates LinkedIn content: research trending topics, generate posts via Claude API, queue for approval, and publish via LinkedIn REST API.

### Core Pipeline

```
Research (every 6h) → Generate (every 4h) → Queue → User Approval → Post (every 15min)
```

Three APScheduler background jobs run this pipeline (`post_queue/scheduler.py`). The dashboard (`dashboard/routes.py`) is the user-facing approval interface.

### Post Status Flow

`DRAFT → QUEUED → APPROVED → SCHEDULED → POSTING → POSTED` (or `REJECTED`/`FAILED`)

### Key Module Interactions

- **Content generation** (`content/generator.py`) orchestrates: `content_strategy.py` picks topic/tone/template → `prompt_builder.py` assembles Claude prompt with brand persona (loaded from `soul/soul.md`) + virality rules + learning context → Claude generates → `post_formatter.py` normalizes for LinkedIn → `fact_checker.py` validates → `virality_scorer.py` scores
- **Learning system** (`analytics/pattern_analyzer.py` + `analytics/learning_context.py`) analyzes posted content performance and injects insights into future prompts. Requires 10+ posts before analysis runs.
- **Research engine** (`research/research_engine.py`) aggregates from Google Trends, Reddit, RSS news, LinkedIn viral content, and Apify competitor scraping into `ResearchItem` records
- **LinkedIn posting** (`linkedin/poster.py`) has a 4-step pipeline: format → validate → post → verify. Uses the `/rest/posts` endpoint (not legacy UGC API)

### Brand Voice

Always reference `soul/soul.md` before generating any LinkedIn post. This file defines the user's identity, voice, tone, audience, and content pillars. The `BRAND_PERSONA` in `content/prompt_builder.py` loads directly from this file.

## LinkedIn API Gotchas

These are hard-won lessons from production truncation bugs:

- **Newline limit**: LinkedIn silently drops everything after ~25 newlines. `post_formatter.py` enforces `MAX_TOTAL_NEWLINES = 25` with a two-phase reduction (collapse blanks first, then cut at paragraph boundary)
- **Carriage returns**: `\r` characters cause silent truncation — always normalize to `\n`
- **Character limit**: 3000 chars via REST Posts API (the legacy UGC endpoint has a 1300 char limit)
- **Special character escaping**: Handled in `linkedin/api_client.py` to prevent silent truncation
- **Post verification**: After publishing, the system fetches the post back to confirm content integrity

## Configuration

All config lives in `config.py` via `pydantic-settings`, loaded from `.env` (see `.env.example`). Critical keys: `ANTHROPIC_API_KEY`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`. Optional: `REDDIT_CLIENT_ID/SECRET`, `GEMINI_API_KEY`, `APIFY_TOKEN`.

## Database

SQLite at `database/linkedin_posts.db`. Key models in `database/models.py`:
- `QueuedPost` — the central entity (content, status, scheduling, media, scoring, LinkedIn response)
- `PostPerformance` — engagement metrics linked 1:1 to QueuedPost
- `ResearchItem` — trending topics from research sources with relevance scores and velocity tracking
- `LearningInsight` — accumulated patterns from post performance analysis
- `Competitor` / `CompetitorPost` — tracked LinkedIn accounts and their posts
- `MyLinkedInPost` — user's own posts scraped via Apify
- `OAuthToken` — LinkedIn access/refresh tokens with person URN

## Content Templates

Seven built-in templates in `content/templates/template_library.py`: The Expensive Lesson, Contrarian Take, Origin Story, Framework Post, Myth Buster, Data Drop, Quick Tips. `content_strategy.py` rotates between these along with tones and angles.
