# Phase 1 — Job Collection Foundation

This phase builds one thing: a command that reads a list of companies, fetches
their public job postings, stores them in SQLite without duplicates, and records
what happened. No frontend, no AI, no auto-apply.

## 1. What a collector is

A **collector** is a small class that knows how to talk to exactly one job board
API and nothing else. `GreenhouseCollector` knows the Greenhouse URL and the
shape of a Greenhouse posting. `LeverCollector` knows Lever's. A collector:

- makes one HTTP request,
- turns the response into a list of `Job` objects,
- returns them.

It never touches the database, and it never decides whether a job is a good
match. That keeps each collector small enough to read in one sitting and easy to
test with a fake HTTP client.

## 2. Why normalization is necessary

Every ATS invents its own field names for the same ideas:

| Idea          | Greenhouse       | Ashby              | Lever                    |
| ------------- | ---------------- | ------------------ | ------------------------ |
| Job title     | `title`          | `title`            | `text`                   |
| Location      | `location.name`  | `location`         | `categories.location`    |
| Apply link    | `absolute_url`   | `applyUrl`         | `hostedUrl`              |
| Board token   | (from config)    | (from config)      | (from config)            |
| Posted time   | `first_published`| `publishedAt`      | `createdAt` (epoch ms)   |
| Last modified | `updated_at`     | `updatedAt`        | *(not documented)*       |
| Description   | escaped HTML     | `descriptionHtml`  | `description` (HTML)     |

If those differences leaked into the database, every later feature — matching,
resume generation, the dashboard — would need `if source == "lever"` branches.
Normalization converts all of them, once, into the single `Job` model in
`backend/app/models.py`. Everything downstream reads one shape.

## 3. Why we use the adapter pattern

The adapter pattern means: define one interface, write one small implementation
per external system. Here the interface is `JobCollector.collect() -> list[Job]`
in `backend/app/collectors/base.py`.

The benefit is that the CLI does not know how many ATS platforms exist. It looks
up a collector class in the `COLLECTORS` registry, calls `collect()`, and stores
the result. Adding Workday later changes one new file plus one registry line —
no changes to the database, the CLI, or the tests for the other sources.

## 4. How the unique key prevents duplicates

Each scan re-fetches every job that is still open, so the same posting arrives
again and again. The `unique_key` property answers "have I seen this exact
posting before?":

```text
unique_key = f"{source}:{source_identifier}:{external_id}".lower()
```

`external_id` is the ATS's own job id, stable for the life of the posting.
`source_identifier` is the board/site token from config — the Greenhouse
board token, Ashby board name, or Lever site name. Both are part of a job's
identity because they name the actual board the posting lives on.

**`company` is deliberately excluded.** It is a human-editable display name,
not part of the board's identity — renaming "Adobe" to "Adobe Inc." in
`sources.json` must not create a second copy of every one of its jobs. Title,
location, and description are excluded for the same underlying reason: they
change over time (a role gets renamed, a location gets added) and none of
that describes *which* job this is.

The key is stored in the `jobs` table with a `UNIQUE` constraint, which makes
duplicates impossible at the database level, not just in Python. Each part is
stripped and lowercased before joining, so incidental casing differences in
config don't split one job into two rows.

Note: `source_identifier` itself is still an identity field — if you actually
move a company to a new board (a real re-platforming), its jobs will show up
as new. That's correct: it *is* a new board.

## 5. `posted_at`, `source_updated_at`, `first_seen_at`, `last_seen_at`

| Field                | Who decides it    | Meaning                                                  |
| -------------------- | ----------------- | --------------------------------------------------------- |
| `posted_at`          | The company / ATS | Original publish time, set **only** when the source clearly documents a field as the publish date. `None` otherwise. |
| `source_updated_at`  | The company / ATS | The source's own "last modified" timestamp, when it documents one. Not a publish date. |
| `first_seen_at`      | ApplyOps           | The first scan in which we ever saw this job.             |
| `last_seen_at`       | ApplyOps           | The most recent successful scan in which the job was still listed. |

These are four different questions, and conflating them produces wrong
answers:

- `posted_at` tells you how fresh the role is — *if* the source actually
  publishes that. Don't assume every ATS does.
- `source_updated_at` tells you the posting was edited, which is not the
  same as "recently posted." A job opened in January and re-edited in August
  has an `updated_at` from August; treating that as `posted_at` would make a
  stale role look brand new. This is why Greenhouse's `updated_at` and
  Ashby's `updatedAt` are never used as a `posted_at` fallback here — see
  each collector's module docstring for the exact per-source reasoning.
- `first_seen_at` tells you how new the job is *to you* — the thing you
  actually want to sort by when hunting for newly discovered work.
- `last_seen_at` tells you whether the job is still live: see deactivation,
  below.

When a source's field semantics aren't clearly documented, the collector sets
the value to `None` rather than guessing. Lever's public postings API has no
documented "last modified" field, so `source_updated_at` is always `None` for
Lever jobs.

All four are timezone-aware UTC datetimes, stored as ISO-8601 strings.

## 6. How the SQLite upsert works

"Upsert" = update if present, insert if not. `database.upsert_jobs()` does this
per job:

