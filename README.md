# Vehicle Matcher

Matches free-text marketplace car descriptions to a vehicle in a PostgreSQL
catalogue, with a calibrated 0–10 confidence score — including confident
*absence* ("Ford Ranger" → `null` at confidence 10).

```
Input: VW Amarok Ultimate
Vehicle ID: 4951649860714496
Confidence: 7
```

## Quickstart

```bash
docker compose up -d --wait          # postgres:16 on localhost:5433
make setup                           # venv + install (or: pip install -e ".[dev]")
python scripts/setup_db.py           # load challenge data + migrations, verify counts
python -m vehicle_matcher.cli data/inputs.txt          # the 20 challenge inputs
python -m vehicle_matcher.cli data/inputs.txt --debug  # + score table per input
make test                            # full suite (unit / integration / golden)
```

Configuration is env-based (see `.env.example`); everything defaults to the
compose stack. The complete output over `inputs.txt` is committed at
[docs/final-run.txt](docs/final-run.txt).

## How it works

```
description ──► normalize ──► extract ──► retrieve ──► score ──► calibrate ──► result
                              │           (1 SQL       (pure     (pure fn)
               alias table    │            round-trip)  fn)
               (in DB)        │                                     │
                              │                         confidence < gate?
                              └──── optional LLM extractor ◄────────┘
                                    (env-gated, cached, fallback-safe)
```

- **normalize** – lowercase, strip punctuation (keeping `h/line`, `r-line`
  intact), tokenize.
- **extract** – discourse rules first (corrections like *"it's actually a
  Toyota 86 GT"* replace the original mention; *"in exchange for …"* and
  *"engine swap from …"* segments are cut), then a greedy longest-match scan
  against the vocabulary: catalogue makes/models, an alias table (`vw` →
  Volkswagen, `4x4` → Four Wheel Drive, `h/line` → highline…), engine-code
  regexes (`110TSI` → badge token + a *weak* Petrol hint). Nothing is guessed:
  unstated attributes stay `None`.
- **retrieve** – one round-trip to Postgres choosing recall arms by what was
  extracted: exact/trigram model match, all-of-make, or per-token strict word
  similarity against a generated `search_text` column (all trigram-GIN
  indexed). Retrieval owes recall only; precision is the scorer's job.
- **score** – per attribute: match, conflict, or unstated. Conflicts are
  punished far harder than silence (*unstated ≠ conflict*), badge penalties are
  asymmetric (a stated badge word the candidate lacks hurts more than surplus
  candidate words), weak signals never conflict, and a small `ln(1 +
  listing_count)` prior implements the "most listings wins ties" rule.
- **calibrate** – confidence from what a reviewer would ask: how much did the
  text actually say, how far ahead is the winner, does anything contradict it,
  did we have to reinterpret the text to get here. Null results get their own
  scale: recognised-but-absent vehicles (Ford Ranger, Toyota Corolla) are
  high-confidence nulls; uninterpretable text is a low-confidence null.

Three principles hold everywhere:

1. **The LLM never picks a vehicle ID.** The optional tier (off by default,
   `MATCHER_LLM_ENABLED=true` to enable) only re-extracts attributes when the
   rules result is below the confidence gate; matching always runs through the
   same deterministic pipeline. It is cached by content hash and degrades to
   the rules result on any API failure.
2. **Push down what benefits from indexes; pull up what benefits from tests.**
   Candidate retrieval lives in SQL next to the trigram indexes; scoring and
   calibration are pure functions with 97–100% branch coverage.
3. **Vocabulary is data.** Marketplace surface forms live in an `alias` table,
   not in code — growing coverage is an INSERT, not a release.

## Design decisions

- **`data.sql` defect** – the vendor file creates `listing` with PK column
  `it` but INSERTs into `id`; the raw script cannot run. The loader creates
  the table, renames `it → id`, then runs the vendor INSERT unmodified. The
  file itself is never edited (CI pins its sha256).
- **External reference vocabulary** – the alias table also carries common
  AU-market makes/models that are *not* in the catalogue. That is what turns
  "Ford Ranger" from "unrecognised text" (a weak null) into "a real vehicle
  this catalogue provably doesn't carry" (null at 10). Absence detection needs
  world knowledge; a closed catalogue alone can't provide it.
- **`strict_word_similarity`, not `word_similarity`** – plain word similarity
  matches partial-word extents, so the token "cab" scores 0.5 against
  "**ca**mry" and floods the candidate pool. Strict (whole-word) similarity
  keeps "amrok" → "amarok" recall while dropping that noise. Found by a failing
  retrieval test, kept as a regression test.
