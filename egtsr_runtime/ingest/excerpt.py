from __future__ import annotations

MAX_EXCERPT_LENGTH = 500


def clip_excerpt(text: str, max_length: int = MAX_EXCERPT_LENGTH) -> str:
    """Clip text to max_length, adding '...' if truncated."""
    if max_length <= 3:
        return text[:max_length]
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."
