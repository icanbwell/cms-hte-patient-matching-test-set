"""Unit tests for near_miss.py."""

from __future__ import annotations

from identity_guard import SSN_SYSTEM
from near_miss import (
    KINDS,
    PAIR_TYPE_BY_KIND,
    NearMiss,
    find_near_misses,
    limit_per_kind,
)


def _p(id_, first, family, dob, zip_="10001", street="1 MAIN ST", phone=None, ssn=None):
    patient = {
        "resourceType": "Patient",
        "id": id_,
        "name": [{"use": "official", "family": family, "given": [first]}],
        "birthDate": dob,
        "address": [
            {"line": [street], "city": "NY", "state": "NY", "postalCode": zip_}
        ],
    }
    if phone:
        patient["telecom"] = [{"system": "phone", "value": phone, "rank": 1}]
    if ssn:
        patient["identifier"] = [{"system": SSN_SYSTEM, "value": ssn}]
    return patient


QUERY = _p("q", "JANE", "SMITH", "1980-01-01")


def _find(records, queries=(QUERY,), **kwargs):
    return find_near_misses(list(queries), [records], **kwargs)


def _kinds(result):
    return {(m.decoy["id"], m.kind) for m in result.near_misses}


class TestKinds:
    def test_same_dob_and_zip_with_a_different_surname_is_a_hard_negative(self):
        result = _find([_p("d", "ROBERT", "JONES", "1980-01-01", street="9 ELM ST")])
        assert _kinds(result) == {("d", "dob_zip")}
        miss = result.near_misses[0]
        assert miss.pair_type == "hard_negative"
        assert dict(miss.shared_fields) == {
            "postalCode": "10001",
            "birthDate": "1980-01-01",
        }

    def test_name_within_one_edit_with_different_dob_and_zip(self):
        result = _find([_p("d", "JANE", "SMYTH", "1990-05-05", zip_="20002")])
        assert _kinds(result) == {("d", "name")}
        assert dict(result.near_misses[0].shared_fields) == {"name_distance": "1"}

    def test_identical_name_with_different_dob_and_zip_has_distance_zero(self):
        result = _find([_p("d", "JANE", "SMITH", "1990-05-05", zip_="20002")])
        assert dict(result.near_misses[0].shared_fields) == {"name_distance": "0"}

    def test_name_two_edits_away_is_not_a_near_miss(self):
        assert (
            _find([_p("d", "JANE", "SMOOTH", "1990-05-05", zip_="20002")]).near_misses
            == []
        )

    def test_same_surname_and_zip_with_close_birth_years_is_a_sibling(self):
        result = _find([_p("d", "JOHN", "SMITH", "1982-05-05")])
        assert _kinds(result) == {("d", "sibling")}
        assert result.near_misses[0].pair_type == "sibling_negative"
        assert dict(result.near_misses[0].shared_fields)["age_gap_years"] == "2"

    def test_same_surname_and_zip_with_a_wide_birth_gap_is_surname_zip(self):
        result = _find([_p("d", "JOHN", "SMITH", "1950-05-05")])
        assert _kinds(result) == {("d", "surname_zip")}
        assert result.near_misses[0].pair_type == "near_miss_negative"

    def test_shared_street_and_zip_with_a_different_surname_is_an_address_miss(self):
        result = _find([_p("d", "ROBERT", "JONES", "1950-05-05")])
        assert _kinds(result) == {("d", "address")}

    def test_shared_phone_with_a_different_surname_is_a_phone_miss(self):
        query = _p("q", "JANE", "SMITH", "1980-01-01", phone="347-984-6839")
        result = _find(
            [
                _p(
                    "d",
                    "ROBERT",
                    "JONES",
                    "1950-05-05",
                    zip_="20002",
                    street="9 ELM ST",
                    phone="(347) 984-6839",
                )
            ],
            queries=(query,),
        )
        assert _kinds(result) == {("d", "phone")}

    def test_shared_dob_only_is_a_dob_only_miss(self):
        result = _find(
            [_p("d", "ROBERT", "JONES", "1980-01-01", zip_="20002", street="9 ELM ST")]
        )
        assert _kinds(result) == {("d", "dob_only")}

    def test_a_record_qualifying_for_several_kinds_is_filed_under_the_first(self):
        result = _find(
            [_p("d", "ROBERT", "JONES", "1980-01-01")]
        )  # dob_zip, address, dob_only
        assert _kinds(result) == {("d", "dob_zip")}

    def test_every_kind_maps_to_a_pair_type(self):
        assert set(PAIR_TYPE_BY_KIND) == set(KINDS)