- **Fuzzy badge floor at 0.85** – adjacent trim codes are exactly 0.8 apart by
  SequenceMatcher ("gt"/"gts", "gx"/"gxl") and are *different vehicles*, not
  typos of each other. Fuzzy badge matching exists for typos of long words.
- **Generated `search_text` column + GIN** – computed at write time (can't
  drift, inspectable), GIN over GiST because the workload is read-dominated.
  At 59 rows Postgres rightly seq-scans; the indexes are for the 10k+
  requirement and [docs/scale-evidence.txt](docs/scale-evidence.txt) shows them
  engaging there.
- **Listing counts as a materialized view** – popularity is a prior, staleness
  is acceptable; refresh is `REFRESH MATERIALIZED VIEW CONCURRENTLY` out of
  band, never on the request path.
- **Two confidence semantics** – match-confidence and null-confidence are
  different questions and are calibrated by separate functions.

## Accuracy

The only ground truth provided is the four README examples; all four reproduce
exactly (`tests/golden/`): Golf 110TSI Comfortline → `…3712 @ 9`, Amarok
Ultimate → `…4496 @ 7`, Golf R engine swap → `…8640 @ 6` (modified-vehicle cap),
Ford Ranger → `null @ 10`.

For the remaining 16 inputs the full output is snapshot-locked — any behaviour
change shows up in review as a diff. Spot checks worth calling out: the
Kluger→86 GT correction resolves to the 86 GT with the tie broken by listing
count; "Amrok h/line 4x4" reaches Amarok TDI550 Highline through fuzzy
retrieval at deliberately modest confidence; "Toyota Corolla Ascent Sport
Auto" is a confident null (Corolla is real and absent) even though Camry
Ascent Sport candidates score superficially well.

Genuinely ambiguous inputs ("Toyota Camry Hybrid" — three hybrid Camrys) are
answered at modest confidence with the most-listed candidate, which is
calibrated uncertainty doing its job, not a miss.

## Scale (10k+ vehicles / 100k+ listings)

`scripts/synth_scale.py` builds a synthetic 10,000-vehicle / 100,000-listing
catalogue and runs the real matcher over 1,000 mixed-style queries
([full evidence](docs/scale-evidence.txt)):

| metric | value |
|---|---|
| p50 / p95 / max latency | **7.8 ms / 41.8 ms / 150 ms** |
| matched | 949/1000 (misses are the deliberately garbled styles, returned as low-confidence nulls) |
| model arm plan | BitmapOr over btree + trigram GIN, 0.55 ms |
| token arm plan | Bitmap Index Scan on `search_text` GIN, 4.9 ms |

The p95 tail is the make-only arm (an entire make's vehicles scored in
Python). At real production scale the end-game for that path is an in-process
catalogue cache (~1–2 MB at 10k vehicles, refreshed periodically) with
Postgres as the source of truth — see roadmap.

## Cost

The rules path costs effectively nothing per call. With the LLM tier enabled,
only descriptions below the confidence gate escalate (2/20 challenge inputs at
the default gate of 5; ~5–15% on realistic traffic), responses are cached by
content hash, and a Haiku-class model at ~750 tokens/call (~$0.0014/call) puts
the blended cost around $0.0001–0.0002 per description matched. The gate is the
accuracy–cost dial: raise it for accuracy, lower it for cost.

## Testing

125 tests across five layers:

