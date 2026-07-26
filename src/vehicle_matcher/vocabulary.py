from __future__ import annotations

from dataclasses import dataclass, field

import psycopg


@dataclass(frozen=True)
class AliasEntry:
    attribute: str  # make | model | badge | transmission | fuel | drive
    canonical: str
    weak: bool = False


@dataclass(frozen=True)
class Vocabulary:
    """Everything the extractor knows about words.

    Built from the database once per process (aliases + catalogue vocabulary),
    but a plain dict-of-values object so unit tests can construct one without a
    database connection.
    """

    aliases: dict[str, AliasEntry]
    catalogue_makes: frozenset[str]  # canonical, as stored in vehicle.make
    catalogue_models: frozenset[str]  # canonical, as stored in vehicle.model
    badge_tokens: frozenset[str]  # lowercase tokens of every catalogue badge
    max_alias_words: int = field(default=3)

    def lookup(self, phrase: str) -> AliasEntry | None:
        """Resolve a (possibly multi-word) surface form to a canonical value.

        Catalogue makes/models resolve directly; everything else goes through
        the alias table. Catalogue badge tokens resolve to themselves.
        """
        entry = self.aliases.get(phrase)
        if entry is not None:
            return entry
        for make in self.catalogue_makes:
            if phrase == make.lower():
                return AliasEntry("make", make)
        for model in self.catalogue_models:
            if phrase == model.lower():
                return AliasEntry("model", model)
        if phrase in self.badge_tokens:
            return AliasEntry("badge", phrase)
        return None


def load_vocabulary(conn: psycopg.Connection) -> Vocabulary:
    aliases: dict[str, AliasEntry] = {}
    for alias_text, attribute, canonical, strength in conn.execute(
        "SELECT alias_text, attribute, canonical, strength FROM alias"
    ):
        aliases[alias_text] = AliasEntry(attribute, canonical, weak=strength == "weak")

    makes: set[str] = set()
    models: set[str] = set()
    badge_tokens: set[str] = set()
    for make, model, badge in conn.execute("SELECT DISTINCT make, model, badge FROM vehicle"):
        makes.add(make)
        models.add(model)
        badge_tokens.update(badge.lower().split())

    max_words = max((a.count(" ") + 1 for a in aliases), default=1)
    return Vocabulary(
        aliases=aliases,
        catalogue_makes=frozenset(makes),
        catalogue_models=frozenset(models),
        badge_tokens=frozenset(badge_tokens),
        max_alias_words=max_words,
    )
