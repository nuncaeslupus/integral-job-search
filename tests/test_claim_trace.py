"""T146 — a denial and a count are claims; the document may carry the first only as the candidate's.

Cases are derived from the task text, not from the code: the live letter said
"I have not used observability tools" (false, Honeycomb at Flanks) and
"~1,600 commits across seven repositories, six published" (stale within the
session). The rule is closed: a denial is allowed in a `candidate`-authored paragraph
and nowhere else, so the family that keeps the check honest is the positive one - the
candidate's own cited denial must PASS, or banning the word "not" would satisfy the gate.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from integral import claim_trace
from integral.application_authorship import check_authorship
from integral.claim_trace import (
    DENIAL_KIND,
    check_version,
    entry_defects,
    entry_denials,
    is_denial,
    paragraph_defects,
    quantities,
)
from integral.cv_store import (
    ConversationTurn,
    CVMaster,
    Episode,
    Experience,
    Skill,
    SourcedText,
    write_master,
)
from integral.generate import Claim, Manifest, generate, read_manifest, render_entry, traceability
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog

DENIAL = "I have not used observability tools in production."
COUNT = "About 1,600 commits across seven repositories, six published."
ADVERT = "A data engineer in Girona. PostgreSQL and migrations."


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


def say(
    store: ProfileStore, text: str, kind: str = "statement", source: str = "conversation"
) -> str:
    return (
        EvidenceLog(store)
        .append(
            recorded_at="2026-10-06T10:00:00Z",
            step="history",
            kind=kind,  # type: ignore[arg-type]
            text=text,
            source=source,  # type: ignore[arg-type]
        )
        .id
    )


def cited(*ids: str) -> tuple[ConversationTurn, ...]:
    return tuple(ConversationTurn(evidence_id=i) for i in ids)


def kinds(store: ProfileStore, entry: SourcedText | Skill) -> list[str]:
    return [d.kind for d in entry_denials(store, entry)]


# --- the classifier --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I have not used observability tools.",
        "I haven't used Kubernetes",
        "I haven" + chr(0x2019) + "t used Kubernetes",
        "Never touched Kafka.",
        "No experience with Terraform.",
        "No he usado herramientas de observabilidad.",
        "Nunca he trabajado con Kafka.",
        "Sense experiència amb Terraform. Mai he fet servir Kafka.",
        "I dont use Kafka.",
        "I have yet to use Kafka.",
        "I am unable to use Kafka.",
        "Desconozco Kafka.",
        "Sin experiencia en Kafka.",
        "Gens d'experiència amb Kafka.",
        "Little exposure to Kafka.",
    ],
)
def test_denials_are_recognised_in_three_languages(text: str) -> None:
    assert is_denial(text)


@pytest.mark.parametrize(
    "text",
    [
        "Used Honeycomb at Flanks.",
        "Built the NoSQL layer.",
        "Migrated billing without downtime.",
        "Sin pausas, con calma: migré la facturación.",
    ],
)
def test_an_assertion_is_not_a_denial(text: str) -> None:
    assert not is_denial(text)


def test_quantities_are_read_from_digits_and_words_and_years_are_not_counts() -> None:
    assert quantities(COUNT) == [1600, 7, 6]
    assert quantities("Seven repositories, siete repos, set repos.") == [7, 7]
    assert quantities("A zero-downtime cutover, once.") == []
    assert quantities("Since 2019, until 1998.") == []
    assert quantities("Cut cost by 2.5 percent") == [Decimal("2.5")] == [Decimal("2.50")]
    assert quantities("Cut cost by 2,5 percent") == [Decimal("2.5")]
    assert quantities("Version 1.2.3") == ["1.2.3"]
    assert quantities("30% faster, 12 services") == [30, 12]
    assert quantities("Web3 and S3 on 3D scenes") == [3]  # only the free-standing 3


# --- a stored denial needs a backing row exactly as an assertion does --------


# --- a generated CV entry may carry no denial, whoever said it ----------------


def test_a_denial_with_no_backing_row_is_refused(store: ProfileStore) -> None:
    assert kinds(store, SourcedText(text=DENIAL)) == [DENIAL_KIND]


def test_a_denial_the_candidate_made_is_still_refused_in_a_cv_entry(store: ProfileStore) -> None:
    """No backing rows at all: a CV entry is not a candidate paragraph, however it is sourced."""
    row = say(store, DENIAL)
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(row))) == [DENIAL_KIND]


def test_the_live_incident_is_refused_the_candidate_used_honeycomb(store: ProfileStore) -> None:
    said = say(store, "I used Honeycomb at Flanks for years and I understand queries and traces.")
    assert kinds(store, SourcedText(text=DENIAL, provenance=cited(said))) == [DENIAL_KIND]


def test_a_denial_in_a_name_field_is_read_too(store: ProfileStore) -> None:
    assert kinds(store, Skill(name="Never used Kafka")) == [DENIAL_KIND]


@pytest.mark.parametrize(
    "text",
    [
        "I have not used AWS.",  # R1: a short name
        "I have not used Kafka, Spark or Flink.",  # A1: the tail of a list
        "Observability tools? I have never used them.",  # R2/A2: bound to its neighbour
        "I have not used Kubernetes in production, and I have never used observability tools.",
        "I have not used C++.",  # A3
        "\uff29 have not used Kafka.",  # a fullwidth spelling
    ],
)
def test_every_reviewer_denial_is_refused_in_a_cv_entry_even_with_the_row_behind_it(
    text: str, store: ProfileStore
) -> None:
    row = say(store, text)  # the candidate said these very words
    entry = Experience(
        title="Dev",
        organisation="Cintra",
        description="Ran billing. " + text,
        provenance=cited(row),
    )
    assert [d.kind for d in entry_defects(store, entry)] == [DENIAL_KIND]


# --- the generator withholds every denial, in every section -------------------


def test_the_generator_omits_a_denial_headline_and_says_why(store: ProfileStore) -> None:
    master = CVMaster(
        headline=SourcedText(text=DENIAL),
        experience=(Experience(title="Dev", organisation="Cintra", description="Moved billing."),),
    )
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    written = {c.text for c in manifest.claims}
    assert DENIAL not in written
    assert any("Moved billing" in t for t in written)
    assert [o.section for o in manifest.omissions] == ["headline"]
    assert "may not state an absence" in manifest.omissions[0].reason
    assert check_version(store, master, "o1", 1)["untraced_claim_defects"] == 0


def test_the_generator_omits_a_denial_the_candidate_made(store: ProfileStore) -> None:
    """The old backed-denial case, reversed: the candidate saying it does not put it in the CV."""
    row = say(store, DENIAL)
    master = CVMaster(headline=SourcedText(text=DENIAL, provenance=cited(row)))
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    assert DENIAL not in {c.text for c in manifest.claims}
    assert [o.section for o in manifest.omissions] == ["headline"]


def test_an_approved_episode_that_is_a_denial_is_left_out(store: ProfileStore) -> None:
    """The episode path is filtered separately from the CV path and has its own pin."""
    text = "I have never used observability tools."
    row = say(store, text)
    master = CVMaster(
        headline=SourcedText(text="Backend engineer"),
        episodes=(Episode(kind="lesson", text=text, provenance=cited(row)),),
    )
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT, _approved_episodes=(0,))
    assert text not in {c.text for c in manifest.claims}
    assert [o.section for o in manifest.omissions] == ["episodes"]


def test_the_generator_omits_a_denial_experience_entry(store: ProfileStore) -> None:
    row = say(store, "I have not used Kafka.")
    entry = Experience(
        title="Dev",
        organisation="Cintra",
        description="Ran billing. I have not used Kafka.",
        provenance=cited(row),
    )
    master = CVMaster(experience=(entry,))
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    assert all("Kafka" not in c.text for c in manifest.claims)
    assert [o.section for o in manifest.omissions] == ["experience"]
    assert check_version(store, master, "o1", 1)["untraced_claim_defects"] == 0


def _append_claim(store: ProfileStore, manifest: Manifest, claim: Claim) -> None:
    """Write a claim line into v1 as a document that disagrees with the generator would."""
    where = store.path("cv", "generated", "o1", "v1")
    cv = where / "cv.md"
    cv.write_text(cv.read_text(encoding="utf-8") + claim.text + "\n", encoding="utf-8")
    both = {**manifest.model_dump(), "claims": (*manifest.claims, claim)}
    (where / "manifest.json").write_text(Manifest(**both).model_dump_json(), encoding="utf-8")


def test_check_version_counts_a_denial_that_reaches_the_document(store: ProfileStore) -> None:
    """Manifest and document agree and T45 is green - only the claim check sees it."""
    row = say(store, DENIAL)
    master = CVMaster(headline=SourcedText(text=DENIAL, provenance=cited(row)))
    write_master(store, CVMaster())
    manifest = generate(store, CVMaster(), offer_id="o1", advert=ADVERT)
    _append_claim(
        store, manifest, Claim(document="cv.md", text=DENIAL, section="headline", entry_index=0)
    )
    assert traceability(store, master, "o1", 1)["claims_untraced"] == []
    checked = check_version(store, master, "o1", 1)
    assert [d.kind for d in checked["defects"]] == [DENIAL_KIND]
    assert checked["untraced_claim_defects"] == 1 and checked["denials_checked"] == 1


def test_check_version_counts_a_denial_in_an_episode_and_in_an_experience(
    store: ProfileStore,
) -> None:
    ep_text = "I have never used observability tools."
    exp = Experience(
        title="Dev", organisation="Cintra", description="I have not used Kafka.",
        provenance=cited(say(store, "I have not used Kafka.")),
    )  # fmt: skip
    master = CVMaster(
        experience=(exp,),
        episodes=(Episode(kind="lesson", text=ep_text, provenance=cited(say(store, ep_text))),),
    )
    write_master(store, CVMaster())
    manifest = generate(store, CVMaster(), offer_id="o1", advert=ADVERT)
    exp_claim = Claim(
        document="cv.md", text=render_entry("experience", exp), section="experience", entry_index=0
    )
    _append_claim(store, manifest, exp_claim)
    _append_claim(
        store,
        read_manifest(store, "o1", 1),
        Claim(document="cv.md", text=ep_text, section="episodes", entry_index=0),
    )
    checked = check_version(store, master, "o1", 1)
    assert [d.kind for d in checked["defects"]] == [DENIAL_KIND, DENIAL_KIND]


# --- the letter: only a candidate paragraph may state an absence --------------

REVIEWER_DENIALS = [  # (body, what the candidate cited): every round's case, all one rule now
    (DENIAL, DENIAL),  # verbatim in an edited paragraph
    (DENIAL, "I have never deployed Kafka to production."),  # B1: shares only "production"
    (DENIAL, "I used observability tools in production for years."),  # opposite sense
    ("I have not used AWS.", "I have never used GCP."),  # R1
    ("Observability tools? I have never used them.", "No, I have not."),  # R2
    ("I have not used Kafka.", "I have not used Kafka Streams, but I used Kafka daily."),  # R3
    ("I have not used Kafka, Spark or Flink.", "I have not used Kafka."),  # A1
    ("Observability tools? No.", "Did I use Haskell? No."),  # A2
    ("I have not used C#.", "I have not used C++."),  # A3
    ("I have never used .NET.", "I have never used NET."),  # A3
    (
        "I have not used Kubernetes in production, and I have never used observability tools.",
        "I have not used Kubernetes in production.",
    ),  # G1
    ("Haskell? I have never used them.", "Haskell? I have never used them."),  # G2: whole row
]


@pytest.mark.parametrize(("body", "said"), REVIEWER_DENIALS)
@pytest.mark.parametrize("author", ["edited", "assistant"])
def test_any_denial_outside_a_candidate_paragraph_is_refused(
    author: str, body: str, said: str
) -> None:
    cited_words = [said] if author == "edited" else []
    assert [d.kind for d in paragraph_defects(author, body, cited_words)] == [DENIAL_KIND]


def test_a_candidate_paragraph_may_state_a_denial() -> None:
    """The positive case that keeps the rule honest: the honest-gap sentence has a home."""
    assert paragraph_defects("candidate", DENIAL, [DENIAL]) == []
    assert paragraph_defects("candidate", "Haskell? I have never used them.", []) == []


def test_an_assistant_denial_is_refused() -> None:
    assert [d.kind for d in paragraph_defects("assistant", DENIAL, [])] == [DENIAL_KIND]


@pytest.mark.parametrize(
    "body", ["I dont use Kafka.", "I have yet to use Kafka.", "I am unable to use Kafka."]
)
def test_the_english_cues_are_denials_and_refused_outside_a_candidate_paragraph(body: str) -> None:
    assert [d.kind for d in paragraph_defects("assistant", body, [])] == [DENIAL_KIND]
    assert [d.kind for d in paragraph_defects("edited", body, [body])] == [DENIAL_KIND]
    assert paragraph_defects("candidate", body, [body]) == []


def test_each_denial_sentence_is_one_defect() -> None:
    body = "I have not used Kafka. I used Spark. I have never used Flink."
    assert [d.text for d in paragraph_defects("edited", body, [body])] == [
        "I have not used Kafka",
        "I have never used Flink",
    ]


def test_an_assistant_hand_typed_count_is_refused_per_number() -> None:
    assert [d.kind for d in paragraph_defects("assistant", COUNT, [])] == ["hand_typed_count"] * 3


def test_an_edited_paragraph_may_keep_the_candidates_number_but_not_add_one() -> None:
    assert paragraph_defects("edited", "I run 3 services.", ["I run 3 services daily."]) == []
    added = paragraph_defects("edited", "I run 4 services.", ["I run 3 services daily."])
    assert [d.kind for d in added] == ["hand_typed_count"]


def test_a_number_is_spent_once() -> None:
    twice = paragraph_defects("edited", "3 teams, 3 services.", ["I run 3 services."])
    assert [d.kind for d in twice] == ["hand_typed_count"]


def test_years_and_the_candidates_own_paragraph_are_never_counts() -> None:
    assert paragraph_defects("assistant", "Since 2019 at Flanks.", []) == []
    assert paragraph_defects("assistant", "Desde 2019 en Flanks, 2019-2021.", []) == []
    assert paragraph_defects("candidate", COUNT + " " + DENIAL, []) == []


def _letter(store: ProfileStore, author: str, body: str, *sources: str) -> list[str]:
    ids = [
        say(store, text, kind="candidate_statement", source="application_draft") for text in sources
    ]
    cell = "" if author == "assistant" else " ".join(ids)
    table = (
        "## Authorship\n| n | a | e | c |\n|---|---|---|---|\n"
        f"| 1 | {author} | {cell} | reworded |\n"
    )
    return list(check_authorship(body, table, EvidenceLog(store)).defects)


def test_check_authorship_refuses_an_assistant_paragraph_carrying_the_live_incident(
    store: ProfileStore,
) -> None:
    """Both live defects, through the real gate: each in a paragraph that cites nothing."""
    for body, kind in ((DENIAL, DENIAL_KIND), (COUNT, "hand_typed_count")):
        found = _letter(store, "assistant", body)
        assert any(kind in d for d in found), found


def test_check_authorship_refuses_an_edited_paragraph_even_when_it_repeats_the_candidate(
    store: ProfileStore,
) -> None:
    found = _letter(store, "edited", DENIAL, DENIAL)
    assert any(DENIAL_KIND in d for d in found), found


def test_check_authorship_passes_the_honest_gap_in_a_candidate_paragraph(
    store: ProfileStore,
) -> None:
    """The counter-case through the real gate: the candidate said it, their paragraph keeps it."""
    assert _letter(store, "candidate", DENIAL, DENIAL) == []


# --- the gate ---------------------------------------------------------------


def test_the_probes_judge_every_hole_and_every_counter_case() -> None:
    verdicts = claim_trace.probe_cases()
    labels = {v["case"] for v in verdicts}
    assert {
        "stored denial with no backing row",
        "stored denial the candidate made",
        "assistant denial",
        "edited denial the candidate cited verbatim",
        "candidate paragraph denial, cited verbatim",
        "assistant hand-typed count",
        "edited count the candidate wrote",
    } <= labels
    assert all(v["expected"] == v["found"] for v in verdicts), verdicts
    assert any(v["expected"] == 0 and "denial" in v["case"] for v in verdicts)


def test_the_measurement_over_the_corpus_is_clean() -> None:
    measured = claim_trace.measure()
    assert measured["untraced_claim_defects"] == 0
    assert measured["claims_checked"] > 0 and measured["adverts_generated"] > 0
    assert measured["probe_cases_misjudged"] == 0


def test_main_exits_zero_and_writes_the_record(tmp_path: Path) -> None:
    out = tmp_path / "T146.json"
    assert claim_trace._main(["claim_trace", str(out)]) == 0
    assert json.loads(out.read_text())["untraced_claim_defects"] == 0


# --- numbers: computed or not written (unchanged by the denial rule) -----------


def test_f3_a_hand_typed_count_in_a_cv_entry_is_left_out_and_counted(store: ProfileStore) -> None:
    row = say(store, "I have commits across several repositories.")
    headline = SourcedText(text=COUNT, provenance=cited(row))
    assert [d.kind for d in entry_defects(store, headline)] == ["hand_typed_count"] * 3
    master = CVMaster(headline=headline)
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    assert COUNT not in {c.text for c in manifest.claims}
    assert [o.section for o in manifest.omissions] == ["headline"]
    assert "number" in manifest.omissions[0].reason
    # an entry that does not hold the number but is written anyway is counted by check_version
    _append_claim(
        store, manifest, Claim(document="cv.md", text=COUNT, section="headline", entry_index=0)
    )
    checked = check_version(store, master, "o1", 1)
    assert checked["untraced_claim_defects"] == 3 and checked["counts_checked"] == 3


def test_f3_a_sourced_count_in_a_cv_entry_passes_once_per_source_number(
    store: ProfileStore,
) -> None:
    row = say(store, "I ran 4 services for the permits API.")
    assert entry_defects(store, SourcedText(text="Ran 4 services.", provenance=cited(row))) == []
    twice = SourcedText(text="Ran 4 and 4 services.", provenance=cited(row))
    assert [d.kind for d in entry_defects(store, twice)] == ["hand_typed_count"]


def test_f3_dates_in_a_stored_entry_are_not_counts(store: ProfileStore) -> None:
    job = Experience(title="Dev", organisation="Cintra", start="2021", end="2025", description="x")
    assert entry_defects(store, job) == []


def test_f4_a_year_shaped_count_is_refused_and_a_date_is_not() -> None:
    assert [d.kind for d in paragraph_defects("assistant", "I wrote 2000 commits.", [])] == [
        "hand_typed_count"
    ]
    for body in ("I shipped 1999 tests.", "A graph of 2048 nodes."):
        assert paragraph_defects("assistant", body, [])
    dates = ("Since 2019 at Flanks.", "Worked 2019-2021.", "From 2019 to 2021.", "Left in 2021.")
    for body in dates:
        assert paragraph_defects("assistant", body, []) == [], body


def test_f5_a_decimal_is_compared_by_value() -> None:
    assert paragraph_defects("edited", "It took 1.6 seconds.", ["It took 2.5 percent."])
    assert paragraph_defects("edited", "It took 2.50 seconds.", ["It took 2.5 percent."]) == []
    assert paragraph_defects("edited", "It took 2,5 seconds.", ["It took 2.5 percent."]) == []


def test_f6_more_number_words() -> None:
    assert quantities("dues empreses, veinticinco, dieciséis, doscientos") == [2, 25, 16, 200]


def test_the_corpus_carries_a_candidate_denial_and_a_sourced_count() -> None:
    measured = claim_trace.measure()
    assert measured["denials_checked"] > 0 and measured["counts_checked"] > 0
    assert measured["untraced_claim_defects"] == 0


def test_main_exits_three_when_the_corpus_has_no_denial_or_no_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = claim_trace.measure()
    for key in ("denials_checked", "counts_checked"):
        monkeypatch.setattr(claim_trace, "measure", lambda key=key: {**real, key: 0})
        assert claim_trace._main(["claim_trace", str(tmp_path / "T.json")]) == 3


def test_split_sentence_boundary_each_sentence_is_judged_on_its_own() -> None:
    """Mutant-killer: with no sentence split an affirmation beside a denial would hide it."""
    found = paragraph_defects("edited", "I used Spark daily. I have not used Kafka.", [])
    assert [d.text for d in found] == ["I have not used Kafka"]
    assert paragraph_defects("edited", "I used Spark daily. I love Kafka.", []) == []


def test_a_year_shaped_number_with_a_plus_is_a_count() -> None:
    assert [d.kind for d in paragraph_defects("assistant", "2000+ commits.", [])] == [
        "hand_typed_count"
    ]
    assert paragraph_defects("assistant", "Since 2019+.", [])


def test_episodes_are_not_exempt_from_the_count_rule(store: ProfileStore) -> None:
    text = "I shipped 1,600 commits across seven repositories."
    unnumbered = say(store, "I shipped many commits across several repositories.")
    episode = Episode(kind="achievement", text=text, provenance=cited(unnumbered))
    assert [d.kind for d in entry_defects(store, episode)] == ["hand_typed_count"] * 2
    master = CVMaster(headline=SourcedText(text="Backend engineer"), episodes=(episode,))
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT, _approved_episodes=(0,))
    assert text not in {c.text for c in manifest.claims}
    assert [o.section for o in manifest.omissions] == ["episodes"]
    held = say(store, text)
    sourced = Episode(kind="achievement", text=text, provenance=cited(held))
    assert entry_defects(store, sourced) == []


# --- round 5: `is_denial` recall is the whole guarantee, so each spelling is a case ---

FULLWIDTH_NOT = "".join(chr(0xFF00 + ord(c) - 0x20) for c in "not")
RESPELLED = [
    "I havent used observability tools.",  # B1: a contraction without its apostrophe
    "I didnt use Kafka.",
    "It hasnt been used.",
    "It isnt used.",
    "I wont use it.",
    "I cant use it.",
    "I don" + chr(0xB4) + "t use Kafka.",  # B2: look-alike apostrophes
    "I don" + chr(0x2018) + "t use Kafka.",
    "I don" + chr(0x2BC) + "t use Kafka.",
    "I don`t use Kafka.",
    "I don" + chr(0x2032) + "t use Kafka.",
    "I " + FULLWIDTH_NOT + " use Kafka.",  # fullwidth "not"
    "Jamás he usado Kafka.",  # NFD "Jamás"
    "Ningún uso de Kafka.",
    "Ningun uso de Kafka.",  # accentless
    "Ningu he fet servir Kafka.",
    "Never-used Kafka.",  # B3: a hyphen compound
    "Not-yet-used Kafka.",
    "Sin  experiencia en Kafka.",  # B4: any whitespace between the words of a phrase
    "Little\nexposure to Kafka.",
    "I have yet\nto use Kafka.",
    "I lacked Kafka.",  # N1 inflections
    "Desconocía Kafka.",
    "Carecía de Kafka.",
    "Ningunos de ellos.",
    "Desconec Kafka.",
    "I hardly used Kafka.",  # N2 phrasings
    "I barely used Kafka.",
    "Nope.",
    "Kafka: n/a.",
    "I am new to Kafka.",
    "Limited experience with Kafka.",
    "Minimal exposure to Kafka.",
    "Zero experience with Kafka.",
    "Without experience in Kafka.",
]


@pytest.mark.parametrize("text", RESPELLED)
def test_a_respelled_cue_is_still_a_denial(text: str) -> None:
    assert is_denial(text), text
    assert [d.kind for d in paragraph_defects("assistant", text, [])] == [DENIAL_KIND]
    assert [d.kind for d in paragraph_defects("edited", text, [text])] == [DENIAL_KIND]


@pytest.mark.parametrize(
    "text",
    [
        "Built a zero-downtime cutover.",
        "Migrated without downtime.",
        "Wrote non-trivial services.",
        "Re-architected billing.",
        "Cantaba en un coro.",
        "Wonton soup.",
    ],
)
def test_the_negative_controls_are_not_denials(text: str) -> None:
    assert not is_denial(text), text
    assert paragraph_defects("assistant", text, []) == []


def test_b_cases_through_check_authorship_and_the_generator(store: ProfileStore) -> None:
    found = _letter(store, "edited", "Ran billing. I havent used observability tools.", DENIAL)
    assert any(DENIAL_KIND in d for d in found), found
    headline = SourcedText(text="Never-used Kafka; havent touched Flink.")
    exp = Experience(
        title="Dev", organisation="Cintra", description="didnt use observability tools."
    )
    master = CVMaster(headline=headline, experience=(exp,))
    write_master(store, master)
    manifest = generate(store, master, offer_id="o1", advert=ADVERT)
    assert sorted(o.section for o in manifest.omissions) == ["experience", "headline"]
    assert check_version(store, master, "o1", 1)["untraced_claim_defects"] == 0
    _append_claim(
        store,
        manifest,
        Claim(document="cv.md", text=headline.text, section="headline", entry_index=0),
    )
    assert [d.kind for d in check_version(store, master, "o1", 1)["defects"]] == [DENIAL_KIND] * 2


def test_each_fold_is_load_bearing() -> None:
    """One assertion per fold, so switching any one off goes red here."""
    assert claim_trace.fold("Jamás") == "jamas"  # combining marks
    assert claim_trace.fold(FULLWIDTH_NOT) == "not"  # NFKC
    assert claim_trace.fold("don" + chr(0xB4) + "t") == "don't"  # apostrophes
    assert is_denial("Never-used") and not is_denial("Reused-twice")  # hyphen parts


def test_a_cited_sentence_plus_a_new_denial_is_not_a_candidate_paragraph(
    store: ProfileStore,
) -> None:
    said = "I run 3 services."
    found = _letter(store, "candidate", said + " I have never used Kafka.", said)
    assert any("not exactly the cited sentences" in d for d in found), found


def test_the_gate_derives_its_denial_count_from_what_check_authorship_judged(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert claim_trace._candidate_denials_checked(store) == (1, 0)
    monkeypatch.setattr(claim_trace, "is_denial", lambda text: False)
    assert claim_trace._candidate_denials_checked(store)[0] == 0