class TestGuards:
    def test_the_query_itself_and_excluded_ids_are_never_returned(self):
        records = [
            QUERY,
            _p("skip", "ROBERT", "JONES", "1980-01-01"),
            _p("keep", "ALICE", "BROWN", "1980-01-01"),
        ]
        result = _find(records, exclude_ids={"skip"})
        assert {m.decoy["id"] for m in result.near_misses} == {"keep"}

    def test_a_record_sharing_the_queries_ssn_is_never_returned(self):
        query = _p("q", "JANE", "SMITH", "1980-01-01", ssn="892-39-5115")
        twin = _p("t", "ROBERT", "JONES", "1980-01-01", ssn="892-39-5115")
        assert _find([twin], queries=(query,)).near_misses == []

    def test_a_query_with_no_look_alikes_yields_nothing(self):
        lonely = {"resourceType": "Patient", "id": "lonely"}
        result = _find(
            [_p("d", "ROBERT", "JONES", "1950-05-05", zip_="20002")], queries=(lonely,)
        )
        assert result.near_misses == []


class TestDuplicateGuards:
    def test_ssn_one_digit_off_is_rejected(self):
        query = _p("q", "JANE", "SMITH", "1980-01-01", ssn="892-39-5115")
        typo = _p("t", "ROBERT", "JONES", "1980-01-01", ssn="892-39-5116")
        assert _find([typo], queries=(query,)).near_misses == []

    def test_name_typo_with_close_dob_is_rejected(self):
        query = _p("q", "EUGENE", "BENALLY", "1971-02-02", zip_="30003")
        typo = _p("t", "ETGENE", "BENALLY", "1971-02-03", zip_="30003")
        assert _find([typo], queries=(query,)).near_misses == []

    def test_identical_name_with_dob_one_digit_apart_is_rejected(self):
        query = _p("q", "ROSALIND", "VANDERMEER", "1980-06-15")
        twin = _p("t", "ROSALIND", "VANDERMEER", "1980-06-25", zip_="20002")
        assert _find([twin], queries=(query,)).near_misses == []

    def test_shared_phone_with_close_dob_is_rejected(self):
        query = _p("q", "HARRIS", "GREENE", "1980-06-15", phone="347-984-6839")
        typo = _p(
            "t", "HARRISS", "GREEN", "1980-06-16", zip_="20002", phone="3479846839"
        )
        assert _find([typo], queries=(query,)).near_misses == []

    def test_identical_name_with_a_clearly_different_dob_is_kept(self):
        query = _p("q", "ROSALIND", "VANDERMEER", "1950-06-15")
        other = _p("t", "ROSALIND", "VANDERMEER", "1971-06-15", zip_="20002")
        assert _kinds(_find([other], queries=(query,))) == {("t", "name")}

    def test_decoy_matching_the_original_is_rejected_when_originals_given(self):
        # Household assignment dropped the minor's SSN from the housed query.
        original = _p("q", "DONNA", "RACETTE", "2010-01-01", ssn="892-39-5115")
        housed = _p("q", "DONNA", "RACETTE", "2010-01-01")
        records = [
            _p("d", "ROBERT", "JONES", "2010-01-01", zip_="20002", ssn="892-39-5115")
        ]
        assert _find(records, queries=(housed,)).near_misses != []
        result = _find(records, queries=(housed,), originals={"q": original})
        assert result.near_misses == []

    def test_originals_for_other_queries_do_not_leak(self):
        original = _p("other", "DONNA", "RACETTE", "2010-01-01", ssn="892-39-5115")
        records = [_p("d", "ROBERT", "JONES", "1980-01-01", ssn="892-39-5115")]
        result = _find(records, originals={"other": original})
        assert _kinds(result) == {("d", "dob_zip")}


class TestNameEditHits:
    def test_one_sided_insertion_is_a_name_hit(self):
        result = _find([_p("d", "JANE", "SMITHE", "1990-05-05", zip_="20002")])
        assert dict(result.near_misses[0].shared_fields) == {"name_distance": "1"}

    def test_one_sided_deletion_is_a_name_hit(self):
        result = _find([_p("d", "JANE", "SMIT", "1990-05-05", zip_="20002")])
        assert dict(result.near_misses[0].shared_fields) == {"name_distance": "1"}


