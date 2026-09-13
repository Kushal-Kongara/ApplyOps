"""Command line entry point for Phase 1 job collection.

    python -m app.cli scan --config config/sources.json
    python -m app.cli list-jobs
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, TextIO

import httpx

from app import database
from app.collectors import COLLECTORS, JobCollector
from app.config import ConfigError, SourceConfig, load_sources
from app.models import utcnow


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="ApplyOps job collection (Phase 1)."
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
