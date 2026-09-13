# LinkedIn Software Overview

A complete read-through of the two LinkedIn projects in this folder: what each one does, how it works, what is broken, and how they fit together.

| | Project | Location | Version read |
|---|---|---|---|
| **A** | **LinkedIn Content Engine** (your app) | this folder (`github.com/Only-Pro-Marketer/Linkedin`) | commit `c5152a9` (2026-04-11) |
| **B** | **linkedin-skills** (Serge Bulaev, MIT) | `linkedin-skills/` (not part of your repo, excluded in `.git/info/exclude`) | v1.0.44 |

Written 2026-09-12. Every file in both projects was read (about 97 files in A; all 11 skills, `lib/`, `scripts/` and `references/` in B). Line numbers are given as `file:line` so you can check any claim.

---

## TL;DR

1. **Your engine is a full autopilot app.** Every 6 hours it researches trends, every 4 hours Claude writes posts into a queue, you approve them in a web dashboard, and a job every 5 minutes publishes approved posts through LinkedIn's official API.
2. **Serge's repo is not an app.** It is 11 instruction files ("skills") that tell Claude how to write posts, comments and replies in a chat. You approve each draft, then it publishes through Publora or you copy and paste.
3. **Your engine is not ready to run yet.**
   - `soul/soul.md` (your brand voice) is still the empty template, so every prompt gets `[YOUR NAME]` placeholders.
   - The code hard-codes an "e-commerce / supplement agency owner" persona in many places.
   - There is no `.env`, no virtualenv and no database yet.
4. **There are security problems to fix before real use.**
   - The dashboard has no login and listens on `0.0.0.0:8082`, so anyone on your Wi-Fi can open it, approve and publish posts, spend your API credits, or rewrite `.env`.
   - Some paths skip approval: "Post Now" publishes un-approved posts, and "Schedule, then Unschedule" silently approves a post.
5. **There is a timezone bug.** Scheduled posts go out 4 to 5 hours early in Toronto.
6. **The "learning" system mostly learns from nothing.**
   - Nothing fetches real LinkedIn engagement automatically.
   - A dashboard button writes fake random engagement into the real database.
   - "Autoresearch" is Claude scoring Claude, about 72 extra Claude calls a day.
7. **Serge's best ideas would improve your engine's writing quality.** The humanizer (AI-tell scrubber), the 2026 hook rules (for example "never open with a question") and the voice profile can go into your `content/prompt_builder.py`. Several of your built-in templates use patterns his data says cost reach (for example "Stop X", "Agree or disagree?").

---

## Update, 2026-09-12: the two projects are now one app

Everything below describes the code **as it was before the merge**. The problems it lists have been fixed on branch `feature/unified-app`:

- **Safety.**
  - The app listens on 127.0.0.1, with an optional password.
  - Cross-site writes are blocked.
  - Post Now and Unschedule can no longer skip approval.
  - `POSTS_PER_DAY` and a minimum gap apply to every publish path.
  - The timezone bug is fixed.
  - Stuck posts are recovered at startup.
  - The fake sample-data button is gone, and URL fetches are limited to public hosts.
- **One Claude layer (`llm.py`)** with prompt caching, refusal handling and a usage log. Serge's playbooks are vendored in `knowledge/`.
- **One quality gate for every draft.**
  - It's the humanizer ported to Python: AI-tell audit, safe auto-fixes and one AI repair pass.
  - It's followed by a combined fact-check and reach score.
  - The 20 hook formulas are built in, and templates that used invented first-person claims were replaced.
- **New features from linkedin-skills:**
  - Studio (Write / Repurpose / Hook Lab), Plan (weekly plan with enforced guardrails);
  - Engage (comments and replies posted through the LinkedIn API after approval, with Copy + Open as a fallback);
  - Brand Voice editor with *Learn my voice*, Profile Optimizer;
  - a Settings page with limits, posting times and AI usage;
  - manual stats in History.
- **New UI.** Home "Today" page, grouped sidebar, a shared post editor with a live quality check and a LinkedIn preview, and confirm dialogs on everything that publishes.
- **Tests.** A pytest suite covers the approval gate, limits, timezones, the quality engine and every new feature.

See `README.md` for the current feature list and setup, and `CLAUDE.md` for the architecture rules.

---

# PART A: Your LinkedIn Content Engine

## A1. What it is

A local web app built with **FastAPI + SQLAlchemy + SQLite + APScheduler**. It uses the **Claude API** for writing and scoring, **Gemini** for images (optional), **Apify** for LinkedIn scraping (optional) and the **LinkedIn REST API** for posting.

```
Research (every 6h) → Generate (every 4h, if queue < 10) → QUEUE → You approve in dashboard → Post job (every 5 min) → LinkedIn
        ↑                                                                                                   │
        └──────────── Learning analysis (daily 08:30) + Autoresearch (every 8h) feed back into prompts ←───┘
```

