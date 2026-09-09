"""Text canonicalisation, hashing, near-duplicate detection and hook analysis.

The content hash is the backbone of approval integrity, so canonicalisation is
deliberately conservative: it absorbs cosmetic whitespace differences (a
trailing space typed on the phone must not invalidate an approval) while any
real wording change produces a different hash.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_WS_RUN = re.compile(r"[ \t]+")
_BLANK_RUNS = re.compile(r"\n{3,}")
_WORD = re.compile(r"[a-z0-9][a-z0-9'+#.-]*")


def canonicalize(text: str) -> str:
    """Normalise text for hashing.

    Unicode NFC, CRLF -> LF, collapse horizontal whitespace runs, strip
    per-line trailing spaces, collapse 3+ blank lines to 2, strip the ends.
    """
    if text is None:
        return ""
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RUN.sub(" ", line).rstrip() for line in normalized.split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def content_hash(text: str) -> str:
    """SHA-256 of the canonical form. Used for approval integrity."""
    return hashlib.sha256(canonicalize(text).encode("utf-8")).hexdigest()


def tokens(text: str) -> list[str]:
    return _WORD.findall(canonicalize(text).lower())


def shingles(text: str, size: int = 3) -> set[str]:
    words = tokens(text)
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def simhash(text: str, bits: int = 64) -> int:
    """64-bit simhash over word trigrams, for cheap near-duplicate screening."""
    vector = [0] * bits
    features = shingles(text) or set(tokens(text))
    for feature in features:
        h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        for i in range(bits):
            vector[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i, weight in enumerate(vector):
        if weight > 0:
            out |= 1 << i
    return out


def simhash_hex(text: str) -> str:
    return f"{simhash(text):016x}"


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def jaccard(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def similarity(a: str, b: str) -> float:
    """Blended similarity in ``[0, 1]``.

    Jaccard over trigrams catches reworded-but-same-content; simhash catches
    structural near-duplication. The max of the two is used because either
    signal alone is enough to call something a repeat.
    """
    if not a or not b:
        return 0.0
    if canonicalize(a) == canonicalize(b):
        return 1.0
    jac = jaccard(a, b)
    sim_bits = 1.0 - (hamming_distance(simhash(a), simhash(b)) / 64.0)
    # Rescale simhash: random text already scores ~0.5, so anything below that
    # carries no information.
    sim_scaled = max(0.0, (sim_bits - 0.5) * 2.0)
    return max(jac, sim_scaled)


def extract_hook(text: str) -> str:
    """First non-empty line - what the reader sees before "see more"."""
    for line in canonicalize(text).split("\n"):
        if line.strip():
            return line.strip()
    return ""


_NUMBER_START = re.compile(r"^\s*\d")
_FAILURE_WORDS = re.compile(
    r"\b(broke|broken|failed|failure|bug|crash|wrong|mistake|regression|outage|lost|"
    r"deadlock|leak|corrupt|timeout|misconfigur)\w*",
    re.I,
)


def classify_hook(text: str) -> str:
    """Coarse hook taxonomy used by the learning engine."""
    hook = extract_hook(text)
    if not hook:
        return "NONE"
    if hook.rstrip().endswith("?"):
        return "QUESTION"
    if _FAILURE_WORDS.search(hook):
        return "FAILURE"
    if _NUMBER_START.match(hook) or re.search(r"\b\d+(\.\d+)?\s*(x|%|ms|s|GB|MB|k)\b", hook, re.I):
        return "NUMBER"
    if re.match(r"^(i|we|my|our)\b", hook, re.I):
        return "PERSONAL"
    return "STATEMENT"


def char_count(text: str) -> int:
    return len(canonicalize(text))
