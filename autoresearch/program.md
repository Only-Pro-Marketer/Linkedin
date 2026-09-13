# LinkedIn Post Autoresearch Program

> Inspired by Karpathy's autoresearch. This file guides the autonomous experiment loop.
> **You (the human) edit this file to steer research direction.**
> The runner reads hypotheses from here and appends results below.

## Objective

Maximize engagement (likes + comments*3 + shares*5) on LinkedIn posts by autonomously testing generation parameters and learning what works.

## Proxy Metric

Virality score (1-100) from virality_scorer.py. Fast feedback (~10 sec per variation). Calibrated against real engagement data as it arrives.

## Parameter Space

- **hook_style**: question, contrarian, bold_statement, story_opener, statistic, personal_failure
- **tone**: authoritative, conversational, provocative, vulnerable, data-driven
- **template**: The Expensive Lesson, The Contrarian Take, The Origin Story, The Framework Post, The Myth Buster, The Data Drop, The Quick Tips
- **word_count_target**: 150, 180, 200, 220, 250
- **angle**: personal_story, data_insight, contrarian_take, how_to, case_study, myth_buster, newsjack

## Experiment Rules

- Generate 3-5 variations per experiment (configured via AUTORESEARCH_VARIATIONS_PER_EXPERIMENT)
- Vary only ONE dimension at a time (controlled experiment)
- Minimum virality score to queue the winner: 55 (configured via AUTORESEARCH_MIN_SCORE_TO_QUEUE)
- Log ALL variations (winners and losers) — we learn from both
- Run up to 3 experiments per cycle (configured via AUTORESEARCH_EXPERIMENTS_PER_CYCLE)

## Current Hypotheses

1. Question hooks outperform bold statement hooks on certain topics
2. Vulnerable tone outperforms authoritative tone on personal lesson topics
3. 180-200 word posts score higher than 250+ word posts
4. Data-driven angle with The Data Drop template produces the highest scores
5. Contrarian hooks work best with provocative tone

## Completed Experiments

<!-- Auto-populated by runner — do not edit below this line -->
| # | Type | Topic | Winner | Score | Spread | Date |
|---|------|-------|--------|-------|--------|------|
| 7 | hook | Health and Wellness Ecommerce Examples a | statistic | 95 | 6 | 2026-09-13 |
| 8 | tone | How is ecommerce for dietary supplements | authoritative | 85 | 12 | 2026-09-13 |
| 9 | length | Top Health & Wellness DTC Brands in the  | 220 | 88 | 10 | 2026-09-13 |

## Win Rates by Parameter

<!-- Auto-populated by log.py -->

## Calibration Log

<!-- Auto-populated — predicted virality score vs actual engagement -->
| Experiment | Predicted | Actual | Delta | Date |
|------------|-----------|--------|-------|------|