| Folder | Job |
|---|---|
| `app.py`, `config.py` | Start-up and all settings (from `.env`) |
| `soul/soul.md` | Your brand voice; read before every generation |
| `content/` | Writes posts: strategy, prompts, formatting, fact-check, virality score, hooks, recycling, images, GIFs |
| `research/` | Finds topics: Google Trends, Reddit, RSS/Google News, competitors (Apify), your own posts (Apify), deep research |
| `analytics/` | Learning loop: fetch engagement, find patterns, inject insights into prompts |
| `autoresearch/` | Automated experiments on hooks, tones and lengths (Claude-judged) |
| `engagement/` | Drafts comments on competitor posts (you post them by hand) |
| `linkedin/`, `auth/` | LinkedIn OAuth, posting, rate limit |
| `post_queue/` | Queue actions and the scheduler jobs |
| `database/` | Models and ad-hoc migrations |
| `dashboard/` | Web UI (Jinja2 templates + JS) |
| `existing_tool/` | An older "post analyzer" tool. Only `PostAnalyzer` is still used. |

## A2. Background jobs (`post_queue/scheduler.py:243-341`)

| Job | When | What it does |
|---|---|---|
| research_cycle | every 6 h | Pulls topics from all sources → `ResearchItem` rows |
| generation_cycle | every 4 h | If fewer than 10 QUEUED posts, writes `min(10 − queued, 5)` new posts |
| **posting_cycle** | **every 5 min** | Publishes due SCHEDULED posts, then the oldest APPROVED post if inside a calendar window |
| token_refresh | daily 00:00 | Refreshes the LinkedIn token if it expires within 7 days |
| competitor_scrape | daily 06:00 | Apify scrape and AI analysis of tracked competitors |
| profile_scrape | daily 07:00 (only if `LINKEDIN_PROFILE_URL` is set) | Scrapes your own posts |
| learning_analysis | daily 08:30 | Runs 12 pattern analyses → `LearningInsight` rows |
| hook_extraction | daily 09:00 | Saves winning hooks into the hook library |
| autoresearch_cycle | every 8 h | 3 experiments × 4 variations, Claude-scored |

Notes:
- Cron times use the **computer's local timezone**, not `POSTING_TIMEZONE`.
- Interval jobs first run one interval after start-up, so the first automatic posts appear about 4 hours after you start the app.

## A3. Post lifecycle and the approval gate

```
(DRAFT is never used)  QUEUED ──approve──► APPROVED ──(calendar window)──► POSTING ──► POSTED
                          │  └──schedule──► SCHEDULED ──(time reached)───►    │
                          └──reject──► REJECTED                              └──► FAILED
```

- **Everything the AI creates starts as QUEUED:** batch generation, Idea Lab, regenerate, recreate-competitor, autoresearch winners, recycler and research-to-post.
- **The automatic job only publishes APPROVED or SCHEDULED posts,** so the AI never publishes on its own.
- **Approval can be bypassed:**
  - **Post Now** (`/api/post-now/{id}`) publishes posts that are still **QUEUED** (`linkedin/poster.py:253-257`).
  - **Schedule, then Unschedule** turns a never-approved QUEUED post into **APPROVED** (`post_queue/post_queue.py:131`), and it then goes out automatically.
  - **No login and no CSRF protection.** Any device on your network, or a malicious web page you visit, could call `/api/post-now/{id}` (post IDs are 1, 2, 3…).
- **Calendar windows:**
  - They come from the database seed: Mon/Fri 09:00 and Tue/Wed/Thu 08:30 (`database/engine.py:219-246`), ±15 min.
  - With **5 or more APPROVED** posts waiting, the calendar is ignored and one post goes out **every 5 minutes** (`poster.py:340`).
  - There is no daily cap: `POSTS_PER_DAY` exists in config but is never used.

## A4. How a post is written (`content/generator.py`)

1. **Plan** (`content_strategy.py`). For each post it picks:
   - **Template:** avoids the last 5 used; weighted by past performance.
   - **Topic:** an unused research item, or a weighted category.
   - **Tone:** no repeats within a batch.
   - **Angle:** from template keywords.
2. **Add performance context:**
   - learning insights (up to 8, confidence ≥ 0.4)
   - autoresearch "winning parameters" (dimensions with 3+ experiments)
   - up to 5 winning hooks from the hook library
3. **Build the prompt** (`prompt_builder.py`), in this order: `soul.md` persona → `VIRALITY_RULES` → performance context → hooks → template → topic, tone, angle → research context.
4. **Claude call 1: write** (`claude-sonnet-4-20250514`, temperature 0.8, max 1500 tokens).
5. **Format** (`post_formatter.py`):
   - strip markdown and trailing hashtags
   - put blank lines between thoughts
   - **cap at 25 newlines** (LinkedIn silently cuts long posts)
   - normalise `\r`
   - 3000-character limit
