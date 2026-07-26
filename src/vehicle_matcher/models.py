from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Transmission = Literal["Automatic", "Manual"]
Fuel = Literal["Petrol", "Diesel", "Hybrid-Petrol"]
Drive = Literal["Front Wheel Drive", "Rear Wheel Drive", "Four Wheel Drive"]


class Flags(BaseModel):
    correction_applied: bool = False
    distractor_stripped: bool = False
    modified_vehicle: bool = False
    non_vehicle: bool = False


class ExtractedVehicle(BaseModel):
    """What the description says, in canonical vocabulary. Attributes are None
    when unstated — extraction never guesses. This model is the seam between
    the rule extractor and the optional LLM extractor: both produce it, and
    everything downstream is indifferent to which one did.
    """

    make: str | None = None
    model: str | None = None
    badge_tokens: list[str] = Field(default_factory=list)
    transmission: Transmission | None = None
    fuel: Fuel | None = None
    drive: Drive | None = None
    # Weak signals hint an attribute (TSI -> Petrol) but never create conflicts.
    weak_fuel: Fuel | None = None
    weak_transmission: Transmission | None = None
    # Tokens we couldn't classify; retrieval uses them for fuzzy recall when no
    # model was extracted (e.g. the "Amrok" misspelling).
    unknown_tokens: list[str] = Field(default_factory=list)
    flags: Flags = Field(default_factory=Flags)


class Candidate(BaseModel):
    """One retrieval row: a catalogue vehicle plus retrieval metadata."""

    id: str
    make: str
    model: str
    badge: str
    transmission_type: str
    fuel_type: str
    drive_type: str
    trgm_score: float
    listing_count: int


class ScoredCandidate(BaseModel):
    candidate: Candidate
    score: float
    conflicts: int


class MatchDebug(BaseModel):
    extracted: ExtractedVehicle
    top_score: float | None = None
    runner_up_score: float | None = None
    candidate_count: int = 0
    scored: list[ScoredCandidate] = Field(default_factory=list)
    tier: Literal["rules", "llm"] = "rules"


class MatchResult(BaseModel):
    vehicle_id: str | None
    confidence: int
    debug: MatchDebug
