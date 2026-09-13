"""Source adapters. Each one converts a single ATS API into `Job` objects."""

from app.collectors.ashby import AshbyCollector
from app.collectors.base import JobCollector
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.lever import LeverCollector

COLLECTORS: dict[str, type[JobCollector]] = {
    GreenhouseCollector.source: GreenhouseCollector,
    AshbyCollector.source: AshbyCollector,
    LeverCollector.source: LeverCollector,
}

SUPPORTED_SOURCES = tuple(sorted(COLLECTORS))

__all__ = [
    "COLLECTORS",
    "SUPPORTED_SOURCES",
    "AshbyCollector",
    "GreenhouseCollector",
    "JobCollector",
    "LeverCollector",
]
