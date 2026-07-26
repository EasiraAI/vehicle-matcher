from __future__ import annotations

from .models import ExtractedVehicle, ScoredCandidate

# Confidence has two distinct meanings (per the challenge README):
#   - with a vehicle ID:  how sure we are this IS the vehicle
#   - with a null ID:     how sure we are the vehicle is NOT in the catalogue
# The two branches below implement each semantic separately.

_CORE_ATTRS = 5  # make, model, transmission, fuel, drive


def _specificity(extracted: ExtractedVehicle) -> tuple[int, int]:
    """(stated core attribute count, specificity incl. up to 2 badge tokens)."""
    stated = sum(
        1
        for v in (
            extracted.make,
            extracted.model,
            extracted.transmission,
            extracted.fuel,
            extracted.drive,
        )
        if v is not None
    )
    return stated, stated + min(2, len(extracted.badge_tokens))


def match_confidence(
    extracted: ExtractedVehicle, top: ScoredCandidate, runner_up: ScoredCandidate | None
) -> int:
    """Confidence that the top candidate is the right vehicle.

    Built from what a human reviewer would ask of a match:
      how much did the description actually say (specificity, 0-4)?
      how far ahead of the next-best candidate is it (margin, 0-2)?
      does anything the description said contradict it (conflicts)?
      how much was left unsaid, and did we have to reinterpret the text
      (corrections / distractors) to get here?
    """
    stated, specificity = _specificity(extracted)
    margin = top.score - runner_up.score if runner_up else float("inf")
    margin_points = 0 if margin < 0.5 else (1 if margin < 1.5 else 2)

    confidence = 3 + min(4, specificity) + margin_points
    if top.conflicts:
        confidence -= 2
    if (_CORE_ATTRS - stated) >= 2:
        confidence -= 1
    if extracted.flags.correction_applied or extracted.flags.distractor_stripped:
        confidence -= 1
    if extracted.flags.modified_vehicle:
        confidence = min(confidence, 6)
    return max(0, min(10, confidence))


def null_confidence(
    extracted: ExtractedVehicle,
    catalogue_makes: frozenset[str],
    catalogue_models: frozenset[str],
) -> int:
    """Confidence that the vehicle is genuinely absent from the catalogue.

    Certainty comes from having cleanly recognised WHAT the vehicle is and
    knowing the catalogue doesn't carry it. A make we know exists in the world
    but not in the catalogue (Ford) is near-certain absence; text we simply
    couldn't interpret is a low-confidence null — absence of evidence, not
    evidence of absence.
    """
    if extracted.flags.non_vehicle:
        return 10
    if extracted.make is not None and extracted.make not in catalogue_makes:
        return 10
    if extracted.model is not None and extracted.model not in catalogue_models:
        return 9
    if extracted.make is not None or extracted.model is not None:
        return 7
    return 3