6. **Analyse structure** (`existing_tool/post_analyzer.py`): hook type, body format and CTA type.
7. **Claude call 2: fact-check** (`fact_checker.py`) → pass / warning / fail, **advisory only**. A "fail" is still queued.
8. **Claude call 3: virality score** (`virality_scorer.py`):
   - six parts, 100 points total: Hook 25, Structure 20, Value 20, Engagement 15, Voice 10, Relevance 10
   - plus a heuristic adjustment from −13 to +15
   - tiers: low below 40, medium 40–64, high 65–84, viral 85+
9. **Save as QUEUED.**
10. **Optional media.** It is off by default (`TEXT_ONLY_DEFAULT=True`); when on, it makes a Gemini image or a GIF (Claude plans it, Pillow renders it).
11. **At publish time** the formatter and validator run again.

**Key prompt rules** (`VIRALITY_RULES`, `prompt_builder.py:39-81`):
- 150–250 words
- scroll-stopping first line
- a blank line between every sentence
- no markdown, no hashtags
- 0–3 emoji
- end with an easy question
- text-only ("16x better for this account", a hard-coded account-specific claim)

**Templates in rotation: 19** (the docs say 7):
- **7 classic** (`template_library.py`): Expensive Lesson, Contrarian Take, Origin Story, Framework Post, Myth Buster, Data Drop, Quick Tips.
- **8 "Kleo" frameworks:** AIDA, Authority Reference, Slippery Slide, Transformation Arc, Conflict Story, PAS, Do This Not That, Vulnerable Truth.
- **4 JSON templates** (supplement niche, auto-extracted from `existing_tool/sample_posts.json`): The Bold List, The Contrarian List, The Failure Debrief, The Unknown.

**Other lists:**
- **Tones (5):** authoritative, conversational, provocative, vulnerable, data-driven.
- **Angles (7):** personal_story, data_insight, contrarian_take, how_to, newsjack, myth_buster, case_study.
- **Idea Lab:** 6 variants and structures AIDA, PAS, BAB, PPP.

**Other content tools:**
- **Hook library:** hooks from top own posts (likes + 3×comments + 5×shares ≥ 50) and competitor posts.
- **Recycler:** rewrites posts that are 60+ days old with 50+ engagement. It discards the result below a score of 45 and has no dashboard button.
- **Regenerate:** rewrites a post using your rejection reason.

## A5. Research engine (`research/`)

| Source | How | Needs | Relevance score |
|---|---|---|---|
| Google Trends | `pytrends` (unofficial): US and GB trending, plus 6 random "rising" queries from 9 e-commerce seed groups | nothing | 0.8, or min(value/100, 1) |
| Reddit | PRAW, 8 subreddits (supplements, ecommerce, Entrepreneur…), top 30 | `REDDIT_CLIENT_ID/SECRET` | min(upvotes/100, 1) |
| News | 23 RSS feeds, plus 8 of 27 Google News queries | nothing | 0.6 / 0.7 |
| "LinkedIn viral" | Competitor posts and your own scraped posts from the DB, plus Google News `site:linkedin.com` | Apify data | tiered 0.5–0.95 |
| Competitors (daily) | Apify `dev_fusion/linkedin-profile-scraper` + `harvestapi/linkedin-profile-posts`, then a Claude analysis of each post | `APIFY_TOKEN` | — |
| Your profile (daily) | Same actors | `APIFY_TOKEN` + `LINKEDIN_PROFILE_URL` | — |
| Deep research (button) | Fetch the URL, Claude extracts data, Playwright screenshot | Anthropic | — |

**Ranking:**
- Topics are grouped by their first 5 meaningful words.
- +0.1 for each extra source; the top 50 are kept.
- Velocity is labelled new / rising / falling / stable against the last 14 days.
- There is **no dedupe across cycles**, so the same topic is inserted again every 6 hours.

## A6. Learning loop and autoresearch: what really happens

**Learning loop** (`analytics/`):
- **Engagement score** = likes + 3×comments + 5×shares.
- **12 analyses:** hook, tone, template, topic, length, weekday, time of day, media, rejections, your edits, research vs non-research, prediction accuracy.
- A group must be 1.2× or better than average to earn "Prefer", or 0.7× or worse for "Avoid".
- Needs **5 POSTED posts** (the code says 5; `CLAUDE.md` wrongly says 10).
- Insights with confidence ≥ 0.4 are injected into prompts, up to 8.

**Gaps in the loop:**
- **No job ever fetches real engagement.** It only happens when you click "Refresh Engagement". The daily analysis runs on whatever data exists.
- **`/api/analytics/generate-sample-data` writes random fake likes and comments** into the real database, and they pollute learning permanently.
- **The LinkedIn engagement parser probably reads the wrong fields** (`performance_tracker.py:120-124`). Check it against a live response.
- **Old insights are never retired.** Duplicates and contradicting insights pile up.

