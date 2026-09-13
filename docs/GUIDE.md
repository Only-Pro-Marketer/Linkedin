# User Guide: LinkedIn Content Engine

This guide explains how to set up the app, use it day to day, and what every page does. For a short overview see the [README](../README.md).

- [1. First-time setup](#1-first-time-setup)
- [2. Your 15-minute daily routine](#2-your-15-minute-daily-routine)
- [3. Every page explained](#3-every-page-explained)
- [4. How publishing works](#4-how-publishing-works)
- [5. How Engage posting works](#5-how-engage-posting-works)
- [6. Images, scraping and optional services](#6-images-scraping-and-optional-services)
- [7. Settings reference](#7-settings-reference)
- [8. Your data and privacy](#8-your-data-and-privacy)
- [9. Troubleshooting](#9-troubleshooting)

---

## 1. First-time setup

### Install

```bash
git clone https://github.com/Only-Pro-Marketer/Linkedin.git
cd Linkedin
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Add your keys to `.env`

Open `.env` in a text editor. **Never paste keys into chats, issues or commits.** The file is gitignored, and a pre-commit check blocks keys from being committed.

| Key | What it's for |
|---|---|
| `ANTHROPIC_API_KEY` | Required. Claude writes and checks everything. Get it at [console.anthropic.com](https://console.anthropic.com/). |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | Needed to publish. See *Connect LinkedIn* below. |
| `KIE_API_KEY` | Optional. Post images through [kie.ai](https://kie.ai/api-key). |
| `APIFY_TOKEN` | Optional. Automatic LinkedIn scraping. See [section 6](#6-images-scraping-and-optional-services). |

### Start the app

```bash
source .venv/bin/activate
python app.py
```

Open **http://localhost:8000**. The **Home** page shows a setup checklist; work through it top to bottom.

### Fill in your Brand Voice (most important)

Open **Brand Voice**. Each section has a hint and an example. Replace every `[bracket]` with your own words; a section turns green when no brackets are left. Until the five core sections are done (Who I Am, What My Business Does, Audience, Voice & Tone, Content Pillars), drafts stay generic and never invent personal facts.

**Shortcut:** open *Learn my voice*, paste 3–6 of your own posts separated by a line of `---`, and click **Analyze my posts**. Claude suggests the Voice & Tone, Voice Fingerprint, Words I Never Use and Signature Lines sections. Signature lines are only kept if they appear word for word in your posts. Tick the sections you like, click **Put checked sections in the editor**, review, then **Save changes**.

The first line of *What My Business Does* is used as your niche everywhere, so make it one clear sentence.

### Connect LinkedIn

1. Go to [linkedin.com/developers](https://www.linkedin.com/developers/apps) and create an app, or use your existing one.
2. Under **Products**, add *Sign In with LinkedIn using OpenID Connect* and *Share on LinkedIn*.
3. Under **Auth**, add the redirect URL `http://localhost:8000/auth/callback`.
4. Copy the Client ID and Primary Client Secret into `.env`, then restart the app.
5. In the app, open **Settings → Connect LinkedIn**, sign in, and click **Allow**.
6. Click **Test connection**. It should say *Working. Connected as …*.

### Check your posting times

In **Settings → Posting times**, add or remove weekly slots. Click a time to pause it. All times are in `POSTING_TIMEZONE`, which defaults to Toronto.

---

## 2. Your 15-minute daily routine

1. **Home.** See what's waiting: drafts to review, the next scheduled post, Engage items that need you, failed posts.
2. **Queue.** Review the best drafts first. Each card shows a quality badge:
   - **Ready**: good to go;
   - **Review**: minor issues;
   - **Needs fixes**: blockers like a question opener, a link in the body, an unfilled `[placeholder]`, or an AI cliché.

   Click **Edit** to see the issues and fix them yourself, or use **Auto-fix** / **Fix with AI**. Then **Approve** or **Schedule**.
3. **Engage.** Comment on 3–5 posts in your niche (*Comment on a post* or *Daily targets*). Answer comments on your latest post (*Reply to comments*).
4. **History.** For yesterday's post, open it and type in LinkedIn's numbers (impressions, reactions, comments, reposts). This is how the app learns what works for you.

Once a week, open **Plan** and plan the next 3–5 posts.

---

## 3. Every page explained

### Home
Your to-do list: the setup checklist, key numbers, the best drafts to review, the next scheduled posts and posting times, an Engage summary, and AI spend for the last 30 days.

### Studio
- **Write:**
  1. Say what the post is about and pick a goal: start a conversation, be worth saving, get shared, or build goodwill.
  2. Studio shortlists hook formulas (F1–F20) that fit the goal. Formulas used in the last 7 days are pushed down.
  3. Add your real facts (numbers, names, dates).
  4. Click **Write draft**. The draft opens in an editor with a live quality check and a LinkedIn preview showing where "…see more" cuts in.
  5. Edit it, then **Save to Queue**.
- **Repurpose:** paste an article, newsletter, podcast transcript or rough notes. Studio finds up to 3 angles and drafts a post for each. With someone else's content it writes from your point of view and never claims their experiences as yours.
- **Hook Lab:** paste any post whose first line stopped you. You get the formula it uses, why it works, reach risks (for example, "opens with a question"), a stronger version, and a reusable template. Save it to your hook library, or jump to Write with the same formula.

### Plan
Choose 3, 4 or 5 posts and an optional focus, then click **Plan my week**. Each item gets a day and time from your posting slots, a pillar, a goal, a formula, a topic and an angle. The app enforces the guardrails in code: no pillar above 60% of the week, and no formula repeated within 7 days. **Draft this** writes the post and puts it in your Queue; nothing is approved automatically. **Skip** or restore items as your week changes.

### Idea Lab
Type a rough idea and get several variations with different tones, formats and structures. Suggest a topic uses your content pillars.

### Queue
All drafts waiting for review. Each card shows its quality badge, predicted reach, fact-check status, word count and line count. Actions:
- **Approve**: asks first if the draft still has blockers.
- **Edit**: the quality panel, LinkedIn preview and fix buttons.
- **Reject** or **Regenerate** with feedback.
- **Gen Image** / **Gen GIF**, or upload your own.
- **Schedule** for a specific time, or **Post Now** (confirmation required).

### Schedule
A calendar of scheduled posts and your posting slots.

### History
Published, approved, rejected and failed posts.
- **Failed** posts show why, and you can retry them.
- Opening a published post lets you **type in its numbers from LinkedIn**. Learnings and Analytics use them.

### Engage
- **Comment on a post:** paste a post link and its text. You get 2–3 comment options (templates T1–T7), each with a quality check, plus a suggested reaction. Edit, then **Approve & post**.
- **Reply to comments:**
  1. Paste comments copied from your post.
  2. The app filters out generic praise, spam, your own comments, and anything that tries to instruct the AI.
  3. It drafts replies (R1–R5). To let the app post a reply for you, put that comment's link (**… → Copy link to comment**) on the line above it.
- **Daily targets:** recent high-engagement posts from the people you track in Competitors.
- **Activity:** scheduled, posted and *needs you* items: copy and post by hand, or check an unconfirmed one.
- **Follow-ups:** comments you posted 6–48 hours ago, worth checking for replies.

### Research, Analytics, Learnings, Competitors, Experiments
- **Research:** trending topics from Google Trends, Reddit, RSS and competitors. Create a post from any item.
- **Analytics:** your posting performance.
- **Learnings:** patterns found in your results, which feed future drafts.
- **Competitors:** track people in your space. Add their posts by hand or scrape them with Apify. The app analyzes hooks and formats.
- **Experiments:** autoresearch results. Experiments only run once `AUTORESEARCH_ENABLED` is on and 10 real posts are published.

### Brand Voice
The guided editor for `soul/soul.md` (see [setup](#fill-in-your-brand-voice-most-important)). Changes apply to the next draft; no restart is needed.

### Profile Optimizer
Paste your headline, About, current role, skills and featured items. You get a 9-part scorecard: headline, About, experience, skills, featured, custom URL, recommendations, banner and photo. It comes with three headline options, a rewritten About and experience bullets. The URL and headline-length checks run in code. Replace any `[bracket]` before pasting anything into LinkedIn.

### Settings
LinkedIn connection and what your permissions allow, **Test connection**, limits and toggles, posting times, your profile URL, AI usage by feature, and the list of background jobs.

---

## 4. How publishing works

- **Only approved posts are published.** Scheduling a post counts as approving it for that time.
- **Automatic publishing** runs every 5 minutes. It publishes the next approved post at your posting times, never more than `POSTS_PER_DAY`, and at least `MIN_HOURS_BETWEEN_POSTS` after the previous one.
- **Post Now** asks for confirmation and still respects the daily cap.
- **Before sending,** the text is formatted for LinkedIn. LinkedIn silently drops text after about 25 line breaks, so the app enforces that limit. After publishing, it reads the post back where the API allows, to check nothing was cut.
- **If a post has a first comment** (for example "Source: https://…"), the app posts it about a minute later. Links belong there, not in the post body.
- **If publishing fails,** the post moves to History → Failed with the reason, and you can retry. Posts interrupted by a crash are marked failed at startup, so nothing is stuck.

## 5. How Engage posting works

- **Approved items post one at a time,** 90–180 seconds apart, under `ENGAGE_DAILY_CAP` a day. The app reacts first, then comments.
- **Replies thread under the top-level comment,** as LinkedIn requires.
- **When LinkedIn says no:**
  - **Refused (403):** everything switches to *Copy + Open post* and a banner explains why. Click *Try the API again* later.
  - **Too many requests (429):** posting pauses and resumes automatically.
  - **No answer:** the item is marked *Check on LinkedIn* and never retried automatically, so nothing posts twice.
- **Automation off:** if background jobs are off or LinkedIn isn't connected, approved items wait for **Post now** or become *Copy + Open*.

## 6. Images, scraping and optional services

- **Post images (kie.ai or Gemini).**
  - **Gen Image** creates a 4:5 image for the post using kie.ai's Nano Banana model (about 4 credits each), or Gemini if only `GEMINI_API_KEY` is set.
  - Images avoid text, invented numbers, logos and real people.
  - You review the image with the post.
- **Scraping (Apify, optional).**
  - With `APIFY_TOKEN` set, the app can import your own posts (daily at 7:00), scrape competitors (daily at 6:00), and fetch a post or its comments in Engage.
  - Costs are about $0.002 per post, $0.01 per profile and $0.005 per comment.
  - Scraping LinkedIn is against LinkedIn's User Agreement, so the risk sits with your account. Everything also works by pasting.
- **Research sources:** Google Trends and RSS work without keys. Reddit needs `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`.

## 7. Settings reference

| Setting | Where | Default | Notes |
|---|---|---|---|
| `POSTS_PER_DAY` | Settings / .env | 1 | Hard cap on every publish path |
| `MIN_HOURS_BETWEEN_POSTS` | Settings / .env | 3 | Automatic publishing only |
| `MIN_QUEUE_SIZE` | Settings / .env | 10 | Automatic drafting pauses when the Queue has this many |
| `ENGAGE_DAILY_CAP` | Settings / .env | 30 | Comments and replies per day |
| `AUTO_REPAIR` | Settings / .env | on | One "Fix with AI" pass on drafts that fail the quality check |
| `FACT_CHECK_ENABLED` | Settings / .env | on | Flags claims that need a source |
| `AUTORESEARCH_ENABLED` | Settings / .env | off | Also needs 10 published posts |
| `SCHEDULER_ENABLED` | .env | true | All background jobs |
| `POSTING_TIMEZONE` | .env | America/Toronto | |
| `CLAUDE_MODEL` | .env | claude-opus-5 | |
| `KIE_IMAGE_MODEL`, `KIE_IMAGE_ASPECT` | .env | google/nano-banana, 4:5 | |
| `HOST`, `PORT` | .env | 127.0.0.1, 8000 | |
| `DASHBOARD_PASSWORD` | .env | empty | Required to listen on a network address |
| `ALLOWED_HOSTS` | .env | empty | Extra host names to answer, e.g. a LAN name |

## 8. Your data and privacy

- **Where things live:**
  - everything runs on your computer;
  - drafts, posts, stats and your LinkedIn login are in `database/linkedin_posts.db`, readable only by your user account;
  - automatic backups are in `database/backups/`;
  - your brand voice is `soul/soul.md`.
- **Keys live in `.env`** and are never committed. Rotate any key that was ever shared, for example in a chat.
- **What leaves your computer:**
  - text goes to Claude (Anthropic) to write and check drafts;
  - posts and comments go to LinkedIn when you approve them;
  - image prompts go to kie.ai or Gemini;
  - scraping requests go to Apify, only if you set it up.
- **Untrusted text is handled safely.** Scraped and pasted content is marked as untrusted in prompts, and all text shown in the dashboard is escaped.

## 9. Troubleshooting

| Problem | What to do |
|---|---|
| "LinkedIn isn't connected" | Settings → Connect LinkedIn, then Test connection. Logins last about 60 days; the app refreshes them when it can. |
| "LinkedIn rejected the saved login" | Click Reconnect in Settings. |
| Scrape Now says it needs an Apify token | Add `APIFY_TOKEN` to `.env` and restart, or paste posts by hand. |
| Gen Image fails | Check `KIE_API_KEY` or `GEMINI_API_KEY`, and your kie.ai credits. The error message says which. |
| Drafts sound generic | Finish Brand Voice (all five core sections green) and add real facts in Studio's notes. |
| A post is stuck in "Failed" | Open History → Failed to see why, fix the cause, and click Retry. |
| An Engage item says "Check on LinkedIn" | Open the post. If your comment is there, click *It posted*; otherwise click *Retry*. |
| Autoresearch won't run | It needs `AUTORESEARCH_ENABLED` on and 10 published posts. |
| The page says "Invalid host header" | Open the app at `http://localhost:8000`, or add your host name to `ALLOWED_HOSTS`. |
| Changes in `.env` don't apply | Restart the app (Ctrl+C, then `python app.py`). |
