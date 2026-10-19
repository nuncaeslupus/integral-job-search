"""T276 — one posting listed under several offices is stored once.

The cases are derived from the task (#551), not from the code: greenhouse /
anthropic listed the same role under several offices (different `location`,
different URL query) and every copy was stored. The counter-case is two
genuinely different openings of one role at one employer (two teams), which
must both survive: a wrong merge hides a vacancy the candidate never sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    SAME_BOARD_TEXT_THRESHOLD,
    collect_offer,
    same_board_body_similarity,
    same_board_twin,
)
from integral.offers import Location, Offer, compute_offer_id

NOW = "2026-01-01T00:00:00+00:00"

ABOUT = (
    "About Anthropic. Anthropic's mission is to create reliable, interpretable and steerable "
    "AI systems. We want AI to be safe and beneficial for our users and for society as a whole. "
    "Our team is a quickly growing group of committed researchers, engineers, policy experts "
    "and business leaders working together to build beneficial AI systems."
)
PARTNERSHIPS = (
    "As an Applied AI Architect on the Partnerships team you will work with strategic "
    "technology partners to design joint reference architectures, advise their engineering "
    "teams on building Claude into their platforms, and write the integration guides that "
    "partner developers follow. You will travel to partner sites a few times each quarter."
)
INDUSTRIES = (
    "As an Applied AI Architect on the Industries team you will embed with customers in "
    "regulated sectors such as banking and healthcare, translate their compliance needs into "
    "deployment patterns, and prototype agents for their back offices. You will lead "
    "discovery workshops and own the technical relationship through production launch."
)


def _offer(
    text: str,
    *,
    url: str,
    location: str,
    title: str = "Applied AI Architect",
    company: str | None = "Anthropic",
    source: str = "greenhouse",
) -> Offer:
    return Offer(
        id=compute_offer_id(text + url + location),
        source=source,
        url=url,
        title=title,
        company=company,
        location=Location(raw=location),
        text=text,
    )


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    create_profile(root, "Fixture", handle="fixture", language="es", fiction=True)
    return ProfileStore(root, "fixture")


def _stored(store: ProfileStore) -> set[str]:
    return {p.stem for p in Path(store.path("offers")).glob("*.json") if not p.name.startswith("_")}


def test_one_posting_under_four_offices_is_stored_once(store: ProfileStore) -> None:
    body = f"{PARTNERSHIPS} {ABOUT}"
    offices = ["London", "Dublin", "Paris", "San Francisco, CA"]
    copies = [
        _offer(
            body,
            url=f"https://boards.greenhouse.io/anthropic/jobs/{4000 + n}?gh_src=o{n}",
            location=place,
        )
        for n, place in enumerate(offices)
    ]
    outcomes = [collect_offer(store, c, at=NOW) for c in copies]
    assert [o.added_as_new for o in outcomes] == [True, False, False, False]
    assert {o.duplicate_of for o in outcomes[1:]} == {copies[0].id}
    assert _stored(store) == {copies[0].id}


def test_the_office_written_into_the_body_does_not_split_the_copies(store: ProfileStore) -> None:
    first = _offer(
        f"{PARTNERSHIPS} {ABOUT} Location: London", url="https://g.test/a", location="London"
    )
    second = _offer(
        f"{PARTNERSHIPS} {ABOUT} Location: Dublin", url="https://g.test/b", location="Dublin"
    )
    assert collect_offer(store, first, at=NOW).added_as_new
    assert collect_offer(store, second, at=NOW).duplicate_of == first.id


def test_two_teams_hiring_the_same_title_are_both_stored(store: ProfileStore) -> None:
    partnerships = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    industries = _offer(f"{INDUSTRIES} {ABOUT}", url="https://g.test/2", location="London")
    assert collect_offer(store, partnerships, at=NOW).added_as_new
    outcome = collect_offer(store, industries, at=NOW)
    assert outcome.added_as_new and outcome.duplicate_of is None
    assert _stored(store) == {partnerships.id, industries.id}


def test_two_teams_are_not_a_twin_even_with_the_same_office() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(f"{INDUSTRIES} {ABOUT}", url="https://g.test/2", location="London")
    assert not same_board_twin(a, b)


def test_the_same_words_on_another_board_are_not_merged_here() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://l.test/1", location="London", source="lever")
    assert not same_board_twin(a, b)


def test_another_employer_with_the_same_title_and_body_is_not_a_twin() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/2", location="London", company="Acme")
    assert not same_board_twin(a, b)


def test_a_different_level_of_the_same_role_is_not_a_twin() -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London")
    b = _offer(
        f"{PARTNERSHIPS} {ABOUT}",
        url="https://g.test/2",
        location="London",
        title="Senior Applied AI Architect",
    )
    assert not same_board_twin(a, b)


def test_an_advert_naming_no_employer_is_never_a_twin(store: ProfileStore) -> None:
    a = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/1", location="London", company=None)
    b = _offer(f"{PARTNERSHIPS} {ABOUT}", url="https://g.test/2", location="Dublin", company=None)
    assert not same_board_twin(a, b)
    assert collect_offer(store, a, at=NOW).added_as_new
    assert collect_offer(store, b, at=NOW).added_as_new


# --- T276 review: realistic boilerplate (second reader, PR #871) -------------
#
# Distinct vacancies at one employer and one title share the employer's
# boilerplate, so on a long advert they look alike. The five pairs below are the
# reviewer's, measured on a ~450-word body; every one must stay stored twice.

BOILER = """
About the company. We build reliable, interpretable and steerable software that helps
organisations make better decisions, and we do it as a public benefit corporation whose
mission is to make the arrival of powerful technology go well for people. Our team is a
quickly growing group of researchers, engineers, operators, policy experts and business
leaders who care about the long term consequences of what we ship. We work as one
collaborative group, favour a small number of large projects over many small ones, and
treat communication as a core skill. Few of us have the exact background this role lists,
and we encourage you to apply even if you do not meet every single qualification.

