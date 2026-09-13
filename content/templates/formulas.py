"""The 20 LinkedIn hook formulas (F1–F20) as structured data.

Adapted from linkedin-skills references/hook-formulas.md by Serge Bulaev
(MIT, see knowledge/LICENSE), with the 2026 reach notes applied to the
skeletons (no "Here's what" bridges, no question openers, one contrast).

`autogen` marks formulas that work without the author's private stories or
numbers, so they are safe for automatic batch generation. The rest need the
author's own facts and are offered in Studio, where the user supplies them.
"""

from dataclasses import dataclass, field

from existing_tool.models import PostTemplate

GOALS = ("comments", "reposts", "likes", "saves")


@dataclass(frozen=True)
class Formula:
    id: str
    name: str
    goals: tuple
    best_for: str
    skeleton: str
    why: str
    caveat: str = ""
    autogen: bool = False
    needs: tuple = field(default_factory=tuple)  # facts the author must supply

    @property
    def label(self) -> str:
        return f"{self.id} {self.name}"

    def as_template(self) -> PostTemplate:
        lines = [l for l in self.skeleton.strip().split("\n")]
        hook = lines[0]
        cta = lines[-1]
        body = "\n".join(lines[1:-1]).strip()
        notes = f"Formula {self.id} — {self.why}"
        if self.caveat:
            notes += f"\n2026 note: {self.caveat}"
        notes += "\nUse only real numbers and facts; if a slot has none, rewrite the line so it does not need one."
        return PostTemplate(name=self.label, hook_pattern=hook, body_pattern=body, cta_pattern=cta,
                            example_post="", fill_instructions=notes)


