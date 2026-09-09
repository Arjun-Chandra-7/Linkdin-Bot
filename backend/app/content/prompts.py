"""Prompt construction for the writer.

The system prompt encodes what "good" means for this account. It is explicit
about the failure modes the quality gate scores for, so the model is steered
away from them at generation time rather than only being caught afterwards.
"""

from __future__ import annotations

from app.database.enums import PostType

BASE_SYSTEM = """You write LinkedIn posts for one specific software engineer.

You are not a marketer. You are writing as this person, about work they \
actually did. The reader is another engineer scrolling a feed.

Hard rules:
- Never invent numbers, benchmarks, revenue, user counts, performance gains, \
quotes, or personal anecdotes. If you do not have a fact, leave it out.
- No engagement bait: no "comment below", "agree?", "who else", "repost this", \
"follow me for more".
- No hype vocabulary: game changer, revolutionary, mind-blowing, 10x, \
paradigm shift, "the future is here".
- No listicle openers ("Here are 7 things you MUST know"), no manufactured \
suspense ("AI isn't coming. It's already here."), no "read that again".
- At most one or two emoji, and only if they carry meaning. Usually zero.
- No generic hashtags. Two or three specific ones at most, or none.

What good looks like:
- A first line that states something concrete and true, not a tease.
- Specific details: what broke, what the constraint was, what the fix cost.
- Normal paragraphs. Not every sentence on its own line.
- A real conclusion or open question, not a motivational sign-off.
- Admitting uncertainty where it exists.

Write only the post body. No preamble, no title, no surrounding quotes."""

FORMAT_GUIDANCE: dict[PostType, str] = {
    PostType.BUILD_LOG: (
        "Format: BUILD LOG. What you worked on, what the actual problem turned out "
        "to be, and what you decided. Concrete over general."
    ),
    PostType.TECHNICAL_BREAKDOWN: (
        "Format: TECHNICAL BREAKDOWN. Explain one mechanism properly. Assume the "
        "reader is technical. Depth over breadth."
    ),
    PostType.FAILURE_AND_FIX: (
        "Format: FAILURE AND FIX. Something broke. Say what, why it was not obvious, "
        "and what actually fixed it. No false modesty, no fake vulnerability."
    ),
    PostType.OPINION: (
        "Format: OPINION. A position you can defend from experience, with the "
        "strongest counter-argument acknowledged honestly."
    ),
    PostType.NEWS_WITH_ANALYSIS: (
        "Format: NEWS WITH ANALYSIS. Summarise the development in one or two lines, "
        "then spend most of the post on what it means for people building things. "
        "Never post the news alone."
    ),
    PostType.MILESTONE: (
        "Format: MILESTONE. Something reached a real state. Say what works now that "
        "did not before. Avoid celebration language."
    ),
    PostType.CASE_STUDY: (
        "Format: CASE STUDY. Situation, what was tried, what happened, what you would "
        "do differently."
    ),
    PostType.SHORT_OBSERVATION: (
        "Format: SHORT OBSERVATION. Under 120 words. One sharp, specific point."
    ),
    PostType.PROJECT_DEMO: (
        "Format: PROJECT DEMO. Describe what it does and the single most interesting "
        "implementation detail."
    ),
}

VARIANT_GUIDANCE: dict[str, str] = {
    "A": "Variant A: concise. Get to the point fast; cut anything that is not load-bearing.",
    "B": "Variant B: technical. Go deeper on mechanism and trade-offs for an engineer reader.",
    "C": "Variant C: conversational. Same substance, looser register, still no filler.",
}


def build_writer_prompt(
    *,
    topic: str,
    post_type: PostType,
    why_it_matters: str | None = None,
    research_summary: str | None = None,
    evidence: list[str] | None = None,
    uncertainty: str | None = None,
    variant: str = "A",
    target_range: tuple[int, int] = (700, 1400),
    style_notes: list[str] | None = None,
) -> str:
    parts = [f"TOPIC: {topic}"]
    if why_it_matters:
        parts.append(f"WHY IT MATTERS: {why_it_matters}")
    parts.append(FORMAT_GUIDANCE.get(post_type, ""))
    parts.append(VARIANT_GUIDANCE.get(variant, VARIANT_GUIDANCE["A"]))

    if research_summary:
        parts.append(f"RESEARCH: {research_summary}")
    if evidence:
        parts.append("EVIDENCE:\n" + "\n".join(f"- {item}" for item in evidence))
    if uncertainty:
        parts.append(
            f"UNCERTAIN (do not state these as fact; omit or hedge honestly): {uncertainty}"
        )
    if style_notes:
        parts.append(
            "LEARNED STYLE PREFERENCES (from posts this author approved and edited):\n"
            + "\n".join(f"- {note}" for note in style_notes)
        )

    low, high = target_range
    parts.append(f"LENGTH: roughly {low}-{high} characters.")
    return "\n\n".join(p for p in parts if p)


REWRITE_INSTRUCTIONS: dict[str, str] = {
    "shorten": "Cut this to roughly 60% of its length. Remove the least load-bearing "
               "sentences. Keep every concrete detail.",
    "expand": "Add one more layer of specific technical detail. Do not pad with "
              "generalities or restate what is already said.",
    "more_technical": "Rewrite for a more technical reader: name mechanisms, trade-offs "
                      "and constraints explicitly.",
    "more_casual": "Loosen the register. Same substance and same specifics, less formal.",
    "rewrite_hook": "Rewrite only the first line so it states something concrete and "
                    "true. No teasing, no question, no suspense. Return the full post.",
    "rewrite_paragraph": "Rewrite the indicated paragraph only. Return the full post "
                         "with that paragraph replaced.",
    "regenerate": "Write a different post on the same topic, taking a different angle.",
}


def build_rewrite_prompt(
    *, content: str, operation: str, instruction: str | None = None, paragraph: str | None = None
) -> str:
    parts = [REWRITE_INSTRUCTIONS.get(operation, REWRITE_INSTRUCTIONS["regenerate"])]
    if paragraph:
        parts.append(f"PARAGRAPH TO CHANGE:\n{paragraph}")
    if instruction:
        parts.append(f"ADDITIONAL INSTRUCTION: {instruction}")
    parts.append(f"CURRENT POST:\n{content}")
    parts.append("Return only the rewritten post body.")
    return "\n\n".join(parts)
