"""ATS detection by application URL. Only three ATS are recognized at
all; everything else is `None` ("Unsupported ATS — open manually")."""

# Every ATS this app will ever recognize -- not necessarily fill yet.
SUPPORTED_ATS = ("lever", "ashby", "greenhouse")

# Which of the supported ATS this phase actually has fill logic for.
# Built and verified one at a time, per the phase spec -- Lever first.
IMPLEMENTED_ATS = ("lever",)

_HOST_MARKERS: dict[str, str] = {
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
}


def detect_ats(application_url: str) -> str | None:
    """The ATS this URL belongs to, or `None` if it isn't one of the three
    this app ever recognizes."""
    url = (application_url or "").lower()
    for marker, ats in _HOST_MARKERS.items():
        if marker in url:
            return ats
    return None


def apply_url_for(application_url: str, ats: str) -> str:
    """The actual application-form URL for a given posting URL -- Lever's
    posting page and its form live at different paths."""
    if ats == "lever" and not application_url.rstrip("/").endswith("/apply"):
        return application_url.rstrip("/") + "/apply"
    return application_url
