# Phase 2 — Deterministic Job Filtering and Match Scoring

Phase 1 collects every public posting from configured companies — currently
well over a thousand jobs. Phase 2 turns that pile into a small, ranked
shortlist, using nothing but keyword rules: no AI, no embeddings, no network
calls. Every point in a score can be traced back to a specific rule in
`backend/app/matching/`.

## 1. Why deterministic scoring comes before AI

Sending 1,000+ jobs to an LLM on every scan is slow, costly, and — worse —
opaque: if a model says a job is a 90% match, you can't easily ask *why*.
Phase 2 exists to do the cheap, obvious filtering first:

- most of the 1,196 jobs in the local database aren't engineering roles at
  all (Account Executive, General Counsel, Business Development...) —
  no AI is needed to know that,
- the ones that are clearly a poor fit for a profile with ~4 years of
  experience wanting full-stack/founding-engineer work in the Bay Area — a
  Staff role in Singapore requiring a security clearance — can be scored
  without a network call,
- everything left over is a much smaller list a future AI-matching phase
  can spend its budget on.

Every score component is a rule you can read in plain Python. That
transparency is the whole point: you can tell exactly why a job scored 65
instead of 90, and fix the rule if it's wrong. An LLM score, by contrast, is
a black box until you ask it to explain itself — and even then, its
explanation is a guess about its own reasoning, not the reasoning itself.

## 2. Filtering versus scoring

These are two different questions, evaluated independently, and Phase 2
keeps them that way on purpose:

- **Filtering** asks "is this even a candidate role family?" — a yes/no
  gate on unambiguous evidence. A job titled "Marketing Intern" is not an
  engineering role at any score; there's no point computing one.
- **Scoring** asks "given that this is a plausible role, how well does it
  fit?" — a graded, explainable 0-100.

A job that gets filtered is **still scored** — `evaluate_job()` always runs
every scoring component, and `evaluate_filters()` runs independently. Both
results are stored on the same row. This means a job that got hard-excluded
for an unrelated reason (say, a title matched an excluded term you didn't
mean to exclude so broadly) still has a visible score, so you can catch a
too-aggressive filter instead of it silently disappearing.

Hard filtering only fires on strong, unambiguous signals:

- a title matching one of the profile's `excluded_title_terms` (intern,
  new grad, engineering manager, director, VP, ...),
- a title with no engineering/developer signal at all (Account Executive,
  General Counsel, Business Development Manager...).

Everything softer is left to scoring, which can rank a job low without
erasing it:

- an unknown location,
- missing profile skills,
- unknown visa/sponsorship information,
- a title that merely contains "Senior."

## 3. Every scoring component

`evaluate_job(job, profile)` in `app/matching/scorer.py` combines five
independently-testable components into a 0-100 total:

| Component  | Max | Module                     | What it rewards |
| ---------- | --- | -------------------------- | ---------------- |
| Title      | 35  | `app/matching/titles.py`   | How specifically the title matches — exact configured title, a specific wanted family, only the generic "Software Engineer," or just a plausible engineering title — minus a small deduction per extra qualifier word. |
| Skills     | 30  | `app/matching/skills.py`   | Primary skills matched (weighted 4x a secondary skill), each tier scored against its *own* list size — not the whole profile at once. |
| Location   | 15  | `app/matching/location.py` | Bay Area > clearly-US-remote > another US city (if relocation is allowed) > unknown > clearly international. |
| Seniority  | 10  | `app/matching/seniority.py`| How close the posting's stated experience requirement is to the profile's ~4 years; an *absent* requirement scores neutrally, not as a confirmed fit. |
| Product/AI | 10  | `app/matching/product.py`  | Breadth of evidence — from title or description — for AI/applied-AI roles, agents, LLMs/RAG, generative AI/ChatGPT, customer-facing product work, startup/founding environment, forward-deployed/enterprise deployment. |

`ScoreComponents.total` sums these and clamps to `[0, 100]` — by
construction the components alone can never leave that range (they're each
individually capped), but the clamp is there so a bug in one component can
never silently push the total out of bounds (see the test suite's
"never below 0 or above 100" tests).

### Title (35)

An earlier version gave every title that touched a wanted family the same
flat 35 — twenty different roles scored identically, and a title's team or
product name ("Enterprise", "Data Acquisition") could shove a genuinely
strong match down to a generic-looking one for no real reason. The current
version scores on a continuous scale within five documented bands:

| Band                                | Points | Trigger |
| ------------------------------------ | ------ | --------------------------------------------- |
| Exact configured target title       | 35     | normalized title == a target title, verbatim   |
| Strong alias / closely related      | 23-34  | a specific wanted family matches (full-stack, founding engineer, forward deployed, applied AI, ...) |
| Generic "Software Engineer"         | 15-22  | only the generic family matches, not a specific one |
| Weak but plausible adjacent title   | 8-14   | a bare engineering word, no family match at all |
| Unrelated                           | 0      | none of the above (normally already hard-filtered) |

