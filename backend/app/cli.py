"""Command line entry point for job collection and match scoring.

    python -m app.cli scan --config config/sources.json
    python -m app.cli list-jobs
    python -m app.cli match --profile config/profile.json
    python -m app.cli list-matches --min-score 70 --limit 25 --show-key
    python -m app.cli inspect-match --job-key <job-unique-key>
    python -m app.cli inspect-match <search-text>
    python -m app.cli applications --status shortlisted
    python -m app.cli application-update <job-unique-key> --status shortlisted
    python -m app.cli daily --profile config/profile.json
"""

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, TextIO

import httpx

from app import database
from app.applications import (
    HIGH_PRIORITY_MIN_SCORE,
    REVIEW_MIN_SCORE,
    STATUSES,
    ApplicationError,
    build_daily_queue,
    parse_datetime_arg,
    validate_status,
)
from app.collectors import COLLECTORS, JobCollector
from app.config import ConfigError, SourceConfig, load_sources
from app.matching import MatchResult, evaluate_job
from app.matching.location import MAX_LOCATION_SCORE
from app.matching.product import MAX_PRODUCT_SCORE
from app.matching.seniority import MAX_SENIORITY_SCORE
from app.matching.skills import MAX_SKILL_SCORE
from app.matching.titles import MAX_TITLE_SCORE
from app.models import utcnow
from app.profile import Profile, ProfileError, load_profile


@dataclass(slots=True)
class SourceResult:
    """What happened for one configured source during a scan."""

    company: str
    source: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    deactivated: int = 0
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


def build_collector(
    source: SourceConfig, client: httpx.Client | None = None
) -> JobCollector:
    """Create the collector adapter for one configured source."""
    collector_class = COLLECTORS[source.type]
    return collector_class(
        company=source.company, identifier=source.identifier, client=client
    )


def scan_sources(
    connection: sqlite3.Connection,
    sources: Iterable[SourceConfig],
    client: httpx.Client | None = None,
    out: TextIO = sys.stdout,
) -> list[SourceResult]:
    """Scan every configured source, storing results and reporting progress.

    A failing source is recorded and reported, then the scan moves on to the
    next source.
    """
    results: list[SourceResult] = []

    for source in sources:
        result = SourceResult(company=source.company, source=source.type)
        scan_id = database.start_scan_run(
            connection, source=source.type, company=source.company, started_at=utcnow()
        )

        try:
            # Collection happens before any database write. If this raises,
            # nothing below runs — a failed fetch/parse never deactivates
            # jobs that are, as far as we know, still live.
            jobs = build_collector(source, client=client).collect()
            inserted, updated, deactivated = database.apply_scan_results(
                connection, jobs, source=source.type, source_identifier=source.identifier
            )
        except Exception as exc:  # noqa: BLE001 - one source must not stop the scan
            result.error = describe_error(exc)
            database.finish_scan_run(
                connection, scan_id, status="failed", error_message=result.error
            )
            print(f"{result.company} / {result.source}: failed — {result.error}", file=out)
        else:
            result.fetched = len(jobs)
            result.inserted = inserted
            result.updated = updated
            result.deactivated = deactivated
            database.finish_scan_run(
                connection,
                scan_id,
                status="success",
                fetched=result.fetched,
                inserted=inserted,
                updated=updated,
                deactivated=deactivated,
            )
            line = (
                f"{result.company} / {result.source}: {result.fetched} fetched, "
                f"{inserted} new, {updated} updated"
            )
            if deactivated:
                line += f", {deactivated} deactivated"
            print(line, file=out)

        results.append(result)

    return results


def describe_error(exc: Exception) -> str:
    """Turn an exception into a short, useful one-line message."""
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            f"HTTP {exc.response.status_code} from {exc.request.url}"
        )
    if isinstance(exc, httpx.TimeoutException):
        return f"request timed out ({type(exc).__name__})"
    if isinstance(exc, httpx.HTTPError):
        return f"{type(exc).__name__}: {exc}".strip(": ")

    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def print_summary(results: Sequence[SourceResult], out: TextIO = sys.stdout) -> None:
    """Print the closing one-line summary of a scan."""
    new = sum(r.inserted for r in results)
    updated = sum(r.updated for r in results)
    deactivated = sum(r.deactivated for r in results)
    failed = sum(1 for r in results if r.failed)

    line = f"Scan complete: {new} new jobs, {updated} updated"
    if deactivated:
        line += f", {deactivated} deactivated"
    if failed:
        noun = "source" if failed == 1 else "sources"
        line += f", {failed} {noun} failed"
    print(line, file=out)