| layer | what it proves |
|---|---|
| unit (no DB, ms) | normalizer, extractor discourse rules, scorer weight semantics, calibrator branches, LLM contract (stub client, offline) |
| property (hypothesis) | no exception on arbitrary unicode; confidence always 0–10; extraction/scoring deterministic |
| integration (real PG) | load idempotency, row counts 59/1000, `it→id` repair, index existence, **recall invariant** (the true vehicle must be in the candidate set), SQL-injection-shaped text leaves the DB intact |
| golden | 4 anchors exact; a **semantic expectation for every one of the 20 inputs** (`test_expected_results.py` — exact IDs where the answer is pinned, required properties where it's ambiguous); byte-level snapshot of the full run; CLI output format; LLM gating/routing with a stub extractor |
| robustness | degenerate/hostile input (unicode, emoji, 10k-char tokens, echoed output format, SQL-shaped text), token-permutation stability, case/whitespace insensitivity, end-to-end confidence monotonicity (more agreeing detail never lowers confidence; conflicting detail never raises it), DB unchanged after a hostile batch |

CI (`.github/workflows/ci.yml`) runs lint → strict mypy → data-integrity
checksum → full suite with a coverage gate (currently 93%, scorer/calibrator
at ~100%) → a smoke run asserting 20 results.

## Requirements coverage

| challenge requirement | where it is satisfied and proven |
|---|---|
| result for every description in `inputs.txt` | CLI over the file; `test_every_description_produces_a_result`, `test_matrix_covers_every_input_line`, CI smoke run asserts 20 |
| vehicle ID + confidence 0–10 per description | output contract test (`test_cli.py`); hypothesis property: confidence ∈ [0, 10] for arbitrary input |
| null match allowed; null confidence = certainty of absence | `null_confidence` branch (`calibrator.py`); Ford Ranger → null@10, Corolla → null@9, garbled → null@3 (`test_calibrator.py`, golden) |
| fewer stated attributes ⇒ lower confidence | specificity term + unstated penalty; monotonicity ladder tests (unit + end-to-end) |
| equal likelihood ⇒ most listings wins | listing prior + `(score, listing_count, id)` sort key; `test_tiebreak_by_listing_count` (unit + golden against real counts) |
| program queries the tables via SQL | all retrieval in `retrieval.py` against live Postgres; integration suite runs it |
| `data.sql` not edited | repair happens in the loader; CI pins the file's sha256 |
| scales to 10k+ vehicles / 100k+ listings | trigram/GIN infrastructure + [scale evidence](docs/scale-evidence.txt): p50 7.8 ms, index plans captured |
| accuracy > cost > latency | deterministic core ≈ free and single-digit-ms; LLM spend only below the confidence gate; accuracy evidenced by anchors + validation matrix |
| production engineering practices | src layout, typed (mypy strict), linted, CI as code, migrations, healthchecked compose, coverage gate, structured debug output |

## Repository layout

```
vehicle-matcher/
├── data/                  # challenge files, byte-identical (CI-checksummed)
├── migrations/            # search infrastructure + vocabulary seed (append-only)
├── scripts/               # setup_db.py (idempotent loader), synth_scale.py (evidence)
├── src/vehicle_matcher/   # normalizer → extractor → retrieval → scorer → calibrator
├── tests/                 # unit / integration / golden / robustness
└── docs/                  # final-run.txt, scale-evidence.txt
```

## Operating notes (running this in a pipeline)

The matcher is a stateless library: one `Matcher` per process holding a DB
connection and a cached vocabulary. For a realtime pipeline, wrap it in a
queue consumer or HTTP service with a `psycopg_pool` connection pool; per-call
work is one SELECT. `MatchDebug` (extraction, candidate count, top score,
margin, tier) is designed to be logged as structured JSON per match — match
rate, null rate, low-confidence rate, and escalation rate are the operational
dials, and a rising low-confidence rate is the vocabulary-drift alarm. The
materialized listing stats refresh out of band (`REFRESH MATERIALIZED VIEW
CONCURRENTLY vehicle_listing_stats`), never on the request path.

## Limitations & roadmap (deliberate, in priority order)

1. **Learned scorer + real calibration.** The weight table is hand-tuned and
   the confidence mapping is a heuristic hit against four anchors — honest but
   not statistically calibrated. With production labels (or mined listing-page
   data), a gradient-boosted ranker plus isotonic calibration replaces both,
   and the current scorer becomes the cold-start fallback.
2. **High-confidence audit loop.** The LLM gate only re-examines *low*
   confidence results, so a confidently-wrong extraction never gets a second
   opinion. Production needs sampled shadow escalation of high-confidence
   matches with a disagreement alarm.
3. **In-process catalogue cache** for the hot path; Postgres stays the source
   of truth. Kills the make-arm latency tail and the per-call round-trip.
4. **Alias mining.** The alias table is seeded by hand; at 10k vehicles it
   needs tooling (mine candidate surface forms from unmatched tokens,
   LLM-assisted curation, human review queue).
5. **Decision versioning.** Stamp matcher version + weights hash on every
   result so historical confidences stay reproducible as tuning evolves.

Deliberately **not** built: ORM, API service, vector DB, Elasticsearch,
fine-tuning. Each would contradict the cost/complexity discipline at this
catalogue size; the pgvector recall backstop earns its place only once the
catalogue outgrows lexical recall.

## Tuning log

- Calibrator margin buckets and the ≥2-unstated-attributes penalty were set to
  hit the four README anchors exactly; no tuning against the other 16 inputs
  (they are snapshot-locked, not targets).
- `badge_fuzzy_floor` 0.8 → 0.85 after observing GT/GTS cross-crediting.
- Token-arm similarity switched to strict word similarity (see design
  decisions) after "Ford Ranger XLT Dual Cab" retrieved Camry candidates.
