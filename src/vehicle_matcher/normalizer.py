from __future__ import annotations

import re

# Keep '/' and '-' inside tokens ("h/line", "r-line"); everything else
# non-alphanumeric becomes a space.
_PUNCT = re.compile(r"[^a-z0-9/\-\s]")
_EDGE_PUNCT = re.compile(r"(?:^[/\-]+)|(?:[/\-]+$)")


def normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation (preserving intra-token '/' and '-'),
    collapse whitespace, return tokens."""
    lowered = text.lower()
    cleaned = _PUNCT.sub(" ", lowered)
    tokens = []
    for raw in cleaned.split():
        token = _EDGE_PUNCT.sub("", raw)
        if token:
            tokens.append(token)
    return tokens