Within the "strong alias" band, each extra **qualifier word** — anything in
the title beyond the matched family phrase and generic connectors like
"engineer" or "of" — subtracts a point, but the band has a floor (23) a
qualifier can never cross: "Full-Stack SWE, Data Acquisition (Foundations)"
still lands solidly in-band rather than falling to "generic." That's the
literal fix for "qualifiers must not destroy an otherwise strong match" —
department, team, and product names are exactly what qualifiers are.

### Skills (30)

An earlier version scored `matched / len(all profile skills)`, which
punished a job for not mentioning a niche tool (Vapi, ElevenLabs) exactly as
hard as for missing a core one (React, Python) — a posting naming every
skill that actually mattered still scored ~6/30 because the profile also
listed twenty other tools it was never going to mention.

The profile now splits skills into `primary_skills` and `secondary_skills`,
and each tier is scored against its *own* list size, then combined with
fixed weights:

```text
points = round(24 * (primary matched / len(primary_skills))
             +  6 * (secondary matched / len(secondary_skills)))
```

(`PRIMARY_CAP=24`, `SECONDARY_CAP=6`, an 80/20 split of the 30-point
component.) A posting matching every primary skill and nothing else still
scores 24/30 — strong credit — regardless of how long the secondary list is.
As before, each skill counts once no matter how many of its aliases appear
or how many times it's mentioned, via the alias tables described below.
JavaScript and TypeScript (or React and Node.js) can both live in the skill
lists even though they overlap conceptually — that's not a double-count,
since each is checked and scored independently as its own real skill.

### Location (15)

Five buckets, from `app/matching/location.py`:

- **Primary** (Bay Area city, or "Bay Area" itself): full credit.
- **Remote, clearly US** ("US - Remote", "Remote (United States)"): full
  credit, if `allow_remote_us` is true.
- **Other US city** ("Austin, TX", "New York City"): partial credit, if
  `allow_relocation_us` is true; otherwise 0.
- **Unknown** (blank, "Hybrid", "Distributed" — extremely common in real
  ATS data): low partial credit, never zero.
- **Clearly international** ("London, UK", "Singapore", "India - Remote"):
  zero.

### Seniority (10)

The profile is roughly 4 years of experience. Extraction
(`extract_experience_years`) tries five ordered, readable regex patterns —
a range ("2-5 years" / "3–5 years"), "at least"/"minimum of" phrasing, "or
more" phrasing, an open-ended minimum ("7+ years"), then a single number
("5 years of experience") — rather than one fragile all-in-one pattern.
Written numbers ("five years", "seven or more years") are converted to
digits first, so every pattern only ever has to handle numerals.

When a posting has more than one number that could be a years-of-experience
mention, extraction prefers whichever one appears near a word like
"experience", "professional", or "industry" — a bare number without that
context (e.g. "founded in 2015," or a phrase that only incidentally
contains "year") is much less likely to be an actual requirement, and is
used only if nothing better is found.

Classification combines the extracted range with title-level words:

- **Strong** (10): roughly 2-4 years, clearly stated.
- **Partial** (6): title says "Senior", or the posting asks for 5-6 years.
- **Low** (2): a staff/principal/architect/manager-level title, or 7+ years.
- **Neutral** (6): no usable experience evidence at all. This is
  deliberately equal to "partial," not "strong" — an absent requirement
  isn't evidence the role fits the profile's experience, so it must not be
  scored as if it were confirmed.

### Product / AI relevance (10)

Eight evidence categories, each covering a distinct kind of signal — AI
role (AI engineer / applied AI), AI agents / agentic systems, LLMs / RAG,
generative AI / ChatGPT, customer-facing product, product ownership
(0-to-1 / full-stack), startup / founding environment, and
forward-deployed / enterprise deployment — searched over **title +
description together**, 2 points each, capped at 10. A title alone saying
"AI Engineer," "Applied AI," "Agent Enablement," or "ChatGPT" is real
evidence and scores on its own, without needing the description to repeat
it. Matching more than one phrase within the same category still only
counts once — this rewards *breadth* of relevant evidence, not how many
synonyms happened to appear.

## 4. How aliases work

Every alias table lives in `app/matching/aliases.py`, already run through
`normalize_text()` (lowercase, accents stripped, punctuation turned to
single spaces). A phrase search then uses `\b` word boundaries
(`contains_phrase()` in `app/matching/text.py`), which is what keeps
matching honest:

- "full-stack", "full stack", and "fullstack" are three spellings of one
  alias group, so all three count as the same family.
- "AI" matches "AI Engineer" but not "email" — `\bai\b` requires a
  transition to/from a non-word character on both sides.
- "Java" matches "Java Developer" but not "JavaScript" — there's no
  boundary between the "a" and the "s" in "javascript".
