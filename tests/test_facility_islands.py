import csv

from data import build

ISLANDS = [
    {"island_id": "66", "name": "Badidhoo", "atoll_code": "Dh"},
    {"island_id": "1050", "name": "Meedhoo", "atoll_code": "Dh"},
    {"island_id": "605", "name": "Meedhoo", "atoll_code": "R"},
    {"island_id": "299", "name": "Hulhudhoo", "atoll_code": "S"},
    {"island_id": "272", "name": "Meedhoo", "atoll_code": "S"},
    {"island_id": "658", "name": "Nolhivaramu", "atoll_code": "HDh"},
    {"island_id": "416", "name": "Nolhivaranfaru", "atoll_code": "HDh"},
    {"island_id": "48", "name": "Kulhudhuffushi", "atoll_code": "HDh"},
    {"island_id": "85", "name": "Magoodhoo", "atoll_code": "F"},
    {"island_id": "907", "name": "Magoodhoo", "atoll_code": "N"},
    {"island_id": "459", "name": "Dhidhdhoo", "atoll_code": "Adh"},
    {"island_id": "69", "name": "Maafushi", "atoll_code": "K"},
    {"island_id": "531", "name": "Mulah", "atoll_code": "M"},
]


def test_repeated_island_name_resolved_by_atoll():
    assert build.infer_atoll_island("Dhaalu Meedhoo Health Centre", ISLANDS) == ("1050", "atoll_name_derived")
    assert build.infer_atoll_island("Raa Meedhoo Health Centre", ISLANDS) == ("605", "atoll_name_derived")
    assert build.infer_island("Raa Meedhoo Health Centre", ISLANDS) is None


def test_spelling_variant_within_atoll():
    assert build.infer_atoll_island("Dhaalu Bandidhoo Health Centre", ISLANDS) == ("66", "atoll_spelling_variant")
    assert build.infer_atoll_island("Dhaalu Bandidhoo HC", ISLANDS) == ("66", "atoll_spelling_variant")
    assert build.infer_atoll_island("Haa Dhaalu Nolhivaram Health Center", ISLANDS) == ("658", "atoll_spelling_variant")


def test_no_atoll_prefix_or_no_close_island():
    assert build.infer_atoll_island("IGMH", ISLANDS) == (None, None)
    assert build.infer_atoll_island("Dhaalu Atoll Hospital", ISLANDS) == (None, None)
    assert build.infer_atoll_island("Dhaalu Farfaraway Health Centre", ISLANDS) == (None, None)


def test_manual_lookup_takes_precedence():
    manual = {"Seenu Hulhu-meedhoo Health Centre": {"island_id": "272", "source_url": "https://example.org"}}
    assert build.locate_health_facility("Seenu Hulhu-meedhoo Health Centre", ISLANDS, manual) == ("272", "manual_sourced", "https://example.org")
    assert build.locate_health_facility("Kulhudhuffushi Regional Hospital", ISLANDS, {}) == ("48", "unique_name_derived", None)
    assert build.locate_health_facility("Dhaalu Atoll Hospital", ISLANDS, {}) == (None, "unresolved", None)


def test_manual_lookup_rows_are_sourced():
    with build.FACILITY_ISLANDS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        assert row["island_id"] and row["source_url"].startswith("http"), row


def test_abbreviated_atoll_prefix_for_schools():
    assert build.infer_atoll_island("F. Magoodhoo School", ISLANDS) == ("85", "atoll_name_derived")
    assert build.infer_atoll_island("N. Magoodhoo School", ISLANDS) == ("907", "atoll_name_derived")
    assert build.infer_atoll_island("ADh. Dhidhdhoo School", ISLANDS) == ("459", "atoll_name_derived")
    assert build.infer_atoll_island("Hdh. Kulhudhuffushi Primary School", ISLANDS) == ("48", "atoll_name_derived")


def test_atoll_schools_and_dotted_names_are_not_islands():
    assert build.locate_by_name("Dh. Atoll School", ISLANDS) == (None, "unresolved")
    assert build.locate_by_name("M. Atoll Education Center", ISLANDS) == (None, "unresolved")
    assert build.split_atoll_prefix("M.C.S Medical Centre 2- K. Maafushi") == (None, "M.C.S Medical Centre 2- K. Maafushi")
    assert build.locate_by_name("M.C.S Medical Centre 2- K. Maafushi", ISLANDS) == ("69", "unique_name_derived")