class TestReservoir:
    def _big_flood(self, n=200):
        return [
            _p(f"d{i:03d}", "ROBERT", f"JONES{i}", "1980-01-01", zip_=f"2{i:04d}")
            for i in range(n)
        ]

    def _ids(self, seed):
        result = _find(self._big_flood(), per_kind_cap=3, seed=seed)
        return {m.decoy["id"] for m in result.near_misses}

    def test_late_records_can_replace_early_ones(self):
        survivors = set().union(*(self._ids(seed) for seed in range(10)))
        assert any(i >= "d100" for i in survivors)  # beyond the first `cap` arrivals
        assert len(self._ids(0)) == 3

    def test_different_seeds_give_different_selections(self):
        selections = {frozenset(self._ids(seed)) for seed in range(10)}
        assert len(selections) > 1


class TestEmailKind:
    def test_shared_email_with_a_different_surname_is_an_email_miss(self):
        query = _p("q", "JANE", "SMITH", "1980-01-01")
        query["telecom"] = [{"system": "email", "value": "Jane@Example.com"}]
        decoy = _p(
            "d", "ROBERT", "JONES", "1950-05-05", zip_="20002", street="9 ELM ST"
        )
        decoy["telecom"] = [{"system": "email", "value": "jane@example.com "}]
        result = _find([decoy], queries=(query,))
        assert _kinds(result) == {("d", "email")}
        assert result.near_misses[0].pair_type == "near_miss_negative"


class TestCapsAndDeterminism:
    def _flood(self):
        return [
            _p(f"d{i}", "ROBERT", f"JONES{i}", "1980-01-01", zip_=f"2{i:04d}")
            for i in range(10)
        ]

    def test_per_kind_cap_limits_kept_decoys_and_reports_seen(self):
        result = _find(self._flood(), per_kind_cap=3)
        assert len(result.near_misses) == 3
        assert result.yield_by_kind["dob_only"] == {"queries": 1, "kept": 3, "seen": 10}
        assert result.yield_by_kind["dob_zip"] == {"queries": 0, "kept": 0, "seen": 0}

    def test_same_seed_gives_the_same_decoys(self):
        first = _find(self._flood(), seed=7)
        second = _find(self._flood(), seed=7)
        assert [m.decoy["id"] for m in first.near_misses] == [
            m.decoy["id"] for m in second.near_misses
        ]

    def test_batches_are_consumed_once_from_a_generator(self):
        batches = (batch for batch in [self._flood()[:5], self._flood()[5:]])
        result = find_near_misses([QUERY], batches, per_kind_cap=10)
        assert len(result.near_misses) == 10

    def test_output_interleaves_kinds_per_query(self):
        records = [
            _p("a", "ROBERT", "JONES", "1980-01-01", zip_="20002"),
            _p("b", "ALICE", "BROWN", "1980-01-01", zip_="20003"),
            _p("c", "JOHN", "SMITH", "1982-05-05"),
        ]
        kinds = [m.kind for m in _find(records).near_misses]
        assert kinds == ["sibling", "dob_only", "dob_only"]


class TestLimitPerKind:
    def _misses(self):
        query = _p("q", "Eugene", "Benally", "1971-01-01")
        other = _p("q2", "Maria", "Lopez", "1999-09-09")
        decoys = [_p(f"d{i}", "Ana", f"Name{i}", "1971-01-01") for i in range(6)]
        return (
            [NearMiss(query, d, "dob_only", {}) for d in decoys]
            + [NearMiss(query, decoys[0], "address", {})]
            + [NearMiss(other, d, "dob_only", {}) for d in decoys[:2]]
        )

    def test_keeps_at_most_cap_per_query_and_kind(self):
        kept = limit_per_kind(self._misses(), 3, seed=0)
        by_slot = {}
        for miss in kept:
            by_slot.setdefault((miss.query_id, miss.kind), []).append(miss)
        assert len(by_slot[("q", "dob_only")]) == 3
        assert len(by_slot[("q", "address")]) == 1
        assert len(by_slot[("q2", "dob_only")]) == 2

    def test_is_deterministic_and_preserves_input_order(self):
        misses = self._misses()
        first = limit_per_kind(misses, 3, seed=0)
        assert first == limit_per_kind(misses, 3, seed=0)
        positions = [misses.index(m) for m in first]
        assert positions == sorted(positions)

    def test_the_choice_depends_on_the_seed(self):
        chosen = {
            tuple(m.decoy["id"] for m in limit_per_kind(self._misses(), 2, seed=s))
            for s in range(10)
        }
        assert len(chosen) > 1

    def test_a_cap_above_the_group_size_keeps_everything(self):
        misses = self._misses()
        assert limit_per_kind(misses, 99, seed=0) == misses