- "Node.js" is fused to "nodejs" *before* punctuation is stripped
  (`normalize_text`'s `.js`-suffix rule), specifically so it doesn't turn
  into two words ("node", "js") and accidentally trip JavaScript's own "JS"
  alias.

A profile skill without a curated alias list still works — it falls back to
its own normalized name as its only alias, so adding an unusual skill to
`profile.json` never requires a code change.

## 5. Why visa status is separate from score

`detect_visa_signal()` in `app/matching/visa.py` never touches the score.
It reports one of `unknown` / `sponsorship_available` / `sponsorship_risk` /
`citizenship_or_clearance_required`, based only on explicit phrasing ("We
do not provide sponsorship", "US citizen only", "Active security clearance
required", explicit sponsorship-available language). A generic "must be
authorized to work in the United States" sentence — extremely common, and
compatible with plenty of visa situations — matches none of these patterns
and stays `unknown`.

Baking a guess about sponsorship into the score would let one ambiguous
sentence silently sink or inflate a job's rank. Keeping it a separate,
evidence-only field means a scored job can be sorted purely on fit, and the
visa signal — with its actual matched text stored as evidence, never an
invented conclusion — is available alongside it for a human to weigh
however they choose.

## 6. How to adjust personal preferences

Everything a person would want to tune lives in `backend/config/profile.json`
(copy `profile.example.json` to start) — no code changes needed for:

- `target_titles` / `excluded_title_terms` — which role families to
  chase or hard-exclude,
- `primary_locations`, `allow_remote_us`, `allow_relocation_us` — location
  preference,
- `primary_skills` / `secondary_skills` — anything can go here, curated
  alias or not; put the skills that matter most in `primary_skills`,
  everything else in `secondary_skills`,
- `years_experience` — shifts the seniority bands (see above) to match.

Adding a genuinely new *kind* of signal (a new title family, a new skill
alias, a new location marker) means editing `app/matching/aliases.py` — it's
a data file, not scoring logic.

## 7. How to run matching

```bash
cd backend
cp config/profile.example.json config/profile.json   # first time only
# edit config/profile.json to taste

python -m app.cli match --profile config/profile.json
python -m app.cli list-matches --min-score 70 --limit 25 --show-key
```

`match` scores every currently-active job and stores the result — rerunning
it (e.g. after a new scan, or after editing the profile) updates each job's
row in place rather than piling up duplicate rows, because `job_matches` has
a `UNIQUE (job_unique_key, profile_id)` constraint.

## 8. How to inspect a score

```bash
python -m app.cli inspect-match --job-key "greenhouse:acme:12345"
# or search by title/company text if you don't have the exact key:
python -m app.cli inspect-match "full stack"
```

`list-matches --show-key` prints each job's exact key so it can be copied
straight into `--job-key`. Prints the full breakdown: every component's
points and evidence, matched/unmatched skills split by primary vs.
secondary tier, the visa signal and its matched text (if any), and the
filter status/reason if the job was hard-excluded.

## 9. Known limitations of keyword matching

- **Small, finite gazetteers, not a geocoder.** `US_LOCATION_MARKERS` and
  `INTERNATIONAL_LOCATION_MARKERS` list specific city/state/country names —
  real, but not exhaustive. An unlisted city falls back to "unknown," which
  still scores low-but-nonzero, never zero — the failure mode is
  conservative, not wrong-and-confident.
- **Some aliases are inherently ambiguous.** "Node" alone (an explicitly
  requested alias) could theoretically match unrelated text about a
  "compute node." In practice this is rare in job description prose, and
  the cost of a false positive here is a slightly inflated skill count, not
  a wrong hard filter.
- **A word-boundary match isn't a semantic one.** "Java Developer" and
  "JavaScript Developer" are correctly told apart, but keyword matching
  can't tell "5 years of React, but we'll train the right person" from a
  hard requirement — it only sees the words present.
- **The engineering-title gate is intentionally blunt.** Any title without
  "engineer"/"engineering"/"developer"/"programmer"/"swe" is hard-filtered
  as outside the target role families. This correctly clears out sales,
  legal, and marketing titles, but would also filter a genuinely relevant
  role with an unconventional title (e.g. "Builder" at a very informal
  startup) — a rare miss, traded for reliably clearing the much larger
  number of clearly-irrelevant titles.

## 10. What the DGX will improve in a later phase

Phase 2 is deliberately shallow: it can't read a job description the way a
person would. A later phase that runs local inference on the DGX can use
this phase's shortlist (not the full 1,000+ jobs) to do the parts keyword
matching structurally can't:

- judge whether the *specific* responsibilities in a description actually
  fit the candidate's real experience, not just whether the right nouns
  appear,
- reconcile softer, implicit signals ("we move fast," "wear many hats")
  that don't reduce to a keyword,
- write a tailored summary of *why* a specific job is a good fit, in
  natural language, grounded in the deterministic score and evidence this
  phase already computed.

Because Phase 2 already did the cheap, obvious elimination, the DGX only
ever has to reason about a shortlist — not the full firehose of collected
jobs.
