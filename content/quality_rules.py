"""LinkedIn quality rules as data.

Ported from linkedin-skills by Serge Bulaev (MIT, see knowledge/LICENSE):
skills/linkedin-humanizer/references/scrub-rules.md, audit-ai-tells.md and
sub-skills/post-audit.md. The evidence behind each rule is in those files;
many reach numbers are vendor data and should be read as directional.
"""

from dataclasses import dataclass

POST, COMMENT, REPLY = "post", "comment", "reply"
ALL_KINDS = (POST, COMMENT, REPLY)

# ── Density markers (counted per paragraph: 3+ = rewrite, 2 = replace one) ──
DENSITY = {
    "AI vocabulary": r"(?i)\b(?:leverag|utiliz|facilitat|streamlin|delv|navigat|unlock|harness|foster|cultivat|elevat|empower)(?:e|es|ed|ing|s)?\b",
    "AI vocabulary (2026)": r"(?i)\b(?:significant(?:ly)?|crucial(?:ly)?|notably|particularly|comprehensive|insights?|robust|landscape|nuanced|multifaceted|holistic|seamless(?:ly)?|ecosystem)\b",
    "filler adverb": r"(?i)\b(?:fundamentally|essentially|ultimately|arguably|certainly|definitely|undoubtedly)\b",
    "-ing clause opener": r"(?m)^[\s>*\-]*[A-Z][a-z]+ing\b[^.\n]{0,60},",
    "nominalisation": r"(?i)\bthe \w+(?:tion|sion|ment|ance|ence|ization|isation) of\b",
    "LinkedIn cliché word": r"(?i)\b(?:quietly|compound(?:s|ing)?|(?:a|the) signal|the work|built different|load-bearing|doing the heavy lifting)\b",
    "“X matters.” line": r"(?im)^\w+ matters\.$",
    "dated AI word": r"(?i)\b(?:delve|delving|tapestry|realm|intricate|journey|paradigm)\b",
}

FORENSIC = (
    r"\boaicite\b|\bcontentReference\b|\bturn\d+search\d+\b|\battached_file\b|\bgrok_card\b|\boai_citation\b"
    r"|(?i:as of my (?:last update|knowledge cutoff|training cutoff))"
    r"|(?i:my (?:knowledge|training data) (?:cuts off|extends to))"
    r"|(?i:\bas an ai (?:language )?model\b)"
)

PLACEHOLDER = r"\[(?:[A-Z][A-Z0-9_ ]{2,}|Your [^\]]{1,40}|Insert [^\]]{1,40}|Describe [^\]]{1,40})\]|\{[a-z_ ]{3,30}\}|202\d-XX-XX"

SINCERITY_OPENER = (
    r"(?i)^[\s\-*]*(?:let me be (?:honest|real|direct|clear)|i'?ll be (?:honest|real|direct)|honestly\?|"
    r"to be (?:direct|honest|transparent)|real talk|full transparency|can i be (?:honest|vulnerable)|"
    r"not gonna lie|unpopular opinion)\b"
)
SINCERITY_ANY = (
    r"(?im)(?:^|[.!?]\s+)(?:let me be (?:honest|real|direct)|i'?ll be (?:honest|real)|honestly\?|real talk|"
    r"not gonna lie|unpopular opinion)\b|\bi (?:might|may|could) be wrong,? but\b|\bin my humble opinion\b|"
    r"\bi think it'?s fair to say\b"
)

# Words that make a rule-of-three "hollow" (interchangeable, no receipt).
HOLLOW_WORDS = {
    "dynamic", "vibrant", "innovative", "faster", "cheaper", "better", "simple", "effective", "easy", "bold",
    "clear", "focused", "scalable", "powerful", "growth", "impact", "value", "alignment", "innovation",
    "efficiency", "results", "success", "clarity", "freedom", "scale", "momentum", "consistency", "mindset",
    "strategy", "vision",
}

GENERIC_CLOSERS = r"(?i)(?:what do you think\??|what are your thoughts\??|^thoughts\?|agree or disagree\??|^agree\?|let me know in the comments|tag someone|let that sink in\.?|that'?s the real story\.?)\W*$"


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str  # "blocker" | "warning"
    pattern: str
    message: str
    fix: str
    scope: str = "anywhere"  # anywhere | opener | closer
    kinds: tuple = ALL_KINDS