1. `SELECT id FROM jobs WHERE unique_key = ?`
2. No row → `INSERT` everything, including `first_seen_at`. Count it as **new**.
3. Row exists → `UPDATE` the mutable fields (company, title, location,
   description, application URL, `posted_at`, `source_updated_at`,
   `is_active`) **and** `last_seen_at`. The `first_seen_at` column is
   deliberately left out of the `UPDATE`, which is how the original discovery
   time survives every later scan. Count it as **updated**.

Every statement uses `?` placeholders — parameterized SQL only, never string
formatting.

## 6a. Safe job deactivation

A job that vanishes from a scan usually means the role closed. We want to
reflect that without ever deleting the row (deleting would throw away
`first_seen_at`/`last_seen_at` history) and without ever guessing wrong
because of a network hiccup.

`database.apply_scan_results(connection, jobs, source, source_identifier)`
does the upsert above and then deactivation, in one transaction:

1. Upsert every job the scan returned (inserts new ones, refreshes existing
   ones, and — because the update touches `is_active` — **reactivates** any
   job that had gone inactive and has now reappeared).
2. `UPDATE jobs SET is_active = 0 WHERE source = ? AND source_identifier = ?
   AND is_active = 1 AND unique_key NOT IN (...)` — using the exact set of
   `unique_key`s this scan returned. Scoped strictly to that source's board,
   so it can never touch another company's jobs, or the same company's jobs
   on a different board.
3. If the scan returned zero jobs, there is nothing to put in `NOT IN (...)`
   (which would be invalid SQL), so that case runs the unconditional form —
   every previously active job for that source+board is now missing, full
   stop.
4. Both steps commit together; if either fails, both roll back.

**This only ever runs after a scan has already succeeded.** The CLI calls
`apply_scan_results` from inside the `try` block, after `collect()` has
already returned successfully — so an HTTP failure, a timeout, or a
normalization exception never reaches this code at all. A source that fails
this scan keeps whatever active/inactive state its jobs already had.

## 7. Complete data flow

```text
config/sources.json
        │  load_sources()  -> validated list[SourceConfig]
        ▼
build_collector()          -> GreenhouseCollector / AshbyCollector / LeverCollector
        │  collect()
        ▼
httpx GET public ATS API   -> raise_for_status() -> JSON
        │  normalize (html_to_text, parse_timestamp, clean_text)
        ▼
list[Job]                  -> every source now has the same shape
        │  apply_scan_results()  [only reached if collect() succeeded]
        ▼
SQLite `jobs` table        -> new rows inserted, seen rows refreshed,
                               missing rows deactivated — one transaction
        │  start_scan_run() / finish_scan_run() wrap each source
        ▼
SQLite `scan_runs` table   -> counts (fetched/inserted/updated/deactivated),
                               status, error message
        ▼
terminal report            -> per-source lines + one summary line, exit code
```

One source failing is caught, written to `scan_runs` with `status = 'failed'`
and a readable error, printed, and then the scan continues with the next
source — and, per the deactivation rule above, that source's existing jobs
are left untouched. The process exits non-zero if anything failed.

## 8. How to add another ATS collector

1. Create `backend/app/collectors/<name>.py`.
2. Subclass `JobCollector`, set `source = "<name>"`, implement `collect()`:
   call `self._get_json(url, params=...)` and map each posting into a `Job`.
   Use `clean_text()` for strings, `parse_timestamp()` for dates, and
   `html_to_text()` for descriptions, so missing fields stay safe. Set
   `source_identifier=self.identifier` — it's what keeps this board's jobs
   distinct from every other board's.
3. Read that ATS's actual API docs before mapping any timestamp field. Only
   set `posted_at` from a field the source clearly documents as the original
   publish time. If a field just means "last modified," it belongs in
   `source_updated_at`, never in `posted_at`. If you can't tell what a field
   means, leave it `None` — don't guess.
4. Register the class in `COLLECTORS` in `backend/app/collectors/__init__.py`.
   It is now a valid `"type"` in the config file and the validator accepts it.
5. Add a test in `backend/tests/test_collectors.py` with a sample payload and a
   mocked client. Prefer a documented JSON endpoint; do not scrape rendered HTML,
   and never work around a login or CAPTCHA.

## 9. How to run the tests

```bash
cd backend
python -m unittest discover -v
```

Tests use `httpx.MockTransport`, temporary directories, and temporary SQLite
files. Nothing touches the network.

## 10. How to run a real scan

```bash
cd backend
cp config/sources.example.json config/sources.json
# edit config/sources.json with real board tokens, then:
python -m app.cli scan --config config/sources.json
python -m app.cli list-jobs
```

The board identifier is the token in the company's own public board URL:

```text
https://boards.greenhouse.io/COMPANY_BOARD_TOKEN -> COMPANY_BOARD_TOKEN
https://jobs.ashbyhq.com/COMPANY_ASHBY_BOARD      -> COMPANY_ASHBY_BOARD
https://jobs.lever.co/COMPANY_LEVER_SITE          -> COMPANY_LEVER_SITE
```

These are placeholders, not real company identifiers — this document doesn't
claim any specific company uses any specific board token. Look up each
company's real board URL yourself; a separate manual live smoke test is the
right way to confirm a given identifier actually works before relying on it.
`config/sources.json` is git-ignored so your private target list stays local.
