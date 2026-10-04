"""T252 — an offer's `url` is the page that describes the job, never the form.

Two offers reached a candidate linking to the board's application form
(`job-boards.eu.greenhouse.io/...`, page title "Job Application for ...")
instead of the advert. A form page is where a person *applies*; presenting it
as the advert asks them to commit before they have read what the job is.

**The decision is made on the url's own shape, once, in every constructor that
turns a url into an `Offer.url`** (`connectors.build_offer`,
`connectors.build_search_offer`, `offers.connect_manual`):

* `is_application_form_url` — the path ends in a form segment
  (`/apply`, `/application`, `/applications/new`) or is Greenhouse's embedded
  `/embed/job_app`. A Greenhouse-hosted job page
  (`job-boards[.eu].greenhouse.io/<slug>/jobs/<id>`) is **not** a form: it
  renders the advert with the form below it, the repository treats that host as
  an advert host (`serves_from`), and the only remedy the spec asks for is to
  prefer the employer's own url when the API gives one. Matching is on parsed,
  percent-decoded path segments, never a substring of the whole url, so
  `/jobs/application-engineer-4411` (an advert for an application engineer) is
  not a form.
* `advert_url` — of the candidate urls a board gives for a job, the first one
  that is not a form (a Greenhouse `absolute_url` is the employer's careers
  page when the employer has one, and is listed first); a `#app` / `#apply`
  fragment (a jump to the form on the advert page) is dropped; a form url on a
  host where the parent path is known to be the advert (Lever, Ashby, Workable,
  Teamtailor) is rewritten to it; otherwise `None`.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import unquote, urlsplit, urlunsplit

#: Final path segments that are a form and nothing else. Lever `.../<id>/apply`,
#: Ashby `.../<id>/application`, Workable `.../j/<id>/apply`.
_FORM_SEGMENTS = frozenset({"apply", "application", "applications"})

#: Hosts where `<advert>/<form segment>` has the advert as its parent path. On
#: any other host the parent may be a careers index, so the url is dropped
#: rather than rewritten.
_REWRITE_EXACT = frozenset(
    {"jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com", "apply.workable.com"}
)
_REWRITE_SUFFIX = (".teamtailor.com",)

#: Fragments that only jump to the form on the advert page.
_FORM_FRAGMENTS = frozenset({"app", "apply", "application"})


def _segments(path: str) -> list[str]:
    return [unquote(part).lower() for part in path.split(";", 1)[0].split("/") if part]


def is_application_form_url(url: str | None) -> bool:
    """True when `url` names a page whose main content is an application form."""
    if not url or not url.strip():
        return False
    try:
        split = urlsplit(url.strip())
    except ValueError:
        return False
    segments = _segments(split.path)
    if not segments:
        return False
    if segments[-1] in _FORM_SEGMENTS:
        return True
    if len(segments) >= 2 and segments[-2:] == ["applications", "new"]:
        return True
    return segments[:2] == ["embed", "job_app"]


def _without_form_segment(url: str) -> str | None:
    """The advert a form url sits under: `.../<id>/apply` -> `.../<id>`.

    Teamtailor's `.../jobs/<id>/applications/new` loses two segments.
    """
    split = urlsplit(url.strip())
    host = (split.hostname or "").lower()
    if host not in _REWRITE_EXACT and not host.endswith(_REWRITE_SUFFIX):
        return None
    raw = [part for part in split.path.split("/") if part]
    lowered = _segments(split.path)
    if len(lowered) >= 3 and lowered[-2:] == ["applications", "new"]:
        keep = raw[:-2]
    elif len(lowered) >= 2 and lowered[-1] in _FORM_SEGMENTS:
        keep = raw[:-1]
    else:
        return None
    return urlunsplit((split.scheme, split.netloc, "/" + "/".join(keep), "", ""))


def _without_form_fragment(url: str) -> str:
    split = urlsplit(url.strip())
    if split.fragment.lower() in _FORM_FRAGMENTS:
        return urlunsplit((split.scheme, split.netloc, split.path, split.query, ""))
    return url


def advert_url(candidates: Sequence[str | None]) -> str | None:
    """The url to present as the advert, from the urls a board gave, in order."""
    given = [_without_form_fragment(c) for c in candidates if c and c.strip()]
    for url in given:
        if not is_application_form_url(url):
            return url
    for url in given:
        stripped = _without_form_segment(url)
        if stripped is not None and not is_application_form_url(stripped):
            return stripped
    return None