RULES: list[Rule] = [
    Rule("forensic_leak", "blocker", FORENSIC, "Leftover AI tool text", "Delete it."),
    Rule("placeholder", "blocker", PLACEHOLDER, "Unfilled template placeholder",
         "Replace it with a real detail, or delete the line."),
    Rule("body_link", "blocker", r"(?i)\bhttps?://\S+|\bwww\.\S+\.\S+",
         "Link in the post body (LinkedIn cuts reach 40–60%)", "Move the link to the first comment.", kinds=(POST,)),
    Rule("question_opener", "blocker", r"\?\s*$",
         "Opens with a question (question hooks get about a third fewer likes)",
         "Open with the number or fact that answers it; move the question to the end.", "opener", (POST,)),
    Rule("cliche_opener", "blocker",
         r"(?i)^[\s\"'“]*(?:in today'?s|have you ever|most people don'?t realize|here'?s a hard truth|let me tell you about|here'?s (?:what|how|why)\b)",
         "Cliché opener", "Start with the specific fact or moment instead.", "opener", (POST,)),
    Rule("stop_start_opener", "blocker", r"(?i)^[\s\"'“]*(?:stop|quit) \w+",
         "“Stop X…” opener (generic-advice frame, −6.7% reach)", "Open with what you saw happen, with a number.",
         "opener", (POST,)),
    Rule("announcement_opener", "blocker",
         r"(?i)^[\s\"'“]*(?:(?:i'?m|we'?re|i am|we are) (?:so |very )?(?:excited|thrilled|delighted|honou?red|proud|happy) to|(?:excited|thrilled|honou?red|delighted) to (?:announce|share|be))",
         "Announcement opener reads like a press release", "Start with the concrete moment that prompted the post.",
         "opener"),
    Rule("sincerity_opener", "blocker", SINCERITY_OPENER, "Sincerity announcement (“Let me be honest”)",
         "Delete it and state the fact plainly.", "opener"),
    Rule("all_caps_opener", "blocker", r"^[^a-z]*[A-Z]{3,}[^a-z]*$", "All-caps first line", "Write the first line in sentence case.",
         "opener", (POST,)),
    Rule("generic_praise", "blocker",
         r"(?i)^[\s\"'“]*(?:great (?:post|point|share|insight)|love this|so true|well said|100%|this\.|couldn'?t agree more|thanks for sharing)\b",
         "Generic praise", "React to one specific point and add something new.", "opener", (COMMENT, REPLY)),
    Rule("generic_closer", "blocker", GENERIC_CLOSERS, "Generic closing line",
         "End with a specific question readers can answer from their own experience.", "closer"),
    Rule("reveal_bridge", "blocker",
         r"(?im)^(?:the (?:result|outcome|answer|lesson|catch|kicker|truth|secret|difference|pattern|twist|biggest surprise)\?|plot twist:|spoiler:)",
         "Reveal bridge (“The result?”), about −5% reach", "Delete the bridge and let the next sentence make the point."),
    Rule("neg_parallel", "blocker",
         r"(?i)\b(?:it'?s|this|that) (?:is )?not (?:just |only |about )?[^,.\n;?!]{1,40}[,;] (?:it'?s|but|this is|they'?re)\b"
         r"|\bisn'?t (?:just |about )?[^,.\n;?!]{1,40}[,.;] (?:it'?s|this is|they'?re)\b",
         "“It’s not X, it’s Y” framing (about −5% reach)", "Say what it is, directly, in one sentence."),
    Rule("engagement_bait", "blocker",
         r"(?i)\bcomment ['\"“]?\w+['\"”]? (?:below |and |to )|\bdrop an? (?:['\"“]?\w+['\"”]?|emoji|🙌|👇)(?: below)?\b|\b(?:repost|like|share) (?:this )?if you agree\b",
         "Engagement bait (LinkedIn demotes it)", "Ask a genuine, specific question instead.", kinds=(POST,)),
    Rule("heres_bridge", "warning", r"(?im)^here'?s (?:what|how|why|the thing|exactly)\b",
         "“Here’s what / how…” bridge", "Delete it or state the point directly."),
    Rule("staccato", "warning", r"(?m)^(?:\w+[.!] ){2,}\w+[.!]$", "Staccato fragment run (“Short. Punchy. Done.”)",
         "Merge them into one full sentence."),
    Rule("no_no_just", "warning", r"(?i)\bno \w+[.,] no \w+[.,] (?:just|only) \w+", "“No X. No Y. Just Z.” construction",
         "Rewrite it as a normal sentence."),
    Rule("one_word_paragraph", "warning", r"(?m)^\w+[.!]$", "One-word paragraph", "Fold it into the sentence next to it."),
    Rule("pseudo_socratic", "warning", r"(?i)\b(?:why|how|so how do you fix it)\? (?:because|simple|easy|here'?s)\b",
         "Question-and-answer to yourself (“Why? Because…”)", "State the reason directly."),
    Rule("sincerity_mid", "warning", SINCERITY_ANY, "Hedge or sincerity marker", "Delete it; keep the fact."),
    Rule("follow_cta", "warning", r"(?i)\bfollow (?:me )?for more\b", "“Follow for more” call to action",
         "End with a specific question instead.", kinds=(POST,)),
    Rule("cliche_phrase", "warning",
         r"(?i)\b(?:in today'?s fast-paced world|at the end of the day|game[- ]changer|deep dive|move the needle|needle-moving|paradigm shift|in the age of ai|the (?:harsh|hard|uncomfortable) (?:truth|reality) is)\b",
         "Cliché phrase", "Replace it with the specific thing you mean."),
]

# Target lengths (characters) per kind: (min_ok, sweet_low, sweet_high, max_ok)
LENGTHS = {
    POST: (600, 900, 1500, 2000),
    COMMENT: (120, 200, 350, 600),
    REPLY: (80, 150, 300, 500),
}
HARD_LIMITS = {POST: 3000, COMMENT: 1250, REPLY: 1250}
MAX_NEWLINES = 25
WARN_NEWLINES = 22