FORMULAS: list[Formula] = [
    Formula("F1", "Platform Risk Anaphora", ("comments",), "platform or category risk arguments",
            "{Platform 1} can {restrict} you {timing}.\n{Platform 2} can {bad thing} for {reason}.\n"
            "[3–4 more parallel lines, each more specific]\n"
            "You don't own {audience}. You're renting {attention}.\n"
            "[One concrete example with a real number]\n[The real asset, stated as one plain sentence]\n"
            "So I changed how I work:\n- [tactic 1]\n- [tactic 2]\n[Metaphor close]\n"
            "[Question that makes the reader audit their own risk]",
            "Stacked loss aversion; the tactics earn the close.",
            "The repeated lines are the post's one repetition device. Put the example number in line 1 or 2.",
            autogen=True),
    Formula("F2", "R.I.P. Category Obituary", ("reposts",), "an era ending or an industry pivot",
            "R.I.P. {category}.\nCause of death: {specific mechanism with a number}.\n"
            "[2–3 short paragraphs of dated evidence]\n[When you changed your mind, with a date]\n"
            "Under the hood, {N} things changed:\n1. [change with a number]\n2. [change with a number]\n3. [change with a number]\n"
            "The winners now are {new-winner type}.\n[Question about what the reader is replacing]",
            "Status threat plus relief: “I'm behind” becomes “the game changed”.",
            "Dated evidence is what protects it. Use the “winners” contrast once, at the end.",
            autogen=True),
    Formula("F3", "Year-over-Year Pivot", ("comments",), "identity shifts and founder reflection",
            "In {last year}, I {humble benchmark with a number}.\nIn {this year}, I'm {goal with a number}.\n"
            "[The first concrete number of the change]\n[The vulnerable truth, with numbers]\n[The identity reframe]\n"
            "What's your {last year} → {this year} change? One line below.",
            "The two-line hook carries the post; the mirror question multiplies comments.",
            "Number-first by construction. Keep the question at the end.", needs=("two real yearly benchmarks",)),
    Formula("F4", "Time-Anchor Confession", ("comments",), "a real habit you stopped and what it cost",
            "{N} {months} ago, I stopped {behaviour}.\n[First concrete consequence, with a number]\n"
            "[Why the old behaviour used to work, with numbers]\n[The quiet cost]\n[What you do now]\n"
            "[The metric that dropped, and the surprising upside]\n"
            "What's something you stopped doing that made your work better?",
            "A dated, specific admission earns attention; the close invites mini-confessions.",
            "Must be a real, dated fact. Never announce candour (“Let me be honest”).",
            needs=("a real behaviour you stopped and when",)),
    Formula("F5", "Self-Proving Meta", ("comments",), "a public test of your own claim",
            "Most {things} fail in the first {time window}.\n[The real reason, with one metric]\n"
            "For the next {24 hours}, I will {specific commitment}.\nYou can help in two ways:\n1. [low-bar action]\n2. [verification action]\n"
            "If I'm wrong, I'll post the numbers anyway.",
            "Reader action validates the claim; public accountability drives comments.",
            "Actions must be substantive — never “comment YES”.", needs=("a commitment you will actually keep",)),
    Formula("F6", "Named Resource Share", ("saves",), "sharing a real resource you built",
            "[Authority number: what you did, how often, with a number]\n[The pattern that experience taught you]\n"
            "So I turned it into {N named items}:\n- [item 1]\n- [item 2]\n- [item 3]\n"
            "It's in the first comment, free.\n[A real question about the reader's own workflow]",
            "A named, real bundle plus real authority earns saves and DMs.",
            "Comment-gates are demoted in 2026: put the resource in the first comment, never “comment X to get it”.",
            needs=("a real resource that exists today",)),
    Formula("F7", "Odd-Precision Money Ledger", ("saves",), "cost breakdowns and build logs",
            "{Odd, exact amount, e.g. $873.47}\n[What that number covers, one line]\n"
            "Every line item, nothing rounded:\n- {item 1}: ${x.yz}\n- {item 2}: ${x.yz}\n- {item 3}: ${x.yz}\n"
            "[What the total replaces]\n[What surprised you]\nP.S. [one real follow-up]",
            "Unrounded numbers signal real accounting; the ledger gets saved and screenshotted.",
            "The strongest 2026 opener — but only with real numbers.", needs=("a real itemised cost",)),
    Formula("F8", "Paid-vs-Free Reversal", ("reposts", "saves"), "giving away a framework you normally charge for",
            "I charge {audience} ${X} for {service}.\nToday it's free.\n"
            "It's the {N}-step {named framework} I run before taking on a client:\n1. {step} — [instruction]\n2. {step} — [instruction]\n3. {step} — [instruction]\n"
            "Run it today; most people find {N} fixes in 20 minutes.\n[Soft, real offer or a specific question]",
            "Price → free is a pattern interrupt; a named framework signals real expertise.",
            "Each step must be a concrete instruction, not “Stop X, start Y”.", needs=("your real price and framework",)),
    Formula("F9", "Specific Curiosity Gap", ("comments",), "a surprising thing that happened",
            "{Yesterday}, our {system} did something we didn't plan for.\n"
            "[The specific reveal with a number or name — before the “see more” fold]\n[One sensory detail]\n"
            "[What it means for the category]\n[A question about the reader's experience]",
            "An incomplete line 1 pulls the reader in; the fast payoff keeps trust.",
            "Pay off the gap within two lines. Avoid “what nobody tells you” phrasing.", needs=("a real event",)),
    Formula("F10", "Contrarian + Historical Receipts", ("comments",), "sacred cows and hype cycles",
            "{Sacred cow} has been “dying” since {year}.\n{Month Year}: {event}.\n{Month Year}: {event}.\n{Month Year}: {event}.\n"
            "The counterpunch: {hard stat with source}.\nWhat actually changed: {specific subset}, with specifics.\n"
            "What's the boldest “X is dead” prediction you remember?",
            "A dated receipt list holds attention; the question makes people pick a side.",
            "Use one contrast, not two. Receipts must be real, dated events.", autogen=True),
    Formula("F11", "Emotional Cold-Open", ("likes",), "a true story with emotional stakes",
            "{One line dropped into the peak moment of a real story}\n[3–6 short present-tense lines inside the moment]\n"
            "[The turn: what changed, who showed up, what it cost]\n[One line of meaning, not a moral]",
            "Starting at the peak skips the warm-up the feed punishes.",
            "True stories only. No all-caps, no “Plot twist:”.", needs=("a true story",)),
    Formula("F12", "Earned Permission Slip", ("comments",), "encouragement backed by your own record",
            "{Specific, dated fact from your own record}.\n[Why it turned out fine, 2–3 lines]\n"
            "If you're {situation}, you're allowed to {one permission}.\n[A soft question inviting readers to share]",
            "Second-person reassurance makes readers self-identify in comments.",
            "Needs a real dated fact and a single permission. Use sparingly.", needs=("a dated fact from your record",)),
    Formula("F13", "Bait-and-Switch Reversal", ("likes",), "a policy or process change that is an upgrade",
            "No more {specific perk or practice} at {company}.\nWe're also cutting {second thing}.\n"
            "[Beat of suspense]\nWe replaced it with {X}. {Cost or time saved, with a number}.\n[The value underneath the change]",
            "Fake bad news, then the relief of a real upgrade.",
            "The reveal must genuinely be positive; state it plainly with a number.", needs=("a real change you made",)),
    Formula("F14", "Named Gratitude", ("reposts",), "thanking specific people",
            "To {Name} and {Name}: thank you for {specific thing}.\n[What each person actually did, one concrete act each]\n"
            "[Why it mattered]\n[A closing line that honours them, not you]",
            "Naming real people invites them and their networks to amplify it.",
            "One concrete act per person, not three adjectives.", needs=("real people and what they did",)),
    Formula("F15", "Explain-to-Kids Glossary", ("saves",), "demystifying jargon in your field",
            "{Jargon term} explained so a 10-year-old gets it.\n{Part 1} = {plain meaning}\n{Part 2} = {plain meaning}\n"
            "{Part 3} = {plain meaning}\n[One-line “now you won't forget it” close]",
            "A simple, scannable explanation of something dense gets saved as a reference.",
            "Keep it correct; a statement opener, not “What is…?”.", autogen=True),
    Formula("F16", "Status-Strip Humility", ("likes",), "senior voice showing the human side",
            "At work, I'm {title}.\nAt home, none of that survives {the humbling moment}.\n[The specific scene]\n"
            "[What the contrast taught you, 1–2 lines]",
            "Trading prestige for relatability turns authority into warmth.",
            "Needs a real, specific scene; it is the post's one contrast.", needs=("a real humbling moment",)),
    Formula("F17", "Controlled A/B Anecdote", ("comments",), "one variable that flipped an outcome",
            "{Action A} → {outcome A, with a number}.\n{Same action, one thing changed} → {outcome B, with a number}.\n"
            "Same {constant 1}. Same {constant 2}. The only variable was {the one thing}.\n"
            "[What you first thought it meant]\n[What it actually showed]\n[A question that makes readers test their own variable]",
            "A one-variable comparison reads as evidence, not opinion.",
            "Change exactly one variable. The A/B is the post's one contrast.", needs=("a real comparison",)),
    Formula("F18", "False-Binary Dissolve", ("comments", "reposts"), "problems where both obvious answers fail",
            "Most teams pick one of two answers to {problem}.\n{Option A} fails because {one line}.\n{Option B} fails because {one line}.\n"
            "Both miss the same thing: {shared flaw}.\nThe third option: {synthesis}.\n[How it works, 2–3 concrete lines]\n"
            "How do you handle {problem} today?",
            "Killing the two obvious options earns the right to the third.",
            "Make the third option concrete; do not open with “A or B?”.", autogen=True),
    Formula("F19", "Anecdote-Meets-Evidence", ("comments", "saves"), "a personal noticing backed by data",
            "[A small thing you noticed, with a number]\nI thought I'd discovered something. It had been measured already:\n"
            "→ {evidence 1, with a number and source}\n→ {evidence 2, with a number and source}\n→ {evidence 3, with a number and source}\n"
            "[What the pattern really is]\n[What you decided to do]\n[An operational question]",
            "The noticing earns attention; the evidence stack earns belief and saves.",
            "Real, sourced numbers only.", needs=("sourced evidence",)),
    Formula("F20", "Diverging Curves", ("reposts",), "two approaches that diverge over time",
            "{Approach A} and {Approach B} look the same today.\n{Approach A}: {what happens over time}.\n"
            "{Approach B}: {the opposite over time}.\nMonth one, {X}. Month six, {Y}.\n{One-line maxim contrasting the two}",
            "Opposite trajectories on a timeline make an idea feel inevitable; the maxim gets reshared.",
            "Counts as the post's one contrast.", autogen=True),
]

BY_ID = {f.id: f for f in FORMULAS}
BY_LABEL = {f.label: f for f in FORMULAS}


def formulas_for_goal(goal: str) -> list[Formula]:
    return [f for f in FORMULAS if goal in f.goals]


def formula_templates(autogen_only: bool = False) -> list[PostTemplate]:
    return [f.as_template() for f in FORMULAS if f.autogen or not autogen_only]