@dataclass(slots=True)
class MatchSummary:
    """What happened when scoring all active jobs against one profile."""

    total: int = 0
    filtered: int = 0
    scored: int = 0
    high_score: int = 0  # scored (not filtered) jobs at or above HIGH_SCORE_THRESHOLD


HIGH_SCORE_THRESHOLD = 70


def _store_match(connection: sqlite3.Connection, match: MatchResult) -> None:
    """Persist one `MatchResult`. Thin glue so `database` never imports `matching`."""
    database.upsert_match(
        connection,
        job_unique_key=match.job_unique_key,
        profile_id=match.profile_id,
        total_score=match.total_score,
        title_score=match.components.title,
        skills_score=match.components.skills,
        location_score=match.components.location,
        seniority_score=match.components.seniority,
        product_score=match.components.product,
        matched_skills=match.matched_skills,
        unmatched_skills=match.unmatched_skills,
        skill_evidence=match.skill_evidence,
        title_evidence=match.title_evidence,
        location_evidence=match.location_evidence,
        seniority_evidence=match.seniority_evidence,
        product_evidence=match.product_evidence,
        visa_signal=match.visa.status,
        visa_evidence=match.visa.evidence,
        filtered=match.filter_result.filtered,
        filter_reason=match.filter_result.reason,
        scored_at=match.scored_at,
    )


def match_jobs(
    connection: sqlite3.Connection, profile: Profile, out: TextIO = sys.stdout
) -> MatchSummary:
    """Score every active job against `profile` and store the results.

    Filtering and scoring both always run — a filtered job is still scored
    and stored, just flagged, so its score stays inspectable later.
    """
    summary = MatchSummary()

    for job in database.get_active_jobs(connection):
        match = evaluate_job(job, profile)
        _store_match(connection, match)

        summary.total += 1
        if match.filter_result.filtered:
            summary.filtered += 1
        else:
            summary.scored += 1
            if match.total_score >= HIGH_SCORE_THRESHOLD:
                summary.high_score += 1

    print(
        f"Matched {summary.total} active job(s) against profile '{profile.profile_id}': "
        f"{summary.scored} scored, {summary.filtered} filtered out.",
        file=out,
    )
    if summary.scored:
        print(f"  {summary.high_score} job(s) scored {HIGH_SCORE_THRESHOLD}+.", file=out)

    return summary


def format_match_line(row: sqlite3.Row, show_key: bool = False) -> str:
    """Render one scored job the way `list-matches` prints it."""
    matched_skills = json.loads(row["matched_skills"])
    location = row["location"] or "location unknown"

    lines = [
        f"{row['total_score']:>3}  {row['title']} — {row['company']}",
        f"    {location} | {row['source']}",
        (
            f"    Title {row['title_score']}/{MAX_TITLE_SCORE} | "
            f"Skills {row['skills_score']}/{MAX_SKILL_SCORE} | "
            f"Location {row['location_score']}/{MAX_LOCATION_SCORE} | "
            f"Seniority {row['seniority_score']}/{MAX_SENIORITY_SCORE} | "
            f"Product {row['product_score']}/{MAX_PRODUCT_SCORE}"
        ),
        f"    Visa: {row['visa_signal']}",
    ]
    if matched_skills:
        lines.append(f"    Matched: {', '.join(matched_skills)}")
    if show_key:
        lines.append(f"    Key: {row['job_unique_key']}")
    return "\n".join(lines)