**Autoresearch** (`autoresearch/`):
- Every 8 hours: 3 experiments × 4 variations. Claude writes each one, and Claude scores it.
- A winner scoring ≥ 65 is added to the QUEUE (still needs your approval).
- **Cost:** about 24 Claude calls a cycle, about 72 a day.
- **It never uses real LinkedIn results.** The "calibration" subtracts a 1–100 score from raw engagement counts, which are different scales.
- **Template experiments don't actually change the template** (`runner.py:163, 350`), and only hypotheses 1–3 in `program.md` ever run.

**Comment helper** (`engagement/comment_helper.py`):
- Picks 15 recent competitor posts a day and drafts comments with Claude.
- **It never posts.** You copy the draft and mark it done.

## A7. LinkedIn integration

**OAuth:**
- Flow: `/auth/login` → LinkedIn → `/auth/callback`.
- Scopes: `openid profile w_member_social r_member_social`.
- `r_member_social` is a restricted scope that LinkedIn only gives to approved (Community Management API) apps. If authorization fails, remove it (`auth/linkedin_oauth.py:23`).

**Tokens:**
- Stored in plain text in SQLite, 60 days.
- Refresh tokens are usually not issued to normal apps, so expect to reconnect every 60 days.

**Posting pipeline** (`linkedin/poster.py`):
1. Rate check (80 a day, in memory, reset on restart).
2. Format and validate.
3. `POST /rest/posts`.
4. Read the post back and check that at least 90% of the characters arrived.

**Media and failures:**
- Images and videos use the upload APIs. **If media fails, it posts text-only and still reports success.**
- FAILED posts don't show in any list and can't be retried.
- A crash leaves a post stuck in POSTING.

## A8. Dashboard (`http://localhost:<PORT>`)

| Page | What you can do |
|---|---|
| **Queue** (`/`) | See AI posts with fact-check and virality badges. Approve, edit, reject (10 reasons), regenerate, add image/GIF, schedule, Post Now, bulk actions, "Generate Posts (5)", "Run Research". Refreshes every 60 s |
| **Idea Lab** | Type an idea, pick variants, formats, tones, angles and structure, generate posts |
| **Research Hub** | Topic list and interactive topic map; filter, save, create posts from research, deep research |
| **Schedule** | Week view; schedule, reschedule, unschedule |
| **Analytics** | Your scraped post stats, template chart, best-times heatmap, hook library, "Refresh Engagement" |
| **Competitors** (+ detail) | Add and scrape competitors, AI analysis per post, "Recreate" a competitor post as your own |
| **Experiments** | Autoresearch results and win rates |
| **Learnings** | Insights; activate or deactivate; run analysis |
| **History** | Published, approved and rejected posts; repost, edit |
| **Settings** | LinkedIn connection, token status, profile URL, scrape now |

The UI loads Tailwind, Google Fonts and Chart.js from CDNs, so it needs internet. Many API routes exist with no button (calendar editing, recycling, sample data, import history…).

## A9. Settings (`config.py`)

**Settings that matter:**

| Setting | Default | Note |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required** for generation |
| `LINKEDIN_CLIENT_ID` / `_SECRET` | — | **Required** for posting |
| `LINKEDIN_REDIRECT_URI` | `http://localhost:8000/auth/callback` | Must match the port |
| `CLAUDE_MODEL` / `FACT_CHECK_MODEL` | `claude-sonnet-4-20250514` | An older snapshot; consider `claude-sonnet-5` |
| `HOST` / `PORT` | **`0.0.0.0` / `8082`** | Docs say 8000. `.env.example` sets `PORT=8000`, so keep that. Use `127.0.0.1` for safety |
| `MIN_QUEUE_SIZE` | 10 | Generation tops the queue up to this |
| `POSTING_TIMEZONE` | America/Toronto | Used for the posting-window check |
| `AUTORESEARCH_ENABLED` | True | About 72 Claude calls a day |
| `SCREEN_RECORD_ENABLED` | True | Needs `playwright install chromium`; also a security risk (see A11) |
| `APIFY_TOKEN`, `REDDIT_*`, `GEMINI_API_KEY`, `LINKEDIN_PROFILE_URL` | "" | Optional |

**Settings that do nothing** (never read by the code): `POSTS_PER_DAY`, `POSTING_SLOTS`, `POSTING_ACTIVE_DAYS`, `TARGET_NICHE`, `DEFAULT_TONE`, `POST_WORD_MIN/MAX`, `CONTENT_RECYCLING_ENABLED`.

## A10. Database (`database/linkedin_posts.db`)

