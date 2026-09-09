"""Phrase and pattern lists for the AI-slop detector.

Everything here is a *signal*, not a ban: a post is scored on the weight of
evidence, so one unlucky word never rejects an otherwise concrete post.
"""

from __future__ import annotations

import re

# Hype words that almost always signal generic LinkedIn filler.
CLICHE_PHRASES: tuple[str, ...] = (
    "game changer",
    "game-changer",
    "revolutionary",
    "mind-blowing",
    "mind blowing",
    "10x",
    "game changing",
    "paradigm shift",
    "the future is here",
    "let that sink in",
    "needle-moving",
    "supercharge",
    "unlock the power",
    "harness the power",
    "in today's fast-paced world",
    "in today's world",
    "at the end of the day",
    "the possibilities are endless",
    "this changes everything",
    "buckle up",
    "here's the thing",
    "spoiler alert",
    "plot twist",
    "hot take",
    "leveraging synergies",
    "thought leader",
    "rockstar",
    "ninja",
    "crushing it",
    "the secret sauce",
    "low-hanging fruit",
)

# Structural tics of AI-written LinkedIn posts.
SLOP_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(ai|it)\s+is\s*n[o']t\s+coming\b", "'X isn't coming' suspense opener"),
    (r"here are \d+\s+\w+", "'Here are N things' listicle opener"),
    (
        r"\b\d+\s+(things|ways|lessons|reasons|tips|secrets)\b.{0,30}\b(you|that)\b",
        "numbered listicle framing",
    ),
    (r"\byou (must|need to) know\b", "'you must know' urgency"),
    (r"\bmost people (don'?t|do not)\b", "'most people don't' superiority hook"),
    (r"\bread that again\b", "'read that again' engagement tic"),
    (r"\bwhat if i told you\b", "'what if I told you' hook"),
    (r"\bthe result\?\s*$", "one-word suspense line"),
    (r"\bhere'?s (why|how)\b.{0,20}$", "'here's why' cliffhanger"),
    (r"\blet me explain\b", "'let me explain' filler"),
    (r"\bthread\b\s*(👇|below)", "thread bait"),
)

# Explicit calls for engagement, which LinkedIn also demotes.
ENGAGEMENT_BAIT: tuple[tuple[str, str], ...] = (
    (r"\bcomment (below|your|with)\b", "asks for comments"),
    (r"\b(dm|pm) me\b", "asks for DMs"),
    (r"\brepost (this|if)\b", "asks for reposts"),
    (r"\blike (this|if you)\b", "asks for likes"),
    (r"\bwho else\b", "'who else' bait"),
    (r"\bagree\?\s*$", "'agree?' bait"),
    (r"\bthoughts\?\s*$", "'thoughts?' bait"),
    (r"\bfollow me for\b", "follow-for-more bait"),
    (r"\btag someone\b", "tag bait"),
    (r"\bdrop a \w+ (below|in the comments)\b", "drop-a-comment bait"),
)

# Evidence that the author actually did something.
FIRST_PERSON = re.compile(r"\b(i|i'?m|i'?ve|my|we|we'?ve|our)\b", re.I)
CONCRETE_NUMBER = re.compile(
    r"\b\d+(\.\d+)?\s*(ms|s|m|h|%|x|kb|mb|gb|k|lines?|tests?|times?)\b", re.I
)
ANY_NUMBER = re.compile(r"\b\d+(\.\d+)?\b")

# Technical vocabulary, used as a depth signal rather than a whitelist.
TECHNICAL_TERMS = re.compile(
    r"\b(api|apis|sdk|database|db|sql|sqlite|postgres|index|indexes|query|queries|cache|caching|"
    r"latency|throughput|schema|migration|migrations|endpoint|token|tokens|embedding|embeddings|"
    r"async|thread|threads|queue|worker|retry|retries|backoff|idempoten\w*|hash|hashes|checksum|"
    r"transaction|deadlock|race condition|timeout|memory|cpu|deploy|deployment|docker|kubernetes|"
    r"compile|compiler|runtime|regression|refactor|test|tests|unit test|integration|repo|commit|"
    r"branch|merge|pipeline|agent|agents|prompt|prompts|llm|model|inference|fine-tune|vector|"
    r"webhook|oauth|auth|jwt|tls|http|json|yaml|kotlin|python|rust|typescript|compose|gradle)\b",
    re.I,
)

EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]",
    flags=re.UNICODE,
)

HASHTAG = re.compile(r"(?:^|\s)#\w+")

# Generic hashtags that add nothing.
GENERIC_HASHTAGS = {
    "#ai",
    "#tech",
    "#innovation",
    "#motivation",
    "#success",
    "#leadership",
    "#growth",
    "#business",
    "#future",
    "#technology",
    "#inspiration",
    "#hustle",
}


# Structural specificity signals. These matter more than any keyword list:
# real technical writing is full of acronyms, identifiers and named things,
# and a fixed vocabulary can never keep up with what the user builds.
ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")
IDENTIFIER = re.compile(r"\b\w+_\w+\b|\b[a-z]+[A-Z]\w+\b|`[^`]+`")
PROPER_NOUN = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.M)
SPELLED_NUMBER = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|dozen|twice|"
    r"half|hundred|thousand)\b\s+\w+",
    re.I,
)
DURATION = re.compile(
    r"\b(second|minute|hour|day|week|month|morning|night|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday)s?\b",
    re.I,
)
