from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from .config import Settings
from .models import Candidate, ExtractedVehicle

# One round-trip, recall arms chosen by what extraction found. All values are
# bound parameters — description text is data, never SQL.
#
#   model stated   -> model arm: exact or trigram-similar model name (also
#                     catches "Amrok"-level typos of a recognised model)
#   make only      -> make arm: every vehicle of that make is a candidate
#                     (scoring sorts them out), plus the token arm
#   neither        -> token arm: each badge/unknown token word-similar to
#                     search_text — the recall backstop for misspelled models
#                     we did NOT recognise.
#
# The token arm uses one flat `token <<% search_text` term per token (a form
# the GIN trigram index supports) rather than EXISTS over unnest (which forces
# a seq scan). STRICT word similarity on purpose: plain word_similarity
# matches partial-word extents, so a short token like "cab" scores 0.5 against
# "ca(mry)" and floods the pool.
#
# Precision is the scorer's job; retrieval only owes us recall.
_SELECT = """
SELECT v.id, v.make, v.model, v.badge, v.transmission_type, v.fuel_type, v.drive_type,
       GREATEST(
         similarity(v.search_text, %(text)s),
         word_similarity(%(text)s, v.search_text),
         COALESCE((SELECT max(strict_word_similarity(t.tok, v.search_text))
                   FROM unnest(%(tokens)s::text[]) AS t(tok)), 0.0)
       ) AS trgm_score,
       COALESCE(s.listing_count, 0) AS listing_count
FROM vehicle v
LEFT JOIN vehicle_listing_stats s ON s.vehicle_id = v.id
WHERE {where}
ORDER BY trgm_score DESC
LIMIT %(k)s
"""

_MAX_ARM_TOKENS = 8


def configure_session(conn: psycopg.Connection, settings: Settings) -> None:
    """Set the pg_trgm thresholds the % / <<% operators compare against."""
    conn.execute(
        "SELECT set_config('pg_trgm.similarity_threshold', %s, false)",
        (str(settings.model_sim_threshold),),
    )
    conn.execute(
        "SELECT set_config('pg_trgm.strict_word_similarity_threshold', %s, false)",
        (str(settings.token_sim_threshold),),
    )


def search_phrase(extracted: ExtractedVehicle) -> str:
    """The text compared against vehicle.search_text (make model badge)."""
    parts: list[str] = []
    if extracted.make:
        parts.append(extracted.make)
    if extracted.model:
        parts.append(extracted.model)
    parts.extend(extracted.badge_tokens)
    if extracted.model is None:
        # Unknown tokens may be a misspelled model; only useful when we have
        # no model, and pure noise (polluting trigram scores) when we do.
        parts.extend(extracted.unknown_tokens)
    return " ".join(parts).lower()


def fetch_candidates(
    conn: psycopg.Connection, extracted: ExtractedVehicle, settings: Settings
) -> list[Candidate]:
    tokens = list(dict.fromkeys(extracted.badge_tokens + extracted.unknown_tokens))
    params: dict[str, object] = {
        "text": search_phrase(extracted),
        "tokens": tokens,
        "k": settings.candidate_k,
    }

    arms: list[str] = []
    if extracted.model is not None:
        params["model"] = extracted.model.lower()
        arms.append("lower(v.model) = %(model)s OR lower(v.model) %% %(model)s")
    else:
        if extracted.make is not None:
            params["make"] = extracted.make.lower()
            arms.append("lower(v.make) = %(make)s")
        for i, token in enumerate(tokens[:_MAX_ARM_TOKENS]):
            params[f"tok{i}"] = token
            arms.append(f"%(tok{i})s <<%% v.search_text")

    if not arms:
        return []

    query = _SELECT.format(where=" OR ".join(f"({arm})" for arm in arms))
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(query, params).fetchall()
    return [Candidate(**row) for row in rows]
