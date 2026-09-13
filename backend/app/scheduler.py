"""Runs `app.refresh.refresh_from_files` on a wall-clock 2-hour cadence.

    python -m app.scheduler

Behavior:

- Runs one refresh immediately on startup, then sleeps until the next
  even wall-clock 2-hour mark (00:00, 02:00, 04:00, ... 22:00) **in the
  local timezone** the process is running in — not "2 hours after
  whenever this process happened to start." If you start it at 09:47, the
  first scheduled refresh after the startup one lands at 10:00, not
  11:47.
- Never overlaps itself: this is a single synchronous loop, so the next
  cycle's boundary is computed only *after* the previous refresh has
  fully finished. If a refresh somehow ran long enough to pass one or
  more boundaries, the next one computed is still the first one strictly
  in the future — a missed boundary is skipped, never queued up to fire
  immediately after.
- A manual `python -m app.cli refresh` run at the same time is handled by
  `refresh_from_files`'s own file lock (see `app/refresh.py`), not by
  anything in this module — the scheduler and the CLI both just call the
  same locked entry point.
- This process only refreshes while it is running. If the machine sleeps,
  loses power, or the process is killed, refreshes stop until it's
  started again — there is no persistence of "missed" runs, and no
  always-on cloud component in this phase.

No APScheduler/Celery/cron dependency — this is a single-user local tool,
and "sleep until the next boundary, run once, repeat" is the entire
scheduling requirement.
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from app import database, refresh
from app.config import ConfigError
from app.profile import ProfileError

DEFAULT_INTERVAL_HOURS = 2


def next_boundary(now: datetime, interval_hours: int = DEFAULT_INTERVAL_HOURS) -> datetime:
    """The next wall-clock multiple of `interval_hours`, strictly after `now`.

    Computed in whatever timezone `now` carries — pass a local-time `now`
    for local wall-clock boundaries (00:00, 02:00, ...), which is what the
    scheduler loop below does. `now` must be timezone-aware.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_since_midnight = (now - midnight).total_seconds() / 3600
    next_multiple = (int(hours_since_midnight // interval_hours) + 1) * interval_hours
    return midnight + timedelta(hours=next_multiple)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def run_scheduler(
    *,
    db_path: str | Path = database.DEFAULT_DB_PATH,
    sources_path: str = "config/sources.json",
    profile_path: str = "config/profile.json",
    lock_path: Path | None = None,
    client=None,
    interval_hours: int = DEFAULT_INTERVAL_HOURS,
    now_fn=_local_now,
    sleep_fn=time.sleep,
    log=print,
    max_cycles: int | None = None,
) -> None:
    """Run refreshes forever (or `max_cycles` times, for tests) on the
    "run now, then every `interval_hours` on the wall clock" cadence.

    `now_fn`/`sleep_fn` (and `lock_path`, to point at an isolated file) are
    injectable so this can be tested without waiting for real wall-clock
    time to pass or touching the real default lock file.
    """
    if lock_path is None:
        lock_path = refresh.DEFAULT_LOCK_PATH

    log("JobOS scheduler starting.")

    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        log("refresh started")
        try:
            result = refresh.refresh_from_files(
                db_path=db_path, sources_path=sources_path, profile_path=profile_path,
                client=client, lock_path=lock_path,
            )
        except refresh.RefreshAlreadyRunningError as exc:
            log(f"refresh skipped: {exc}")
        except (ConfigError, ProfileError) as exc:
            log(f"refresh could not start: {exc}")
        except Exception as exc:  # noqa: BLE001 - one bad cycle must not kill the scheduler
            log(f"refresh failed unexpectedly: {type(exc).__name__}: {exc}")
        else:
            log(
                f"refresh completed: status={result.status} "
                f"new={result.jobs_new} updated={result.jobs_updated} "
                f"high_priority_new={result.high_priority_new} review_new={result.review_new} "
                f"({result.duration_seconds:.1f}s)"
            )
            if result.error_message:
                log(f"refresh errors: {result.error_message}")

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break

        now = now_fn()
        upcoming = next_boundary(now, interval_hours)
        log(f"next scheduled run: {upcoming.isoformat()}")
        sleep_fn(max(0.0, (upcoming - now).total_seconds()))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.scheduler",
        description="Run the JobOS refresh pipeline immediately, then every 2 hours on the wall clock.",
    )
    parser.add_argument("--config", default="config/sources.json", type=Path)
    parser.add_argument("--profile", default="config/profile.json", type=Path)
    parser.add_argument("--db", default=database.DEFAULT_DB_PATH, type=Path)
    parser.add_argument(
        "--interval-hours", default=DEFAULT_INTERVAL_HOURS, type=int, help="Refresh cadence in hours (default: 2)."
    )
    parser.add_argument(
        "--lock-path", default=refresh.DEFAULT_LOCK_PATH, type=Path,
        help="Advisory lock file used to avoid overlapping with a manual `cli.py refresh` (default: "
             f"{refresh.DEFAULT_LOCK_PATH}).",
    )
    args = parser.parse_args(argv)

    run_scheduler(
        db_path=args.db, sources_path=args.config, profile_path=args.profile,
        lock_path=args.lock_path, interval_hours=args.interval_hours,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
