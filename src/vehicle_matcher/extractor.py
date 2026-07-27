from __future__ import annotations

import re

from .models import ExtractedVehicle, Flags, Fuel, Transmission
from .normalizer import normalize
from .vocabulary import Vocabulary

# Discourse rules. Marketplace text routinely talks about more than one vehicle;
# these decide which mention is the subject before any token-level extraction.

# "(... actually a Toyota 86 GT ...)" — the parenthetical replaces the original claim.
_CORRECTION_PARENS = re.compile(r"\(([^)]*\b(?:actually|really|it'?s a)\b[^)]*)\)", re.IGNORECASE)
# "... it's actually a <correction>" inline — keep the text after the marker.
_CORRECTION_INLINE = re.compile(r"\b(?:it'?s )?actually (?:a |an )?", re.IGNORECASE)
# "engine swap from <donor>" — the donor vehicle is not what's being sold.
_MODIFIED = re.compile(
    r"\b(?:with )?(?:engine swap|swapped engine|engine conversion)\b", re.IGNORECASE
)
# "in exchange for <wanted>" — the wanted vehicle is not what's being sold.
_DISTRACTOR = re.compile(
    r"\b(?:in exchange for|swap for|swapped for|looking for|wtb)\b", re.IGNORECASE
)

_ENGINE_TSI = re.compile(r"^\d{2,3}tsi$")
_ENGINE_TDI = re.compile(r"^tdi\d{3}$")

_NON_VEHICLE_PHRASES = ("golf cart", "golf buggy", "golf clubs", "go kart", "go-kart")

# Function words and marketplace filler that carry no vehicle signal. Kept
# small on purpose: anything not listed here survives as an unknown token,
# which only feeds fuzzy retrieval and costs nothing when irrelevant.
_STOPWORDS = frozenset(
    "a an the my our this that it its is are was be been but and or of to in on at "
    "for with from sale selling sell wanted urgent cheap price ono nego car vehicle "
    "sorry please me let didn t s".split()
)


def _segment(text: str, flags: Flags) -> str:
    """Apply discourse rules to raw text, returning the segment that describes
    the vehicle actually being sold."""
    m = _CORRECTION_PARENS.search(text)
    if m:
        flags.correction_applied = True
        text = m.group(1)
    elif _CORRECTION_INLINE.search(text):
        flags.correction_applied = True
        text = _CORRECTION_INLINE.split(text)[-1]

    m = _MODIFIED.search(text)
    if m:
        flags.modified_vehicle = True
        text = text[: m.start()]

    m = _DISTRACTOR.search(text)
    if m:
        flags.distractor_stripped = True
        text = text[: m.start()]

    return text


def extract(text: str, vocab: Vocabulary) -> ExtractedVehicle:
    flags = Flags()

    full = " ".join(normalize(text))
    if any(phrase in f" {full} " for phrase in (f" {p} " for p in _NON_VEHICLE_PHRASES)):
        return ExtractedVehicle(flags=Flags(non_vehicle=True))

    tokens = normalize(_segment(text, flags))
    extracted = ExtractedVehicle(flags=flags)

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Engine codes before vocabulary lookup: they double as badge tokens
        # AND a weak fuel hint, and the plain badge lookup would lose the hint.
        if _ENGINE_TSI.match(token):
            _apply(extracted, "badge", token)
            _apply_weak_fuel(extracted, "Petrol")
            i += 1
            continue
        if _ENGINE_TDI.match(token):
            _apply(extracted, "badge", token)
            _apply_weak_fuel(extracted, "Diesel")
            i += 1
            continue

        consumed = False
        # Longest alias phrase first ("front wheel drive" before "front").
        for n in range(min(vocab.max_alias_words, len(tokens) - i), 0, -1):
            phrase = " ".join(tokens[i : i + n])
            entry = vocab.lookup(phrase)
            if entry is None:
                continue
            _apply(extracted, entry.attribute, entry.canonical, weak=entry.weak)
            i += n
            consumed = True
            break
        if consumed:
            continue

        if token not in _STOPWORDS:
            extracted.unknown_tokens.append(token)
        i += 1

    return extracted


def canonicalize(ev: ExtractedVehicle, vocab: Vocabulary) -> ExtractedVehicle:
    """Map an externally produced extraction (e.g. LLM output) onto the same
    canonical vocabulary the rule extractor uses.

    Found by the shadow audit: the LLM occasionally returns "VW" unexpanded,
    promotes a badge word to model ("Ascent"), or files a fuel word under
    badge_tokens. Left raw, those become spurious conflicts and false nulls.
    The vocabulary arbitrates each word's role; genuinely unknown values
    (Ford, Ranger) pass through untouched so absence detection still works.
    """
    out = ev.model_copy(deep=True)

    if out.make:
        entry = vocab.lookup(out.make.lower())
        if entry is not None and entry.attribute == "make":
            out.make = entry.canonical

    if out.model:
        entry = vocab.lookup(out.model.lower())
        if entry is not None:
            if entry.attribute == "model":
                out.model = entry.canonical
            elif entry.attribute == "badge":
                # a badge word was promoted to model — demote it back
                if entry.canonical not in out.badge_tokens:
                    out.badge_tokens.insert(0, entry.canonical)
                out.model = None

    tokens: list[str] = []
    for raw in out.badge_tokens:
        token = raw.lower()
        entry = vocab.lookup(token)
        if entry is None:
            tokens.append(token)
        elif entry.attribute == "badge":
            tokens.append(entry.canonical)
        else:
            # an attribute word filed under badge — move it where it belongs
            _apply(out, entry.attribute, entry.canonical, weak=entry.weak)
    out.badge_tokens = list(dict.fromkeys(tokens))

    return out


def _apply(ev: ExtractedVehicle, attribute: str, canonical: str, weak: bool = False) -> None:
    if attribute == "make":
        if ev.make is None:
            ev.make = canonical
    elif attribute == "model":
        if ev.model is None:
            ev.model = canonical
    elif attribute == "badge":
        if canonical not in ev.badge_tokens:
            ev.badge_tokens.append(canonical)
    elif attribute == "transmission":
        value_t: Transmission = canonical  # type: ignore[assignment]
        if weak:
            if ev.transmission is None and ev.weak_transmission is None:
                ev.weak_transmission = value_t
        elif ev.transmission is None:
            ev.transmission = value_t
            ev.weak_transmission = None  # an explicit statement supersedes any hint
    elif attribute == "fuel":
        value_f: Fuel = canonical  # type: ignore[assignment]
        if weak:
            _apply_weak_fuel(ev, value_f)
        elif ev.fuel is None:
            ev.fuel = value_f
            ev.weak_fuel = None  # an explicit statement supersedes any hint
    elif attribute == "drive" and ev.drive is None:
        ev.drive = canonical  # type: ignore[assignment]


def _apply_weak_fuel(ev: ExtractedVehicle, fuel: Fuel) -> None:
    if ev.fuel is None and ev.weak_fuel is None:
        ev.weak_fuel = fuel
