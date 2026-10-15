"""Unit tests for near_miss.py."""

from __future__ import annotations

from identity_guard import SSN_SYSTEM
from near_miss import KINDS, PAIR_TYPE_BY_KIND, find_near_misses


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