def _cmd_scan(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    try:
        sources = load_sources(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    connection = database.connect(args.db)
    try:
        results = scan_sources(connection, sources, out=out)
        print_summary(results, out=out)
    finally:
        connection.close()

    return 1 if any(r.failed for r in results) else 0


def _cmd_list_jobs(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    connection = database.connect(args.db)
    try:
        rows = database.list_jobs(connection, limit=args.limit, active_only=not args.all)
    finally:
        connection.close()

    if not rows:
        print("No jobs stored yet. Run a scan first.", file=out)
        return 0

    for row in rows:
        print(
            f"[{row['source']}] {row['company']} — {row['title']}"
            f" ({row['location'] or 'location unknown'})",
            file=out,
        )
        print(f"    first seen {row['first_seen_at']}  last seen {row['last_seen_at']}", file=out)
        if row["application_url"]:
            print(f"    {row['application_url']}", file=out)

    print(f"\n{len(rows)} job(s) shown.", file=out)
    return 0


def _cmd_match(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"Profile error: {exc}", file=sys.stderr)
        return 2

    connection = database.connect(args.db)
    try:
        match_jobs(connection, profile, out=out)
    finally:
        connection.close()

    return 0


def _cmd_list_matches(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"Profile error: {exc}", file=sys.stderr)
        return 2

    connection = database.connect(args.db)
    try:
        rows = database.list_matches(
            connection, profile.profile_id, min_score=args.min_score, limit=args.limit
        )
    finally:
        connection.close()

    if not rows:
        print("No matches at or above that score. Run `match` first.", file=out)
        return 0

    print("\n\n".join(format_match_line(row, show_key=args.show_key) for row in rows), file=out)
    print(f"\n{len(rows)} job(s) shown.", file=out)
    return 0


def _cmd_inspect_match(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    query = args.job_key or args.job
    if not query:
        print("Provide a job key with --job-key, or search text as a positional argument.", file=sys.stderr)
        return 2

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"Profile error: {exc}", file=sys.stderr)
        return 2

    connection = database.connect(args.db)
    try:
        row = database.get_match(connection, query, profile.profile_id)
        if row is None and not args.job_key:
            # Not an exact key — try it as a title/company search instead.
            candidates = database.list_matches(
                connection, profile.profile_id, min_score=0, limit=10_000, include_filtered=True
            )
            needle = query.lower()
            matches = [
                r for r in candidates
                if needle in r["title"].lower() or needle in r["company"].lower()
            ]
            if len(matches) == 1:
                row = matches[0]
            elif len(matches) > 1:
                print(f"'{query}' matches {len(matches)} jobs — be more specific, or use a job's "
                      "exact key with --job-key:", file=out)
                for candidate in matches:
                    print(f"  {candidate['job_unique_key']}  {candidate['title']} — {candidate['company']}", file=out)
                return 1
    finally:
        connection.close()

    if row is None:
        print(f"No scored job found matching '{query}'. Run `match` first.", file=out)
        return 1

    print(_format_inspection(row, profile), file=out)
    return 0


def _format_inspection(row: sqlite3.Row, profile: Profile) -> str:
    """Full, human-readable breakdown of one job's score — for `inspect-match`."""
    matched = json.loads(row["matched_skills"])
    unmatched = json.loads(row["unmatched_skills"])
    skill_evidence = json.loads(row["skill_evidence"])
    product_evidence = json.loads(row["product_evidence"])

    primary_set = set(profile.primary_skills)
    matched_primary = [s for s in matched if s in primary_set]
    matched_secondary = [s for s in matched if s not in primary_set]
    unmatched_primary = [s for s in unmatched if s in primary_set]
    unmatched_secondary = [s for s in unmatched if s not in primary_set]

    lines = [
        f"{row['title']} — {row['company']} ({row['source']})",
        f"{row['location'] or 'location unknown'} | {row['application_url']}",
        f"Key: {row['job_unique_key']}",
        "",
        f"Total score: {row['total_score']}/100",
    ]
    if row["filtered"]:
        lines.append(f"FILTERED OUT: {row['filter_reason']}")
    lines += [
        "",
        f"Title     {row['title_score']:>3}/{MAX_TITLE_SCORE}  — {row['title_evidence']}",
        f"Skills    {row['skills_score']:>3}/{MAX_SKILL_SCORE}",
        f"  matched primary:     {', '.join(matched_primary) or '(none)'}",
        f"  matched secondary:   {', '.join(matched_secondary) or '(none)'}",
        f"  unmatched primary:   {', '.join(unmatched_primary) or '(none)'}",
        f"  unmatched secondary: {', '.join(unmatched_secondary) or '(none)'}"
        f"  (profile skills not found in this posting, not requirements it lacks)",
    ]
    if skill_evidence:
        lines.append(f"  evidence:            {'; '.join(skill_evidence)}")
    lines += [
        f"Location  {row['location_score']:>3}/{MAX_LOCATION_SCORE}  — {row['location_evidence']}",
        f"Seniority {row['seniority_score']:>3}/{MAX_SENIORITY_SCORE}  — {row['seniority_evidence']}",
        f"Product   {row['product_score']:>3}/{MAX_PRODUCT_SCORE}  — {', '.join(product_evidence) or '(no evidence found)'}",
        "",
        f"Visa signal: {row['visa_signal']}",
    ]
    if row["visa_evidence"]:
        lines.append(f"  evidence: \"{row['visa_evidence']}\"")
    lines.append(f"Scored at: {row['scored_at']}")

    return "\n".join(lines)


def _cmd_applications(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    if args.status is not None:
        try:
            validate_status(args.status)
        except ApplicationError as exc:
            print(f"Application error: {exc}", file=sys.stderr)
            return 2

    connection = database.connect(args.db)
    try:
        rows = database.list_applications(connection, status=args.status, limit=args.limit)
    finally:
        connection.close()

    if not rows:
        print("No tracked applications yet. Use `application-update` to start tracking one.", file=out)
        return 0

    for row in rows:
        lines = [
            f"[{row['status']}] {row['title']} — {row['company']} ({row['location'] or 'location unknown'})",
            f"    key: {row['job_unique_key']}",
            f"    last action: {row['last_action_at']}",
        ]
        if row["applied_at"]:
            lines.append(f"    applied: {row['applied_at']}")
        if row["next_follow_up_at"]:
            lines.append(f"    next follow-up: {row['next_follow_up_at']}")
        if row["notes"]:
            lines.append(f"    notes: {row['notes']}")
        print("\n".join(lines), file=out)
        print(file=out)

    print(f"{len(rows)} application(s) shown.", file=out)
    return 0


def _cmd_application_update(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    connection = database.connect(args.db)
    try:
        if database.get_job(connection, args.job_key) is None:
            print(f"No job found with key '{args.job_key}'.", file=sys.stderr)
            return 2

        # Only fields the user actually passed are included, so anything
        # omitted keeps its existing value — `upsert_application`'s default
        # ("leave unchanged") only kicks in for a keyword that's absent.
        updates: dict = {}
        try:
            if args.status is not None:
                updates["status"] = validate_status(args.status)
            if args.notes is not None:
                updates["notes"] = args.notes
            if args.applied_at is not None:
                updates["applied_at"] = parse_datetime_arg(args.applied_at)
            if args.clear_follow_up:
                updates["next_follow_up_at"] = None
            elif args.next_follow_up_at is not None:
                updates["next_follow_up_at"] = parse_datetime_arg(args.next_follow_up_at)
        except ApplicationError as exc:
            print(f"Application error: {exc}", file=sys.stderr)
            return 2

        created = database.upsert_application(connection, args.job_key, **updates)
        row = database.get_application(connection, args.job_key)
    finally:
        connection.close()

    verb = "Created" if created else "Updated"
    print(f"{verb} application for '{args.job_key}': status={row['status']}", file=out)
    return 0


def _cmd_daily(args: argparse.Namespace, out: TextIO | None = None) -> int:
    out = out or sys.stdout

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"Profile error: {exc}", file=sys.stderr)
        return 2

    connection = database.connect(args.db)
    try:
        queue = build_daily_queue(connection, profile.profile_id)
    finally:
        connection.close()

    if queue.is_empty:
        print("Nothing actionable right now.", file=out)
        return 0

    if queue.high_priority:
        print(f"=== High priority ({HIGH_PRIORITY_MIN_SCORE}+) ===\n", file=out)
        print("\n\n".join(_format_daily_item(item) for item in queue.high_priority), file=out)
        print(file=out)

    if queue.review:
        print(f"=== Review candidates ({REVIEW_MIN_SCORE}-{HIGH_PRIORITY_MIN_SCORE - 1}) ===\n", file=out)
        print("\n\n".join(_format_daily_item(item) for item in queue.review), file=out)
        print(file=out)

    if queue.follow_ups:
        print("=== Follow-ups due ===\n", file=out)
        print("\n\n".join(_format_daily_item(item) for item in queue.follow_ups), file=out)
        print(file=out)

    total = len(queue.high_priority) + len(queue.review) + len(queue.follow_ups)
    print(f"{total} item(s) in today's queue.", file=out)
    return 0


def _format_daily_item(item) -> str:
    """Render one `DailyItem` the way `daily` prints it."""
    label = "NEW" if item.kind == "new" else "FOLLOW-UP"
    score = f"{item.total_score}" if item.total_score is not None else "?"

    lines = [
        f"[{label}] {score:>3}  {item.title} — {item.company}",
        f"    {item.location or 'location unknown'} | status: {item.status}",
        f"    {item.application_url}",
    ]
    if item.visa_signal:
        lines.append(f"    Visa: {item.visa_signal}")
    if item.matched_skills:
        lines.append(f"    Matched: {', '.join(item.matched_skills)}")
    if item.kind == "follow_up" and item.next_follow_up_at is not None:
        lines.append(f"    Follow-up was due: {item.next_follow_up_at.date().isoformat()}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="ApplyOps job collection and match scoring."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Collect jobs from every configured source.")
    scan_parser.add_argument(
        "--config",
        default="config/sources.json",
        type=Path,
        help="Path to the sources JSON file (default: config/sources.json).",
    )
    scan_parser.add_argument(
        "--db",
        default=database.DEFAULT_DB_PATH,
        type=Path,
        help=f"SQLite database path (default: {database.DEFAULT_DB_PATH}).",
    )
    scan_parser.set_defaults(handler=_cmd_scan)

    list_parser = subparsers.add_parser("list-jobs", help="Show stored jobs.")
    list_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    list_parser.add_argument("--limit", default=50, type=int, help="Maximum jobs to show.")
    list_parser.add_argument(
        "--all", action="store_true", help="Include jobs that are no longer active."
    )
    list_parser.set_defaults(handler=_cmd_list_jobs)

    match_parser = subparsers.add_parser(
        "match", help="Score every active job against a profile and store the results."
    )
    match_parser.add_argument(
        "--profile",
        default="config/profile.json",
        type=Path,
        help="Path to the profile JSON file (default: config/profile.json).",
    )
    match_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    match_parser.set_defaults(handler=_cmd_match)

    list_matches_parser = subparsers.add_parser("list-matches", help="Show scored jobs.")
    list_matches_parser.add_argument("--profile", default="config/profile.json", type=Path)
    list_matches_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    list_matches_parser.add_argument(
        "--min-score", default=0, type=int, help="Only show jobs scoring at least this much."
    )
    list_matches_parser.add_argument("--limit", default=25, type=int, help="Maximum jobs to show.")
    list_matches_parser.add_argument(
        "--show-key", action="store_true", help="Also print each job's unique key (to copy into inspect-match)."
    )
    list_matches_parser.set_defaults(handler=_cmd_list_matches)

    inspect_parser = subparsers.add_parser(
        "inspect-match", help="Show the full score breakdown for one job."
    )
    inspect_parser.add_argument(
        "job", nargs="?", default=None, help="Text to search title/company for (ignored if --job-key is given)."
    )
    inspect_parser.add_argument("--job-key", default=None, help="A job's exact unique key.")
    inspect_parser.add_argument("--profile", default="config/profile.json", type=Path)
    inspect_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    inspect_parser.set_defaults(handler=_cmd_inspect_match)

    applications_parser = subparsers.add_parser("applications", help="Show tracked applications.")
    applications_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    applications_parser.add_argument(
        "--status", default=None, help="Only show applications in this status."
    )
    applications_parser.add_argument("--limit", default=100, type=int, help="Maximum applications to show.")
    applications_parser.set_defaults(handler=_cmd_applications)

    update_parser = subparsers.add_parser(
        "application-update", help="Create or update one job's tracked application."
    )
    update_parser.add_argument("job_key", help="The job's exact unique key (see `list-matches --show-key`).")
    update_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    update_parser.add_argument("--status", default=None)
    update_parser.add_argument(
        "--applied-at", default=None, help="Date/datetime this was applied to (YYYY-MM-DD or ISO-8601)."
    )
    update_parser.add_argument(
        "--next-follow-up-at", default=None, help="Date/datetime to follow up (YYYY-MM-DD or ISO-8601)."
    )
    update_parser.add_argument(
        "--clear-follow-up", action="store_true", help="Clear any scheduled follow-up date."
    )
    update_parser.add_argument("--notes", default=None, help="Replace this application's notes.")
    update_parser.set_defaults(handler=_cmd_application_update)

    daily_parser = subparsers.add_parser(
        "daily", help="Show today's actionable jobs: high-priority matches, review candidates, and due follow-ups."
    )
    daily_parser.add_argument("--profile", default="config/profile.json", type=Path)
    daily_parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    daily_parser.set_defaults(handler=_cmd_daily)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