How we are different. We believe the highest impact comes from careful empirical work.
Our research agenda is shaped by evidence, written down in public, and revisited when the
evidence changes. Colleagues review each other's work openly and kindly, and we value
people who change their mind when shown a better argument. You will have a real say in
what we build and how we build it, and you will be trusted to make decisions without
waiting for permission.

Logistics. We expect staff to be in the office at least three days a week, because
working side by side makes the hardest problems easier. We do offer relocation support and
we can sponsor work visas, although we are not able to do so for every role or location,
and we will tell you honestly where a particular posting stands. Candidates are welcome to
tell us what adjustments would help them in the interview process, and we will gladly make
them. Our interviews consist of a recruiter conversation, a technical exercise you can
complete in your own environment, a conversation with future colleagues, and a final
discussion about values and working style. We aim to give a decision within two weeks of
the final round and to give feedback to every candidate who reaches the technical stage.

Benefits. We offer competitive salary and equity, generous leave, a learning budget,
comprehensive health cover for you and your dependents, flexible parental leave, a
retirement plan with employer contributions, daily lunches in the office, and a wellbeing
allowance you can spend as you see fit. We encourage you to read our principles on the
careers page before you apply. We are an equal opportunity employer and we consider
applicants without regard to race, colour, religion, sex, gender identity, sexual
orientation, national origin, age, disability or veteran status. Please do not send us
unsolicited resumes through recruiters unless you have a signed agreement with us in place,
because we review each application ourselves. Your personal data is handled under our
candidate privacy notice, which we will send you with the first message, and you may ask us
to delete it at any time during or after the process.
"""

TEAM_A = (
    "The Inference team. You will build the serving stack that turns trained models into "
    "low latency, high throughput endpoints: batching, scheduling, caching of attention state, "
    "and the accelerator kernels underneath. You will profile production traffic and own the "
    "capacity plan for the fleet."
)
TEAM_B = (
    "The Pretraining Infrastructure team. You will build the distributed training stack that "
    "keeps thousands of accelerators busy for weeks: sharding, checkpointing, fault tolerance, "
    "and the data loading pipeline feeding it. You will debug stragglers and own the cluster "
    "health tooling."
)


def _long(role: str, **kw: str | None) -> Offer:
    text = f"{role}\n{BOILER}"
    return _offer(
        text,
        url=f"https://g.test/{compute_offer_id(text)}",
        location="London",
        **kw,  # type: ignore[arg-type]
    )


def _words(text: str) -> int:
    return len(text.split())


def test_the_realistic_boilerplate_is_realistically_long() -> None:
    # A short body is what hid this defect: the fixture's bodies were half role text.
    assert 380 <= _words(BOILER) <= 520


def test_p1_two_teams_with_heavy_boilerplate_stay_separate(store: ProfileStore) -> None:
    a, b = _long(TEAM_A), _long(TEAM_B)
    assert not same_board_twin(a, b)
    assert collect_offer(store, a, at=NOW).added_as_new
    assert collect_offer(store, b, at=NOW).added_as_new


def test_p2_one_template_with_a_different_team_sentence_stays_separate() -> None:
    template = "You will own a service end to end, from design to on call. {team} Ship weekly."
    a = _long(template.format(team="You join the Consumer team, building the chat product."))
    b = _long(template.format(team="You join the Developer Platform team, building the API."))
    assert not same_board_twin(a, b)


def test_p3_a_different_contract_type_stays_separate() -> None:
    a = _long("Engagement: permanent, full-time. " + TEAM_A)
    b = _long("Engagement: twelve month fixed-term contract. " + TEAM_A)
    assert not same_board_twin(a, b)


def test_p4_a_different_level_and_pay_band_stays_separate() -> None:
    a = _long("Level: L4. Pay band 180,000 to 220,000 USD. " + TEAM_A)
    b = _long("Level: L6. Pay band 300,000 to 405,000 USD. " + TEAM_A)
    assert not same_board_twin(a, b)


def test_p5_an_agencys_two_clients_stay_separate() -> None:
    footer = "Hays is a leading recruiter. " + BOILER
    a = _offer(
        "Our client, a large insurer, needs a Java developer to modernise claims systems. "
        + footer,
        url="https://g.test/h1",
        location="Leeds",
        company="Hays",
        title="Java Developer",
    )
    b = _offer(
        "Our client, a growth stage fintech, needs a Java developer to build payment rails. "
        + footer,
        url="https://g.test/h2",
        location="Leeds",
        company="Hays",
        title="Java Developer",
    )
    assert not same_board_twin(a, b)


def test_a_real_multi_office_twin_with_the_office_in_the_body_still_merges(
    store: ProfileStore,
) -> None:
    def office(place: str) -> Offer:
        text = f"{TEAM_A}\nLocation: {place}\n{BOILER}"
        return _offer(text, url=f"https://g.test/{place}", location=place)

    first, second = office("London"), office("Dublin")
    assert collect_offer(store, first, at=NOW).added_as_new
    assert collect_offer(store, second, at=NOW).duplicate_of == first.id


def test_a_body_naming_another_city_than_its_location_is_not_rewritten() -> None:
    # Only the offer's own declared place is removed, never a list of cities.
    a = _offer(f"{TEAM_A} Based in Paris. {BOILER}", url="https://g.test/p", location="London")
    b = _offer(f"{TEAM_A} Based in Berlin. {BOILER}", url="https://g.test/q", location="London")
    assert not same_board_twin(a, b)


def test_the_threshold_is_pinned_from_both_sides() -> None:
    base = f"{TEAM_A}\n{BOILER}"
    words = base.split()
    end = list(words)
    end[-1] = "CHANGED"  # one word of ~450: the closest a different advert can get
    noise = base.upper().replace(".", ";").replace("\n", "  ")  # case, punctuation, spacing

    def offer(text: str, n: int) -> Offer:
        return _offer(text, url=f"https://g.test/t{n}", location="London")

    original = offer(base, 0)
    just_under, just_over = offer(" ".join(end), 1), offer(noise, 2)
    # Guard the fixture: the two pairs straddle the threshold, closely.
    under_score = same_board_body_similarity(original, just_under)
    over_score = same_board_body_similarity(original, just_over)
    assert 0.99 < under_score < SAME_BOARD_TEXT_THRESHOLD <= over_score
    assert not same_board_twin(original, just_under)
    assert same_board_twin(original, just_over)


def test_a_stub_body_never_merges() -> None:
    # Fewer words than one shingle: equal text says nothing about equal vacancies.
    a = _offer("Software Engineer London, UK", url="https://g.test/s1", location="London")
    b = _offer("Software Engineer London, UK ", url="https://g.test/s2", location="London")
    assert not same_board_twin(a, b)
    assert same_board_body_similarity(a, b) == 0.0


# --- #865: follow-ups from the second readers of #871 --------------------------


def _pair(
    a_text: str, b_text: str, *, loc_a: str = "London", loc_b: str = "London"
) -> tuple[Offer, Offer]:
    return (
        _offer(a_text, url="https://g.test/n1", location=loc_a),
        _offer(b_text, url="https://g.test/n2", location=loc_b),
    )


@pytest.mark.parametrize(
    ("one", "other"),
    [("C++", "C"), ("C#", "C"), ("C++", "C#"), ("£60,000", "€60,000"), ("$60,000", "€60,000")],
)
def test_a_symbol_inside_a_token_makes_a_different_advert(one: str, other: str) -> None:
    a, b = _pair(f"{TEAM_A} Required: {one}. {BOILER}", f"{TEAM_A} Required: {other}. {BOILER}")
    assert not same_board_twin(a, b)


def test_a_short_country_code_is_stripped_only_in_the_case_it_is_declared() -> None:
    """`US` in the location must not delete the word `us` from one body only."""
    a, b = _pair(
        f"{TEAM_A} Join us. {BOILER}",
        f"{TEAM_A} Join. {BOILER}",
        loc_a="New York, US",
        loc_b="London, UK",
    )
    assert not same_board_twin(a, b)
    c, d = _pair(
        f"{TEAM_A} Based in New York, US. {BOILER}",
        f"{TEAM_A} Based in London, UK. {BOILER}",
        loc_a="New York, US",
        loc_b="London, UK",
    )
    assert same_board_twin(c, d)


def test_a_one_word_difference_in_a_very_long_body_is_not_a_twin() -> None:
    """Pins the threshold at 1.0: at 0.999 a 2,500-word body one word apart merges."""
    words = [f"w{n}" for n in range(2500)]
    changed = [*words[:-1], "CHANGED"]
    a, b = _pair(" ".join(words), " ".join(changed))
    assert 0.999 <= same_board_body_similarity(a, b) < SAME_BOARD_TEXT_THRESHOLD
    assert not same_board_twin(a, b)


def test_places_are_removed_part_by_part_not_only_whole() -> None:
    """Only `Hamburg` and `Germany` appear in the body, never `Hamburg, Germany`."""
    a, b = _pair(
        f"{TEAM_A} Office: Hamburg. {BOILER} Germany.",
        f"{TEAM_A} Office: Munich. {BOILER} Germany.",
        loc_a="Hamburg, Germany",
        loc_b="Munich, Germany",
    )
    assert same_board_twin(a, b)


def test_a_title_differing_only_in_punctuation_is_left_to_the_batch_pass(
    store: ProfileStore,
) -> None:
    """The `posting_key` prefilter is the only thing between these two: same vacancy,
    same body, but the title text differs, so a stored copy is not read for it."""
    a = _offer(
        f"{TEAM_A} {BOILER}",
        url="https://g.test/k1",
        location="London",
        title="Backend Engineer (Senior)",
    )
    b = _offer(
        f"{TEAM_A} {BOILER}",
        url="https://g.test/k2",
        location="Dublin",
        title="Backend Engineer, Senior",
    )
    assert same_board_twin(a, b)
    assert collect_offer(store, a, at=NOW).added_as_new
    assert collect_offer(store, b, at=NOW).added_as_new
