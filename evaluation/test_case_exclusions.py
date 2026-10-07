"""Tests for case_exclusions.py: the rule-29 exclusion and the policy that
applies it inside both generators."""

from __future__ import annotations

import copy
from typing import Any, Dict

from case_exclusions import (
    ExclusionPolicy,
    ExclusionRule,
    no_exclusions,
    only_matchable_by_removed_rule_29,
)
from labeled_pairs import generate_raw_pairs
from population_cases import build_population_dataset


def _patient(id_: str = "p1", **overrides: Any) -> Dict[str, Any]:
    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"family": "Aamodt", "given": ["Allison"]}],
        "birthDate": "1976-03-24",
        "telecom": [{"system": "phone", "value": "718-124-7797"}],
        "address": [{"line": ["571 Elton St"], "postalCode": "11208"}],
        "identifier": [],
    }
    patient.update(overrides)
    return patient


def _variant(patient: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    variant = copy.deepcopy(patient)
    variant.update(overrides)
    return variant


class TestRule29Exclusion:
    def test_dob_beyond_tolerance_with_name_phone_zip_intact_is_excluded(self):
        p = _patient()
        assert only_matchable_by_removed_rule_29(p, _variant(p, birthDate="1976-05-24"))

    def test_dob_within_one_day_is_kept(self):
        p = _patient()
        assert not only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-03-25")
        )

    def test_changed_phone_means_rule_29_never_matched_so_kept(self):
        p = _patient()
        other_phone = [{"system": "phone", "value": "212-555-0100"}]
        assert not only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24", telecom=other_phone)
        )

    def test_changed_zip_is_kept(self):
        p = _patient()
        other_zip = [{"line": ["571 Elton St"], "postalCode": "10001"}]
        assert not only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24", address=other_zip)
        )

    def test_unrelated_first_name_is_kept(self):
        p = _patient()
        renamed = [{"family": "Aamodt", "given": ["Zebedee"]}]
        assert not only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24", name=renamed)
        )

    def test_one_edit_family_name_still_counts_as_rule_29_match(self):
        p = _patient()
        typo = [{"family": "Aamoot", "given": ["Allison"]}]
        assert only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24", name=typo)
        )

    def test_nickname_counts_as_first_name_match(self):
        p = _patient(name=[{"family": "Smith", "given": ["Katherine"]}])
        nick = [{"family": "Smith", "given": ["Kate"]}]
        assert only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24", name=nick)
        )

    def test_diacritics_do_not_hide_a_name_match(self):
        p = _patient(name=[{"family": "Munoz", "given": ["Allison"]}])
        accented = [{"family": "Muñoz", "given": ["Allison"]}]
        assert only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24", name=accented)
        )

    def test_dob_free_rule_that_still_links_the_pair_keeps_it(self):
        # Rule 13: First Name + Phone + SSN last 4 needs no DOB, so a DOB error
        # does not make this pair rule-29-only.
        ssn = [{"system": "http://hl7.org/fhir/sid/us-ssn", "value": "892-39-5115"}]
        p = _patient(identifier=ssn)
        assert not only_matchable_by_removed_rule_29(
            p, _variant(p, birthDate="1976-05-24")
        )

    def test_missing_dob_fails_closed_and_is_excluded(self):
        p = _patient()
        no_dob = _variant(p)
        del no_dob["birthDate"]
        assert only_matchable_by_removed_rule_29(p, no_dob)


class TestExclusionPolicy:
    def test_counts_each_drop_by_rule_name(self):
        policy = ExclusionPolicy()
        p = _patient()
        assert policy.excludes(p, _variant(p, birthDate="1976-05-24"))
        assert not policy.excludes(p, _variant(p, birthDate="1976-03-25"))
        assert policy.counts == {"rule_29_removed": 1}
        assert policy.summary() == "rule_29_removed=1"

    def test_custom_rule_can_be_registered(self):
        drop_all = ExclusionRule("drop_all", "test", lambda q, c: True)
        policy = ExclusionPolicy(rules=(drop_all,))
        assert policy.excludes(_patient(), _patient("p2"))
        assert policy.counts == {"drop_all": 1}

    def test_no_exclusions_policy_drops_nothing(self):
        p = _patient()
        assert not no_exclusions().excludes(p, _variant(p, birthDate="1976-05-24"))


class TestGeneratorsApplyThePolicy:
    def _patients(self):
        return [
            _patient(
                f"p{i}",
                name=[{"family": f"Familyname{i}", "given": ["Allison"]}],
                birthDate=f"19{50 + i}-03-24",
            )
            for i in range(40)
        ]

    def test_labeled_pairs_emit_no_rule_29_only_true_match(self):
        policy = ExclusionPolicy()
        pairs = list(generate_raw_pairs(self._patients(), exclusions=policy))
        assert not any(
            p.is_true_match
            and only_matchable_by_removed_rule_29(p.query_patient, p.candidate_patient)
            for p in pairs
        )

    def test_labeled_pairs_without_policy_keep_what_it_would_drop(self):
        patients = self._patients()
        policy = ExclusionPolicy()
        kept = list(generate_raw_pairs(patients, exclusions=policy))
        everything = list(generate_raw_pairs(patients, exclusions=no_exclusions()))
        assert policy.counts["rule_29_removed"] > 0
        assert len(everything) - len(kept) == policy.counts["rule_29_removed"]

    def test_negatives_are_never_excluded(self):
        patients = self._patients()
        kept = list(generate_raw_pairs(patients, exclusions=ExclusionPolicy()))
        everything = list(generate_raw_pairs(patients, exclusions=no_exclusions()))
        assert sum(not p.is_true_match for p in kept) == sum(
            not p.is_true_match for p in everything
        )

    def test_population_expected_matches_exclude_rule_29_only_candidates(self):
        policy = ExclusionPolicy()
        dataset = build_population_dataset(self._patients(), exclusions=policy)
        for case in dataset.cases:
            for match_id in case.expected_match_ids:
                assert not only_matchable_by_removed_rule_29(
                    case.query_patient, dataset.candidates[match_id]
                )
        assert policy.counts["rule_29_removed"] > 0
