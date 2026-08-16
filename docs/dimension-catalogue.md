# Dimension catalogue — candidates for the model beyond candidate zero

**Status: a candidate list, not the model.** Nothing here is committed to
`dimensions/*.yaml` by virtue of appearing here. This is the pool T24 (candidate attributes) and
T26 (model v1) draw from, and every **matched** dimension in it must earn its
cues from real ads in the broadened corpus (T25) before it enters the model.
Writing cues from this document directly would repeat, at four times the scale,
the mistake PR #8's review caught: eight cues written from imagined phrasing,
each matching the wrong thing or nothing.

Traits and facts are different — they are elicited from the person, never
extracted from an ad, so they do not need corpus evidence to exist. They need an
interview question that works (T27).

## Why this list is shaped by jobs, not by one job

v0's 22 dimensions came from remote programming ads. They encode assumptions
that quietly fail elsewhere: that pay is annual and salaried (a waiter's is
hourly with tips, a driver's may be per-route), that "remote" is the axis that
matters (a nurse cannot work remotely and needs *shift predictability* instead),
that career progression means levels (a diving instructor's means seasons and
certifications), that the working day is continuous (Spanish hospitality runs
`jornada partida` — a split shift with three hours off in the middle).

The test applied to every entry below: **would this matter to a waiter, a
nurse, a lorry driver, a field labourer, a teacher, a diving instructor, and a
software engineer?** Where the answer is "only to some", the entry says which —
a dimension that applies to one family is fine, as long as it is not assumed
universal.

---

## 1. Candidate facts — hard constraints

Filtered against an ad-side requirement, never traded off against a preference.
An unstated fact is **unknown, not satisfied** (T24's rule): it neither passes
nor vetoes, and surfaces as something the interview still owes the candidate.

### 1.1 Right to work and jurisdiction

| id | what it holds | who it decides everything for |
|----|----------------|-------------------------------|
| `work_authorisation` | countries the candidate may legally work in, and on what basis | migrants, students on study visas, non-EU applicants in Spain, anyone applying abroad |
| `visa_sponsorship_needed` | whether an offer must include sponsorship to be real | the same, and it is the single most common silent rejection |
| `right_to_work_expiry` | when the current permit lapses | seasonal and permit-tied workers, for whom a 3-year contract is fiction |
| `criminal_record_check` | willingness and ability to pass a background check | childcare, teaching, security, healthcare, driving |

### 1.2 Cross-border and payment arrangement

The arrangement the owner described — *work from Spain, be paid by a foreign
employer at their market rate, in euros, under Spanish rules* — is not one
dimension. It is the six below, and conflating them is how a tool tells someone
an impossible offer is a match.

| id | what it holds | why it is separate |
|----|----------------|--------------------|
| `employer_country` | where the paying entity is | determines the salary benchmark |
| `work_country` | where the candidate physically is | determines tax residency and labour law |
| `payroll_arrangement` | direct local contract, employer-of-record, foreign payroll, or self-employed invoicing | an EOR offer and a "become an autónomo and invoice us" offer are wildly different in take-home and protection |
| `pay_currency` | EUR, USD, GBP … | currency risk is real income risk over a year |
| `social_security_regime` | which country's contributions and cover apply | pension, unemployment, sick pay — invisible at offer time, decisive later |
| `timezone_overlap_required` | hours of overlap the role demands | the constraint that makes "remote, any country" false in practice |

This cluster generalises well beyond the owner's case: a Colombian developer
hired by a US company, a Portuguese nurse recruited to Germany, a seasonal
picker moving between EU states, an English teacher paid in a soft currency.

### 1.3 Time and availability

| id | notes |
|----|-------|
| `contracted_hours_needed` | full-time, part-time, a specific number of hours — students and carers often need a *ceiling*, not a floor |
| `schedule_shape` | continuous day, split shift (`jornada partida`), shifts, nights, weekends, on-call |
| `fixed_unavailability` | school runs, study timetable, caring duties, religious observance, second job |
| `notice_period` | what they owe a current employer |
| `earliest_start` | and whether they need work *now* — an unemployed candidate and a passively-looking one are not the same user |
| `seasonal_availability` | summer only, harvest, academic year |
| `shift_predictability_needed` | how far ahead a rota must be published to be liveable — decisive in hospitality, retail and care, meaningless in salaried office work |

### 1.4 Pay

| id | notes |
|----|-------|
| `pay_floor` | the number below which an offer is not worth taking |
| `pay_target` | and the number they are aiming at — the gap between them is the negotiating range |
| `pay_period` | hourly, daily, monthly, annual, per-piece, per-route — assuming annual silently excludes most non-office work |
| `pay_basis` | fixed, commission, tips, piece rate, and the proportion that is variable |
| `in_kind_needs` | meals, accommodation, transport — decisive in agriculture, offshore, hospitality, live-in care |
| `benefit_needs` | health cover, pension, equipment — where public provision is thin, these are pay |

### 1.5 Place and movement

| id | notes |
|----|-------|
| `home_location` | where they are now |
| `commute_tolerance` | time or distance, and by which transport — "45 minutes by public transport" and "45 minutes by car" select different jobs |
| `relocation_willingness` | no / yes / conditional, and **what the condition is** — "for the right role" is not a yes |
| `remote_need` | the candidate side of `remote_arrangement`: required, preferred, indifferent, or unwanted (some people need to leave the house) |
| `travel_tolerance` | day trips, overnight, rotations away from home (offshore, tour, fieldwork) |
| `own_vehicle` | and whether they would use it for work |
| `driving_licence` | with category — B, C+E, D, forklift, tractor |

### 1.6 Credentials and capability

| id | notes |
|----|-------|
| `qualifications_held` | degrees, vocational certificates, apprenticeships |
| `licences_held` | medical registration, teaching qualification, diving instructor grade, food handling, security badge, crane, electrical |
| `languages` | per language, a level, and whether it is a *working* language — the difference between serving tourists and writing medical notes |
| `experience_years` | overall and per family |
| `first_job` | no work history at all — the branch that must exist, or every retrospective question tells a school leaver the tool is not for them |
| `equipment_owned` | tools, knives, laptop, PPE, instruments |
| `physical_capabilities` | lifting, standing, heights, night work, driving hours |
| `accommodations_needed` | what the workplace must provide — the Feina Activa slice is full of disability-hire ads, and the tool should serve that candidate rather than treat accommodation as an afterthought |

---

## 2. Candidate traits — elicited, never extracted

No ad wording evidences these. Their only source is the interview (T27) and the
story bank, and their evidence is episodes, never cue hits (D-2).

| id | the question behind it |
|----|------------------------|
| `ambition` | what they went after that nobody asked them to |
| `creativity` | when they made something that did not exist, at work or outside it |
| `learning_orientation` | what they studied for work on their own time, and who paid |
| `autonomy_preference` | a decision they made unsupervised, and one they wanted to make and could not |
| `structure_preference` | whether a day that repeats is restful or deadening |
| `risk_tolerance` | how they felt when an employer was visibly unstable |
| `pace_preference` | their busiest month, and what was still true a year later |
| `people_contact_appetite` | a day of customer contact they enjoyed, and one that emptied them |
| `conflict_tolerance` | an angry customer or colleague, and what they did |
| `leadership_appetite` | whether they want people reporting to them, and whether they have tried |
| `craft_pride` | work they would show someone, and why that one |
| `monotony_tolerance` | the most repetitive work they have done and how it went |
| `physicality_preference` | whether a desk is a relief or a sentence |
| `outdoor_preference` | weather as a working condition |
| `recognition_needs` | when they last felt their work was seen |
| `mission_sensitivity` | work they were proud to explain at a family dinner, and work they would not take again |
| `security_vs_upside` | a stable salary versus a variable one |
| `collaboration_style` | their best working week: who they talked to and what for |
| `resilience_pattern` | a failure and what they took from it — the lesson-extraction the interview owes them |
| `institution_preference` | big employer or small: which felt survivable |

Traits are the part most likely to be got wrong by asking directly. "Are you
creative?" measures self-image; "tell me about something you made" measures
behaviour (METHODS §2.1).

---

## 3. Matched dimensions — candidates for the widened model

The v0 22 are in `dimensions/README.md`. These extend them to families v0 never
sampled, and **none may enter the model without cues that fire on real ads**.

### 3.1 Time and load

`schedule_predictability` (how far ahead the rota is known) ·
`split_shift` (`jornada partida`) · `night_work` · `weekend_work` ·
`overtime_expectation` and whether it is paid · `seasonality` ·
`hours_guarantee` (fixed hours vs zero-hours vs "as needed") ·
`shift_length`

### 3.2 Conditions

`physical_demand` · `outdoor_work` · `hazard_exposure` ·
`noise_and_environment` · `uniform_or_dress_code` ·
`workplace_accessibility` · `equipment_provided` ·
`meals_or_accommodation_provided`

### 3.3 Work content

`customer_contact_intensity` · `supervision_closeness` · `team_size` ·
`task_variety` · `emergency_or_unplanned_work` · `documentation_burden` ·
`decision_authority`

### 3.4 Employment terms

`job_security` (contract type, turnover, probation length) ·
`probation_length` · `collective_agreement` (`convenio`) — decisive in Spain
and invisible to a model built on tech ads · `union_presence` ·
`notice_and_termination_terms` · `relocation_support_offered` ·
`visa_sponsorship_offered`

### 3.5 Progression and pay shape

`training_provided_paid` · `certification_sponsorship` ·
`promotion_path_named` · `pay_transparency` (v0 has it) ·
`variable_pay_share` (commission, tips, bonus) · `pay_review_cadence`

### 3.6 Employer character

`employer_size` · `employer_stage` (v0) · `family_business` ·
`public_or_private_sector` · `prestige_or_recognition` ·
`mission_domain` (health, education, defence, gambling, climate …) ·
`turnover_signals` (perpetual hiring for the same role)

---

## 4. What this changes about the shape of the model

Three observations that matter more than any single entry:

1. **The hard/soft split is not enough.** `pay_floor` is hard, `pay_target` is
   soft, and they are the same subject. T24's schema needs to hold a floor and
   an aspiration on one attribute rather than forcing two dimensions.
2. **Several facts are per-item, not scalar.** `languages` is a level per
   language; `licences_held` is a set; `work_authorisation` is per country. A
   single float cannot carry them, and pretending otherwise is what makes a
   filter silently pass.
3. **Some dimensions only apply to some families.** `split_shift` is
   meaningless for remote software and decisive for hospitality. The model needs
   applicability by job family, or `ontology_hit_rate` will read as low
   coverage when it is in fact correct silence — the same lesson as
   `language_slices_with_no_corpus_hit` in T3.

These three are recorded as design constraints for T24 and T26 rather than
resolved here.
