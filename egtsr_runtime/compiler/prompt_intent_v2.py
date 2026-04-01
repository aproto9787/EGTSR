"""Prompt intent classifier v2 — risk-flag based classification.

Replaces the simple keyword-match v1 with a 4-stage pipeline:
1. Language-agnostic rule layer (code patterns, file extensions)
2. Write-sensitive lexicon (Korean + English)
3. Mixed prompt penalty (read+write => write-risk)
4. Fallback: no flags => ambiguous (treated as write-risk)

v1 (PromptIntentClassifier) is preserved for compatibility but deprecated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class PromptRiskFlags:
    requests_read: bool = False
    requests_inspection: bool = False
    requests_test: bool = False
    requests_write: bool = False
    requests_repo_mutation: bool = False
    ambiguous: bool = False
    raw_intent: str = ""  # v1-compatible string


# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

_READ_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:read|show|display|print|cat|view|look|list|ls|what|find|grep|search)\b", re.I),
    re.compile(r"(?:보여|읽어|확인해|찾아|검색)", re.I),
]

_INSPECT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:inspect|check|status|debug|diagnose|why|how|explain|describe|diff)\b", re.I),
    re.compile(r"(?:점검|진단|설명|상태|분석|왜|어떻게)", re.I),
]

_TEST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:test|run\s+test|verify|assert|pytest|unittest|check\s+test|lint)\b", re.I),
    re.compile(r"(?:테스트|검증)", re.I),
]

_WRITE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:fix|change|modify|update|add|remove|delete|refactor|implement|create|write|edit|patch|rewrite|rename|move|replace|insert|append)\b", re.I),
    re.compile(r"(?:수정|변경|추가|삭제|생성|구현|리팩토링|만들어|고쳐|바꿔|넣어|지워|없애|작성|편집|업데이트|고치|수정해|바꾸)", re.I),
]

_REPO_MUTATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:commit|push|merge|rebase|reset|checkout|branch|tag|release|deploy|publish)\b", re.I),
    re.compile(r"\b(?:git\s+(?:push|commit|merge|rebase|reset|checkout|branch|tag))\b", re.I),
    re.compile(r"(?:커밋|푸시|머지|배포|릴리즈)", re.I),
]

# Code-pattern rules (language-agnostic): mentioning file paths with
# write-intent markers strongly indicates write risk.
_CODE_WRITE_PATTERNS: list[re.Pattern[str]] = [
    # e.g. "create src/foo.py", "add a handler in utils/"
    re.compile(r"\b(?:create|add|write|edit|modify)\s+\S+\.(?:py|ts|js|rs|go|java|cpp|c|h|rb|sh)\b", re.I),
    re.compile(r"\b(?:create|add|write|edit|modify)\s+\S+/", re.I),
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_prompt_intent_v2(prompt_text: str) -> PromptRiskFlags:
    """Classify a user prompt into risk flags.

    4-stage pipeline:
    1. Language-agnostic rule layer (code patterns)
    2. Write-sensitive lexicon (Korean + English)
    3. Mixed prompt penalty: read + write => write-risk emphasized
    4. Fallback: no flags matched => ambiguous=True (write-risk)
    """
    text = (prompt_text or "").strip()
    flags = PromptRiskFlags()

    if not text:
        flags.ambiguous = True
        flags.raw_intent = "ambiguous"
        return flags

    normalized = text.lower()

    # Stage 1: code-pattern rules
    for pat in _CODE_WRITE_PATTERNS:
        if pat.search(normalized):
            flags.requests_write = True
            break

    # Stage 2: lexicon matching
    if _any_match(_READ_PATTERNS, normalized):
        flags.requests_read = True
    if _any_match(_INSPECT_PATTERNS, normalized):
        flags.requests_inspection = True
    if _any_match(_TEST_PATTERNS, normalized):
        flags.requests_test = True
    if _any_match(_WRITE_PATTERNS, normalized):
        flags.requests_write = True
    if _any_match(_REPO_MUTATION_PATTERNS, normalized):
        flags.requests_repo_mutation = True

    # Stage 3: mixed prompt penalty
    has_read_like = flags.requests_read or flags.requests_inspection or flags.requests_test
    has_write_like = flags.requests_write or flags.requests_repo_mutation
    if has_read_like and has_write_like:
        # Mixed signals: ensure write stays flagged (penalty)
        flags.requests_write = True

    # Stage 4: fallback — nothing matched
    if not any([
        flags.requests_read,
        flags.requests_inspection,
        flags.requests_test,
        flags.requests_write,
        flags.requests_repo_mutation,
    ]):
        flags.ambiguous = True

    # Compute v1-compatible raw_intent
    flags.raw_intent = _compute_raw_intent(flags)
    return flags


def _any_match(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _compute_raw_intent(flags: PromptRiskFlags) -> str:
    """Map risk flags back to a v1-compatible intent string."""
    if flags.ambiguous:
        return "ambiguous"
    if flags.requests_repo_mutation:
        return "edit"
    if flags.requests_write:
        return "edit"
    if flags.requests_test:
        return "test"
    if flags.requests_inspection:
        return "inspect"
    if flags.requests_read:
        return "read"
    return "mixed"