| Model | What it holds |
|---|---|
| `QueuedPost` | The central table: content, status, template, topic, scores, fact-check, media, schedule, LinkedIn ID |
| `PostPerformance` | Likes, comments, shares, impressions per post |
| `ResearchItem` | Trending topics |
| `TemplateRecord` | Template stats (never updated: the updater is never called) |
| `OAuthToken` | LinkedIn tokens (plain text) |
| `ContentCalendar` | Posting slots (no UI to edit them) |
| `HookEntry` | Hook library |
| `Competitor` / `CompetitorPost` | Tracked competitors and their posts |
| `MyLinkedInPost` | Your scraped posts |
| `LearningInsight` / `AnalysisRun` | Learning system |
| `Experiment` / `ExperimentVariation` | Autoresearch |

Tables are created on start-up, and new columns are added with ad-hoc `ALTER TABLE` (no Alembic; errors are silently ignored).

## A11. Problems found (ranked)

### 🔴 Critical: fix before connecting your real LinkedIn

| # | Problem | Where |
|---|---|---|
| 1 | **No login on the dashboard, and it listens on all network interfaces.** Anyone on your network can publish, delete, spend credits, or rewrite `.env` via `/api/profile/set-url` | `config.py:98`, `app.py:58`, `routes.py` (0 auth dependencies) |
| 2 | **Approval bypasses:** Post Now publishes QUEUED posts; Unschedule turns QUEUED into APPROVED | `poster.py:253`, `post_queue.py:131` |
| 3 | **No CSRF protection:** any website could trigger `/api/post-now/{id}` from your browser | `routes.py:352` |
| 4 | **Timezone bug:** the browser sends local time, the server compares it with UTC, so posts fire 4–5 h early | `poster.py:267`, `schedule.html:376` |
| 5 | **Several posts per slot, or one every 5 min when 5+ are approved;** no daily cap | `poster.py:316, 340` |
| 6 | **`soul.md` is empty placeholders,** while the code hard-codes an e-commerce/supplement agency persona | `soul/soul.md`, `prompt_builder.py:136,176,404`, `content_strategy.py:37` |
| 7 | **Made-up first-person claims:** templates say "I've audited 40+ supplement brands", "7-figure supplement brand" and so on, and the fact-check can't block them | `content/templates/*.json` |
| 8 | **Server fetches any URL:** the screen-record GIF sends a user-given URL to a headless browser (localhost and file:// allowed) | `routes.py:754`, `gif_generator.py:428` |
| 9 | **XSS:** scraped or AI text is inserted with `innerHTML` in several pages; with #1 this could publish posts | `research.html`, `competitors.html`, `queue.html`… |

### 🟠 High: the system works, but gives wrong results

- Real engagement is never fetched on a schedule, and the fake "sample data" button pollutes learning (`routes.py:1182`).
- The autoresearch calibration compares different scales; template experiments don't vary; it burns about 72 Claude calls a day.
- The tone-learning regex also captures the next line (e.g. `"authoritative\nANGLE"`) (`pattern_analyzer.py:655`).
- Template insights have no effect, because a missing `ratio` key means they are read as 1.0.
- Research items are marked "used" even when generation fails. The research route never passes research into the prompt (`routes.py:2451`).
- When media fails, the post goes out text-only but the app reports success. FAILED posts can't be seen or retried.
- A blank line between every sentence at 150–250 words often exceeds the 25-newline cap, so the formatter cuts posts.
- Synchronous Claude, Apify and research calls inside async handlers freeze the dashboard and the posting job while they run.
- Failed Apify scrapes are marked "success", and the first 100-post backfill is lost.

### 🟡 Medium: docs vs code, and dead code

- **Port:** the docs say 8000, the code says 8082.
- **Posting interval:** the docs say 15 min, the code runs every 5.
- **Learning threshold:** `CLAUDE.md` says 10 posts, the code uses 5.
- **Templates:** the docs say 7, there are 19.
- **Settings page:** its scheduler summary is hard-coded and out of date.
- **Placeholder content:** `content/TOPIC_SUGGESTIONS.md` and the "Past Posts" section of `soul.md` say they "auto-populate"; nothing writes to them.
- **Unused code:** `build_newsjack_prompt`, most of `existing_tool/` (RewriteGenerator, TemplateExtractor.extract, sample_posts.json), and the DRAFT status.
- **Out-of-scope legal and ToS risks:**
  - Scraping LinkedIn through Apify breaks LinkedIn's User Agreement, and storing other people's data raises PIPEDA/GDPR questions.
  - pytrends and the DuckDuckGo scraping break those services' terms.

## A12. How to run it locally (once the critical items are handled)

```bash
cd "/Users/promarketer/Development /LinkedIn"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only if SCREEN_RECORD_ENABLED stays True
cp .env.example .env                 # then fill in the keys below
```

1. **Fill `.env`:**
   - `ANTHROPIC_API_KEY`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`
   - keep `PORT=8000`, and set `HOST=127.0.0.1`
2. **Set up the LinkedIn developer app:**
   - Add redirect `http://localhost:8000/auth/callback`.
   - Enable "Sign In with LinkedIn (OpenID Connect)" and "Share on LinkedIn".
3. **Fill in `soul/soul.md` completely.** Restart after editing, because it is only read at start-up.
4. **Start and connect:**
   - Run `python app.py` from the repo root, then open http://localhost:8000.
   - In **Settings**, click Connect LinkedIn.
   - Click **Generate Posts**, review them, then Approve.

---

# PART B: linkedin-skills (Serge Bulaev)

## B1. What it is

- **11 Markdown "skills"** plus a small Python library (`lib/`).
- Claude Code, Codex and claude.ai load a skill automatically when you ask about LinkedIn.
- There is no server, database or scheduler. Each skill runs when you ask, inside a chat.

**The core pattern in every skill:**
```
Input (topic or LinkedIn URL) → Draft (formulas + your voice profile) → Humanizer pass → Approval card → you say "yes" → Publish
```

**Publishing tiers** (`lib/backend_selector.py`):

| Tier | Setup | What happens on "yes" |
|---|---|---|
| 0 Manual (default) | nothing | Shows the text to copy and paste, plus a Publora sign-up message |
| 1 Publora | `PUBLORA_API_KEY` + `LINKEDIN_PLATFORM_ID` | Posts via the Publora API (free plan: 15 posts/month) |
| 2 DIY | `LINKEDIN_SKILLS_CUSTOM_POSTER` | Runs your own command with the draft as JSON (this is code execution) |

**Optional services:**
- **Apify** (`APIFY_TOKEN`) reads post text, comments, your recent comments and likers.
- **Pixfaro** (`PIXFARO_TOKEN`) makes images and quote cards. Its default model costs about $0.08 per image.

## B2. The 11 skills

| Skill | Use it for | Key rules | Reads (Apify) | Publishes |
|---|---|---|---|---|
| **post-writer** | New posts from 20 hook formulas, picked by goal | Hook in the first 210 chars; never open with a question; number-first; 900–1,300 chars; 0–2 hashtags; links in the first comment; suggested window Tue–Thu 7:30–9:00 | — | post |
| **humanizer** | Remove AI tells; `--mode audit` (pass/fail); `--mode profile` (learn your voice) | 4 passes (B3) | optional | — |
| **repurposer** | Tweet, thread, video, blog or newsletter → LinkedIn post | Extract the "spine", re-hook, expand, no platform leftovers | — | post |
| **hook-extractor** | Viral post URL → which formula plus a blank template | Scores hook, body and close features (rules only cover F1–F10) | post | — |
| **comment-drafter** | Comment on someone's post, or repost with your thoughts | 200–350 chars; templates T1–T7; never name your own product; react first | post + comments | comment, reaction, reshare |
| **reply-handler** | Reply to one comment, or sweep the whole thread | 150–300 chars; R1–R5; **`parentComment` = the top-level comment** (LinkedIn flattens to 2 levels); filters low-value comments; one batch approval; post one at a time | comments | reply, reaction |
| **thread-monitor** | Which of your comments got author replies | Hot / warm / cool / dormant windows (6–24 h is the sweet spot); DM after 72 h | your comments | — |
| **engager-analytics** | Who liked or commented, segmented by ICP (peer / aspirational / prospect) | Follow-back, comment and DM lists | likers | — |
| **content-planner** | 7-day plan | 3–5 posts/week; no pillar above 60%; pillars 40 Authority / 30 Narrative / 20 Community / 10 Product; founder pillar set | — | — |
| **profile-optimizer** | Headline, About, Featured, banner, Experience | 9-part scorecard; About in 7 steps; banner 1584×396 | (can't actually fetch a profile) | — |
| **employee-advocacy** | Team posting program | 14-day launch; review tiers A/B/C; cadence by role | — | via reshare |

## B3. The humanizer (the most valuable part)

Four passes, applied **per paragraph with density scoring**:
- 3 or more AI markers in a paragraph → rewrite it.
- 2 → replace the weakest.
- 1 → leave it (except reveal bridges and leaked model text, which always go).

**Pass 1, SCRUB.**
- **Forensic tier:** leaked tool tokens (`oaicite`…), "As of my last update…", `[Your Name]` placeholders, too many em dashes (cap = max(1, min(2, words/100))), and "In conclusion" closers.
- **Strict tier (default):**
  - Durable 2026 vocabulary, with replacements: significant, crucial, notably, particularly, comprehensive, insights, robust, leverage→use, foster→build, landscape→field, nuanced, multifaceted, holistic, streamline→simplify, elevate→improve, empower. Also utilize, facilitate, harness, unlock, navigate, seamless, ecosystem.
  - The "LinkedIn layer": quietly, "X matters", compound, signal, the work, load-bearing, "let that sink in".
  - Reveal bridges: "The result?" (−4.8%), "It's not X, it's Y" (−4.9%), "Stop X, start Y" (−6.7%), "Here's what/how" (−4.3%).
  - Negative parallelism (7 forms), hollow triads, and clichés ("In today's fast-paced world", game-changer, deep dive).
  - Bad closers: "What do you think?", "Thoughts?", "Agree or disagree?", "Tag someone".
- **Aesthetic tier (opt-in):** delve, tapestry, realm, journey, cultivate, showcase, and passive voice.

**Pass 2, RHYTHM.** Fix flat rhythm, but **never manufacture variance**. Banned: "Short. Punchy. Done.", "No X. No Y. Just Z.", one-word paragraphs, and more than 2 fragments per post.

**Pass 3, ADD.** Needs:
- an odd-precision number *with a referent* ("$4,730 in Vercel overages, March invoice")
- a named entity
- a sensory detail
- one flat, dated, uncomfortable fact

It never invents facts, and never adds "let me be honest" or hedges.

**Pass 4, SELF-CHECK.** Did the edit create new tells, or flatten the voice? If so, dial back.

**Audit mode:**
- **Blockers:** em-dash overuse, a link in the body, more than 3,000 chars, a bad opener or closer, a paragraph with 3+ markers, framing LinkedIn as inferior.
- About 20 warnings: hook beyond 210 chars, length, no specifics, triads, hashtags above 2…

Serge says honestly that this is **not** a way to beat AI detectors. It targets human readers and LinkedIn's slop filter.

## B4. Hook formulas and founder angles (`references/hook-formulas.md`)

| Goal | Best formulas |
|---|---|
| Comments | F17 Controlled A/B, F10 Contrarian + Receipts, F4 Time-Anchor Confession*, F12 Permission Slip*, F9 Curiosity Gap* |
| Reposts | F14 Named Gratitude, F2 R.I.P. Obituary, F8 Paid-vs-Free Reversal |
| Likes | F11 Emotional Cold-Open, F13 Bait-and-Switch, F16 Status-Strip Humility |
| Saves | F15 Explain-to-Kids, F7 Odd-Precision Money Ledger (strongest 2026 opener), F8 |

\* = "use with care" in 2026.

The rest: F1 Platform Risk Anaphora, F3 Year-over-Year Pivot, F5 Self-Proving Meta, F6 Comment-Gate (demoted, because LinkedIn now targets it), F18 False-Binary, F19 Anecdote-Meets-Evidence, F20 Diverging Curves.

**Founder angles A1–A10:** Reprice the Category, Content Became Pipeline, Audience of One, Scarce-Shots Math, Unglamorous Bet, Limit of Delegation, Designed Serendipity, Evasive-Sentence Test, Delegation Line, Learning Gate.

**2026 "density rule":** one contrast, one triple, zero reveal bridges, zero questions before the close.

## B5. Algorithm numbers it uses (treat as directional)

- **Timing:** Tue–Thu 7:30–9:00 audience-local. Avoid Friday after 2 PM and weekends.
- **Hook cutoff:** about 210 chars on desktop. Mobile is given as 140, 210 or 265 in different files.
- **Length:** 1,000+ chars give a 1.18× reach lift; 20+ sentences give 1.14×.
- **Links:** a link in the body cuts reach by 40–60%; put it in the first comment.
- **Hashtags:** 0–2 at the end.
- **Engagement weights:** a save ≈ 5× a like, a long comment ≈ 3× a like. Reply to comments within 60–90 min.
- **Reach risks:** pods and automation patterns are penalised. Editing in the first 3 hours triggers re-evaluation.
- **Where the numbers come from:** most are **vendor data** (MagicPost, AuthoredUp, Co.Actor) or internal, unpublished corpora. Several papers and "2026 LinkedIn updates" it cites could not be verified.

## B6. Issues in linkedin-skills

- **Approval is a convention, not code.** `lib/approval.py` only formats the card, and `scripts/schedule_post.py` posts with **no confirmation**.
- **Publora quirks:**
  - `publish("post")` without `scheduled_time` only creates a *draft* in Publora.
  - POSTs are retried on timeouts and 429 responses, which can **double-post**.
- **Reactions and caching bugs:**
  - Replies react on the top-level comment instead of the one you answered.
  - Reaction errors are silently swallowed.
  - The Apify cache never works through the main wrapper, which creates a new client on every call.
  - `canShare` is always `None`, so the "resharing disabled" check never fires.
- **Documents contradict each other:** the hook cutoff, the thread-monitor stage definitions, the review SLA, and the founder templates, which still contain tells the humanizer bans.
- **Commercial nudges:** a Publora sign-up message on every manual approval (the code says this is meant to "convert to a registration"), Pixfaro prompts, and an instruction to ask you for a GitHub star.
- **Legal and ToS:** cookie-less Apify LinkedIn scraping, and DM lists built from strangers' profiles (GDPR/PIPEDA). Some guidance is framed as making automation "look human".

---

# PART C: How the two projects compare and fit together

| | Your Content Engine | linkedin-skills |
|---|---|---|
| Type | Always-on app with a dashboard | On-demand chat skills |
| Brand voice | `soul/soul.md` (empty) | `references/voice-profile.md` (empty) |
| Writing guidance | 19 templates + `VIRALITY_RULES` | 20 hook formulas + 10 founder angles + 2026 rules |
| Quality control | Fact-check + virality score (advisory) | Humanizer (4 passes) + audit blockers |
| Topic research | Trends, Reddit, RSS, competitors | none |
| Learning from results | Yes (needs real data) | none |
| Publishing | Official LinkedIn API (your own app) | Publora / copy-paste |
| Comments and replies | Draft-only comment helper | Full comment, reply and thread-sweep skills |
| Approval | Dashboard (with bypasses) | Chat "yes" (convention) |

**Where they disagree.** Serge's data says these parts of your engine hurt reach:

| Your engine | Serge's rule |
|---|---|
| Myth Buster opens "Stop X. Seriously." | "Stop X" openers: −6.7% |
| Contrarian Take ends "Agree or disagree?" (and `soul.md` itself bans "Agree?") | Banned closer |
| Slippery Slide "One word. That's all it took." | Staccato fragments are the #1 2026 tell |
| Autoresearch tests a "question" opening hook | Question as line 1: −34% |
| No em-dash or AI-vocabulary control | Density scrubbing, em-dash cap |
| Heuristic rewards "I/my/we" first word | Prefers a number-first first line (+34%) |

**Where they already agree:** a text-first format, a closing question, no body links, few or no hashtags, and short paragraphs with blank lines.

**What to bring from Serge into your engine:**
1. **Humanizer scrub:** a new `content/humanizer.py` step after Claude writes and before formatting. Port the forensic and strict regex lists (deterministic, no extra Claude call).
2. **Hook rules:** add them to `VIRALITY_RULES`. Never open with a question; prefer a number first; ban "Here's what/how", "Stop X, start Y", "The result?" and "It's not X, it's Y"; one contrast and one triple.
3. **Audit blockers:** add them to `validate_post_content` or the virality scorer so bad drafts are flagged in the queue.
4. **Hook formulas F1–F20:** add them as new templates. Fix or retire the templates that conflict (the table above).
5. **Voice profile fields:** merge them into `soul.md` (fingerprint, never-use words, signature lines).
6. **Untrusted-content rule:** scraped competitor, Reddit and news text is data, never instructions. Put it in every prompt that includes scraped text.
7. **Reply threading and filtering:** use these if you later extend `comment_helper.py` to replies.

---

# PART D: Recommended next steps (in order)

1. **Make it safe.**
   - Set `HOST=127.0.0.1`.
   - Make Post Now require APPROVED, and make Unschedule keep the original status.
   - Fix the timezone comparison.
   - Add a daily post cap.
   - Remove or guard the sample-data button.
2. **Make it yours.**
   - Fill in `soul/soul.md`.
   - Move the hard-coded "supplement / e-commerce agency" text into config or `soul.md`.
   - Delete the made-up first-person claims in the JSON templates.
3. **Set up and run it.** Follow A12 with your keys; test with Generate → review → **don't approve yet**.
4. **Improve writing quality.** Port Serge's humanizer and hook rules (Part C).
5. **Fix the learning loop.**
   - Schedule the engagement fetch and verify the LinkedIn response fields.
   - Pause autoresearch until there are real posts (saves about 72 Claude calls a day).
6. **Update the model.** Change `CLAUDE_MODEL` from the older `claude-sonnet-4-20250514` snapshot to a current model.

---

## Appendix: key files to open first

| To change… | Open |
|---|---|
| Brand voice | `soul/soul.md` |
| Writing rules sent to Claude | `content/prompt_builder.py` (`VIRALITY_RULES`, lines 39–81) |
| Templates | `content/templates/template_library.py`, `content/templates/*.json` |
| Topic mix and weights | `content/content_strategy.py` (lines 21–76) |
| Formatting limits | `content/post_formatter.py` |
| Scoring | `content/virality_scorer.py` |
| When posts go out | `linkedin/poster.py`, `post_queue/scheduler.py`, `database/engine.py` (calendar seed) |
| Settings | `config.py`, `.env` |
| Serge's writing rules | `linkedin-skills/skills/linkedin-humanizer/references/scrub-rules.md`, `linkedin-skills/references/hook-formulas.md` |
