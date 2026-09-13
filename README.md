# LinkedIn Content Engine

A local app that researches, writes, checks and publishes LinkedIn posts, and helps you comment and reply, with you approving every word.

Built with FastAPI, the Claude API and the LinkedIn REST API. The writing playbooks in `knowledge/` come from [linkedin-skills](https://github.com/sergebulaev/linkedin-skills) by Serge Bulaev (MIT).

## What's inside

| Area | Page | What it does |
|---|---|---|
| | **Home** | Setup checklist, drafts to review, what's coming up, Engage tasks, AI spend |
| Create | **Studio** | *Write*: goal → proven hook formula (F1–F20) → your facts → draft. *Repurpose*: turn an article, newsletter or transcript into up to 3 posts. *Hook Lab*: see why a hook works and save it as a template |
| | **Plan** | A 3–5 post week across your pillars. No pillar above 60%, no formula twice in 7 days. "Draft this" puts a post in your Queue |
| | **Idea Lab** | Turn a rough idea into several variations |
| Review | **Queue** | Every draft has a quality score. The editor shows AI tells, a LinkedIn preview with the "…see more" fold, and Auto-fix / Fix with AI buttons |
| | **Schedule / History** | Scheduled and published posts, failed posts with retry, and numbers you enter by hand from LinkedIn |
| Engage | **Engage** | Comment on other people's posts (T1–T7 templates), reply to comments on yours (R1–R5), daily targets, follow-ups. Approved comments post through the LinkedIn API one at a time |
| Insights | **Research, Analytics, Learnings, Competitors** | Trending topics and what works for you. Experiments appear once autoresearch is on |
| Setup | **Brand Voice** | A guided editor for `soul/soul.md`. *Learn my voice* suggests voice sections from your own posts |
| | **Profile Optimizer** | A 9-part profile scorecard with headline, About and experience rewrites |
| | **Settings** | LinkedIn connection test, limits and toggles, posting times, AI usage by feature |

## How it keeps you safe

- **Nothing publishes without your approval.** Post now, the scheduler and Engage only publish items you approved.
- **Limits:** `POSTS_PER_DAY` (default 1) on every path, a minimum gap between automatic posts, and `ENGAGE_DAILY_CAP` for comments.
- **One quality gate.** Every new draft goes through the same pipeline: format → safe auto-fixes → AI-tell audit → at most one AI repair → fact-check and reach score.
- **No invented facts.** Drafts only use facts from your Brand Voice and the notes you give. Anything missing becomes a `[placeholder]` that blocks approval until you fill it.
- **Comments are careful.** Approved comments go out 1–3 minutes apart, reacting before commenting. If LinkedIn refuses (403), everything switches to Copy + Open post. If LinkedIn doesn't answer, the item is marked "check on LinkedIn" and never retried automatically, so nothing posts twice.
- **Local by default.** The app listens on 127.0.0.1. It refuses to listen on a network address unless `DASHBOARD_PASSWORD` is set. Cross-site requests are blocked, URL fetches are limited to public hosts, and scraped text is marked as untrusted in every prompt.

## Quick start

```bash
git clone https://github.com/Only-Pro-Marketer/Linkedin.git
cd Linkedin
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add your keys
python app.py
```

Open **http://localhost:8000** and follow the checklist on Home:

1. Add `ANTHROPIC_API_KEY` to `.env`.
2. Fill in **Brand Voice**. This matters most: drafts stay generic until it's done. Paste 3–6 of your posts into *Learn my voice* to get a head start.
3. **Connect LinkedIn** (Settings → Connect).
4. Check your **posting times** in Settings.
5. Write something in **Studio**, review it in the **Queue** and approve it.

| Key | Required | Where to get it |
|-----|----------|-----------------|
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com](https://console.anthropic.com/) |
| `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` | To publish | [linkedin.com/developers](https://www.linkedin.com/developers/): enable *Sign In with LinkedIn using OpenID Connect* and *Share on LinkedIn* |
| `APIFY_TOKEN` | No | Optional scraping (competitors, your own posts, fetching comments). Everything also works by pasting |
| `KIE_API_KEY` | No | [kie.ai](https://kie.ai/api-key) for post images (Nano Banana). Used instead of Gemini when set |
| `REDDIT_CLIENT_ID` / `GEMINI_API_KEY` | No | Extra research source / Gemini images |

## LinkedIn permissions

- `w_member_social` (default): publish posts, comments and reactions.
- `r_member_social` (needs LinkedIn approval): read post stats automatically. Without it, type the numbers into History and Learnings uses them.

Settings shows what your current login allows and has a **Test connection** button.

## Configuration

Secrets live in `.env`. Limits and toggles can also be changed in **Settings**; those are stored in the database and override `.env`.

| Setting | Default | What it does |
|---|---|---|
| `POSTS_PER_DAY` | 1 | Hard cap on publishes per day |
| `MIN_HOURS_BETWEEN_POSTS` | 3 | Gap between automatic publishes |
| `ENGAGE_DAILY_CAP` | 30 | Comments and replies per day |
| `SCHEDULER_ENABLED` | true | Background jobs on or off |
| `AUTO_REPAIR` | true | One "Fix with AI" pass on drafts that fail the quality check |
| `FACT_CHECK_ENABLED` | true | Fact-check new drafts |
| `AUTORESEARCH_ENABLED` | false | Claude-scored experiments (idle until 10 real posts) |
| `CLAUDE_MODEL` | claude-opus-5 | Model for every Claude call |
| `POSTING_TIMEZONE` | America/Toronto | All schedule times use this zone |
| `HOST` / `DASHBOARD_PASSWORD` | 127.0.0.1 / empty | Set a password before exposing the app to a network |

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use a temporary database and a fake Claude, so they don't need keys or a network. See `CLAUDE.md` for the architecture and the rules the code relies on.

## Architecture

```
app.py                     FastAPI app: middleware, routers, startup recovery
config.py / app_settings.py  .env settings / values edited in Settings
llm.py                     The only place that calls Claude (caching, refusals, usage log)
knowledge/                 Vendored playbooks from linkedin-skills (MIT) + loader
soul/soul.md               Your brand voice
content/                   brand, prompt_builder, pipeline (quality gate), humanizer + quality_rules,
                           ai_fix, review (fact-check + reach score), generator, templates/formulas (F1–F20)
studio/                    writer, repurposer, hook_lab, planner, voice, profile
engagement/                comment_drafter, reply_handler, publisher (paced API posting), followups
linkedin/                  api_client (posts, comments, reactions), poster (approval gate + limits), url_parser
post_queue/                queue state, scheduler jobs, calendar slots
research/ analytics/ autoresearch/   research sources, learning loop, experiments
dashboard/                 routers/ (home, studio, plan, engage, brand, profile, settings, quality, stats),
                           routes.py (older pages), templates/, static/js (app.js, post-editor.js)
database/                  models, engine (SQLite WAL), migrations (versioned, backed up)
tests/                     pytest suite
```

Post status flow: `QUEUED → APPROVED → (SCHEDULED) → POSTING → POSTED`, or `REJECTED` / `FAILED` (with retry).

## License

MIT, see [LICENSE](LICENSE). `knowledge/` is adapted from linkedin-skills by Serge Bulaev (MIT, see `knowledge/LICENSE`).
