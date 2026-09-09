"""
Cleans raw scraped text (markdown, code blocks, headers) into plain,
readable summaries suitable for a problem-statement listing.
"""
import re

_NO_RESPONSE_RE = re.compile(r"_?no response_?", re.IGNORECASE)


def clean_markdown(text: str) -> str:
    if not text:
        return ""
    # remove fenced code blocks entirely — they're implementation detail, not the problem
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # remove markdown images entirely, alt-text included — badges/shields, not real content
    # (must run BEFORE the link regex below, or the leading "!" is left dangling, e.g. "!Time: <1 minute")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # remove inline code backticks but keep the content
    text = re.sub(r"`([^`]*)`", r"\1", text)
    # remove markdown headers (###, ##, #)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    # remove blockquote markers (> ...)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    # remove bold/italic markers — both *asterisk* and _underscore_ styles
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    # remove markdown links, keep the label: [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # remove bare URLs
    text = re.sub(r"https?://\S+", "", text)
    # collapse multiple blank lines / whitespace
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def is_mostly_english(text: str, threshold: float = 0.85) -> bool:
    """Rough heuristic: reject entries that are mostly non-ASCII (non-English),
    since a student problem-statement board should be readable by default."""
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return (ascii_chars / max(len(text), 1)) >= threshold


def is_low_quality(text: str, min_response_count: int = 3) -> bool:
    """Reject entries that are mostly an unfilled issue-form template —
    GitHub renders empty required fields as literal 'No response' text,
    so an entry with several of these has no real problem statement in it."""
    if not text:
        return True
    return len(_NO_RESPONSE_RE.findall(text)) >= min_response_count


def summarize(text: str, max_len: int = 220) -> str:
    cleaned = clean_markdown(text)
    if len(cleaned) <= max_len:
        return cleaned
    # cut at the last full word before max_len
    cut = cleaned[:max_len].rsplit(" ", 1)[0]
    return cut + "…"
