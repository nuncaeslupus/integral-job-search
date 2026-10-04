"""T252 — an offer's `url` is the page that describes the job, never the form.

Two offers reached a candidate linking to the board's application form
(`job-boards.eu.greenhouse.io/...`, page title "Job Application for ...")
instead of the advert. A form page is where a person *applies*; presenting it
as the advert asks them to commit before they have read what the job is.

**The decision is made on the url's own shape, once, where an offer is built**
(`connectors.build_offer`), so no connector can bypass it:

* `is_application_form_url` — the path ends in a form segment
  (`/apply`, `/application`, `/applications/new`), is Greenhouse's embedded
  `/embed/job_app`, or is a Greenhouse-hosted job page
  (`job-boards[.eu].greenhouse.io/<slug>/jobs/<id>`), whose title is "Job
  Application for ...". Matching is on parsed path segments, never on a
  substring of the whole url, so `/jobs/application-engineer-4411` (an advert
  for an application engineer) is not a form.
* `advert_url` — of the candidate urls a board gives for a job, the first one
  that is not a form (the employer's own advert is preferred: a Greenhouse
  `absolute_url` is the employer's careers page when the employer has one); a
  form url whose advert is the same path without the form segment (Lever,
  Ashby) is rewritten to it; otherwise `None`. `None` is the honest answer: a
  link nobody can show as an advert is no link.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

#: Final path segments that are a form and nothing else. Lever `.../<id>/apply`,
#: Ashby `.../<id>/application`, Workable `.../j/<id>/apply`.
_FORM_SEGMENTS = frozenset({"apply", "application", "applications"})

#: Greenhouse's hosted boards. A job page here is the application form (its
#: <title> is "Job Application for <role>"), whichever region serves it.
_GREENHOUSE_HOSTED = frozenset(
    {"job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.greenhouse.io"}
)


def _parts(url: str) -> tuple[str, list[str]] | None:
    try:
        split = urlsplit(url.strip())
    except ValueError:
        return None
    segments = [part.lower() for part in split.path.split("/") if part]
    return (split.hostname or "").lower(), segments


def is_application_form_url(url: str | None) -> bool:
    """True when `url` names a page whose main content is an application form."""
    if not url or not url.strip():
        return False
    parsed = _parts(url)
    if parsed is None:
        return False
    host, segments = parsed
    if not segments:
        return False
    if segments[-1] in _FORM_SEGMENTS:
        return True
    if len(segments) >= 2 and segments[-2] == "applications" and segments[-1] == "new":
        return True
    if segments[:2] == ["embed", "job_app"]:
        return True
    return host in _GREENHOUSE_HOSTED and "jobs" in segments


def _without_form_segment(url: str) -> str | None:
    """The advert a form url sits under: `.../<id>/apply` -> `.../<id>`."""
    split = urlsplit(url.strip())
    segments = [part for part in split.path.split("/") if part]
    if len(segments) < 2 or segments[-1].lower() not in _FORM_SEGMENTS:
        return None
    return urlunsplit((split.scheme, split.netloc, "/" + "/".join(segments[:-1]), "", ""))


def advert_url(candidates: Sequence[str | None]) -> str | None:
    """The url to present as the advert, from the urls a board gave, in order."""
    given = [c for c in candidates if c and c.strip()]
    for url in given:
        if not is_application_form_url(url):
            return url
    for url in given:
        stripped = _without_form_segment(url)
        if stripped is not None and not is_application_form_url(stripped):
            return stripped
    return None
