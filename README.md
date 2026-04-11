# LinkedIn Content Engine

An AI-powered LinkedIn content automation system that researches trending topics, generates posts using Claude, queues them for your approval, and publishes to LinkedIn — all from a local dashboard.

Built with FastAPI, Claude API, and the LinkedIn REST API.

## What It Does

```
Research (every 6h) → Generate (every 4h) → Queue → You Approve → Auto-Post
```

- **Research engine** — pulls trending topics from Google Trends, Reddit, RSS news feeds, LinkedIn viral content, and competitor posts (via Apify)
- **AI content generation** — Claude writes posts matching your brand voice (defined in `soul/soul.md`), using proven viral templates and your performance data
- **Learning system** — analyzes what performs well and injects those patterns into future prompts
- **Karpathy-style autoresearch** — autonomously tests different hooks, tones, and templates to find what works
- **Dashboard** — approve/reject/edit posts, view analytics, manage competitors, schedule posts
- **LinkedIn posting** — handles OAuth, formatting, newline limits, and post verification

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_ORG/linkedin-content-engine.git
cd linkedin-content-engine

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

| Key | Required | Where to get it |
|-----|----------|----------------|
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com](https://console.anthropic.com/) |
| `LINKEDIN_CLIENT_ID` | Yes | [linkedin.com/developers](https://www.linkedin.com/developers/) |
| `LINKEDIN_CLIENT_SECRET` | Yes | Same as above |
| `REDDIT_CLIENT_ID` | No | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) |
| `GEMINI_API_KEY` | No | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| `APIFY_TOKEN` | No | [console.apify.com](https://console.apify.com/account/integrations) |

### 3. Set up your brand voice

Edit `soul/soul.md` — this is the most important file. It defines:
- Who you are and what you do
- Your target audience
- Your writing voice and tone
- Content pillars (what you post about)
- Phrases and patterns that sound like you

The AI reads this file before generating every post. Take time to fill it out well.

### 4. Run

```bash
source .venv/bin/activate
python app.py
```

Open **http://localhost:8000** in your browser.

### 5. Connect LinkedIn

Go to the **Settings** page in the dashboard and click **Connect LinkedIn**. This starts the OAuth flow to authorize posting on your behalf.

## Architecture

```
app.py                          # FastAPI entry point
soul/soul.md                    # Your brand voice (edit this!)
config.py                       # All settings via .env
│
├── content/                    # Content generation pipeline
│   ├── generator.py            # Orchestrates the full pipeline
│   ├── prompt_builder.py       # Builds Claude prompts from soul.md
│   ├── content_strategy.py     # Picks topics, tones, templates
│   ├── post_formatter.py       # LinkedIn formatting + newline limits
│   ├── fact_checker.py         # AI fact-checking before publish
│   ├── virality_scorer.py      # Scores posts 1-100
│   ├── hook_library.py         # Accumulates winning hooks
│   ├── recycler.py             # Recycles top-performing content
│   ├── image_generator.py      # Gemini image generation (optional)
│   ├── gif_generator.py        # GIF generation (optional)
│   └── templates/              # Post templates (7 built-in)
│
├── research/                   # Topic research
│   ├── research_engine.py      # Aggregates all sources
│   ├── google_trends.py        # Google Trends
│   ├── reddit_scraper.py       # Reddit (requires API keys)
│   ├── news_fetcher.py         # RSS news feeds
│   ├── linkedin_viral.py       # LinkedIn viral content
│   ├── competitor_scraper.py   # Competitor posts (Apify)
│   └── profile_scraper.py      # Your own post scraping
│
├── analytics/                  # Learning from performance
│   ├── pattern_analyzer.py     # Finds what works
│   ├── learning_context.py     # Injects insights into prompts
│   └── performance_tracker.py  # Fetches LinkedIn engagement
│
├── autoresearch/               # Karpathy-style experimentation
│   ├── runner.py               # Autonomous experiment loop
│   ├── log.py                  # Experiment logging
│   └── program.md              # Hypotheses + results
│
├── linkedin/                   # LinkedIn API integration
│   ├── api_client.py           # REST API client
│   ├── poster.py               # Post pipeline (format → validate → post → verify)
│   └── rate_limiter.py         # Rate limiting
│
├── auth/                       # OAuth
│   ├── linkedin_oauth.py       # OAuth flow
│   └── token_manager.py        # Token storage + refresh
│
├── dashboard/                  # Web UI
│   ├── routes.py               # All dashboard endpoints
│   └── templates/              # Jinja2 HTML templates
│
├── database/                   # SQLite + SQLAlchemy
│   ├── engine.py               # DB init + migrations
│   └── models.py               # All models
│
├── post_queue/                 # Scheduling
│   ├── post_queue.py           # Queue management
│   └── scheduler.py            # APScheduler background jobs
│
└── engagement/                 # Comment suggestions
    └── comment_helper.py       # AI comment assistance
```

## Post Status Flow

```
DRAFT → QUEUED → APPROVED → SCHEDULED → POSTING → POSTED
                ↘ REJECTED
                                          ↘ FAILED
```

## Built-in Templates

| Template | Style |
|----------|-------|
| The Expensive Lesson | Vulnerable opener + mistakes + recovery |
| The Contrarian Take | Challenge belief + evidence + "Agree?" |
| The Origin Story | Timeline + turning point + metrics |
| The Framework Post | Before/after + step-by-step |
| The Myth Buster | "Stop doing X" + bad vs good |
| The Data Drop | Surprising stat + data points + tactics |
| The Quick Tips | Numbered tips + engagement question |

Plus 8 Kleo-inspired viral frameworks (AIDA, PAS, Slippery Slide, etc.)

## LinkedIn API Notes

Hard-won lessons built into the formatter:

- LinkedIn silently drops everything after ~25 newlines — the formatter enforces this limit
- `\r` characters cause silent truncation — always normalized to `\n`
- 3000 char limit via REST Posts API (legacy UGC endpoint is 1300)
- After publishing, the system fetches the post back to verify content integrity

## Configuration

All settings in `config.py` via `pydantic-settings`. Key options:

| Setting | Default | Description |
|---------|---------|-------------|
| `POSTS_PER_DAY` | 4 | Target posts per day |
| `POSTING_SLOTS` | "08:00,10:00" | Times to post (in your timezone) |
| `POSTING_TIMEZONE` | "America/Toronto" | Your timezone |
| `POSTING_ACTIVE_DAYS` | "0,1,2,3,4" | Active days (0=Mon, 6=Sun) |
| `TEXT_ONLY_DEFAULT` | true | Text-only posts (no images) |
| `AUTORESEARCH_ENABLED` | true | Enable experiment loop |
| `LEARNING_MIN_POSTS_FOR_ANALYSIS` | 5 | Posts needed before learning kicks in |

See `config.py` for the full list.

## License

MIT — see [LICENSE](LICENSE).
