import pytest

from pipeline import map_islands as mi
from pipeline.export_web import build_network

ISLANDS = [
    {"island_id": "66", "name": "Badidhoo", "atoll_code": "Dh", "lat": 2.9367, "lon": 72.9902, "population": 500},
    {"island_id": "1050", "name": "Meedhoo", "atoll_code": "Dh", "lat": 2.9980, "lon": 73.0073, "population": 900},
    {"island_id": "152", "name": "Gamu", "atoll_code": "L", "lat": 1.9143, "lon": 73.5409, "population": 3000},
    {"island_id": "1", "name": "Elsewhere", "atoll_code": "HA", "lat": 6.9, "lon": 73.0, "population": 100},
]
COORDS = {"Dh.Bandidhoo": {"lat": "2.9368", "lon": "72.9902"}, "Dh.Meedhoo": {"lat": "2.9985", "lon": "73.0070"},
          "L.Gan": {"lat": "1.9066", "lon": "73.5397"}, "Dh.Farfaraway": {"lat": "2.5", "lon": "72.5"}}


def manual_file(tmp_path, body=""):
    path = tmp_path / "manual.csv"
    path.write_text("stop_name,island_ids,note\n" + body, encoding="utf-8")
    return path


def test_exact_and_spelling_variant_matched_within_atoll(tmp_path):
    result = mi.map_stops(ISLANDS, COORDS, manual_file(tmp_path), ["Dh.Bandidhoo", "Dh.Meedhoo"])
    assert [(m.island_ids, m.method) for m in result] == [(["66"], "spelling_variant"), (["1050"], "exact")]


def test_unmatched_stop_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="L.Gan"):
        mi.map_stops(ISLANDS, COORDS, manual_file(tmp_path), ["L.Gan"])


def test_similar_name_too_far_away_is_not_matched(tmp_path):
    coords = {"Dh.Meedhoo": {"lat": "2.5", "lon": "72.5"}}  # ~60 km from Census Meedhoo
    with pytest.raises(ValueError):
        mi.map_stops(ISLANDS, coords, manual_file(tmp_path), ["Dh.Meedhoo"])


def test_manual_override_and_non_census_stop(tmp_path):
    manual = manual_file(tmp_path, "L.Gan,152,official name Gamu\nDh.Farfaraway,,airport\n")
    result = mi.map_stops(ISLANDS, COORDS, manual, ["L.Gan", "Dh.Farfaraway"])
    assert [(m.island_ids, m.method) for m in result] == [(["152"], "manual"), ([], "manual")]


def test_manual_override_rejects_unknown_island(tmp_path):
    with pytest.raises(ValueError, match="unknown Census island"):
        mi.map_stops(ISLANDS, COORDS, manual_file(tmp_path, "L.Gan,999,typo\n"), ["L.Gan"])


def test_coverage_statuses():
    mapping = [mi.StopIslands("Dh.Meedhoo", ["1050"], "exact", 1.0, 0.1, "")]
    network = {"stops": [{"id": "DH_MEEDHOO", "atoll": "Dh"}],
               "routes": [{"id": "288", "trips": [{"calls": [[0, 490], [0, 600]]}]}]}
    status = {r["name"]: r["ferry_status"] for r in mi.coverage(mapping, ISLANDS, network)}
    assert status == {"Meedhoo": "served", "Badidhoo": "no_route_in_data",
                      "Gamu": "atoll_not_in_data", "Elsewhere": "atoll_not_in_data"}


def test_real_data_every_stop_resolves_and_population_is_conserved():
    islands = mi.load_census_islands()
    mapping = mi.map_stops(islands)
    assert len(mapping) == 77
    assert sum(not m.island_ids for m in mapping) == 4  # 2 airports, Felivaru, Madivaru
    cov = mi.coverage(mapping, islands, build_network())
    assert len(cov) == len(islands) == 193
    assert sum(r["population"] for r in cov) == 448_819
    mapped = {i for m in mapping for i in m.island_ids}
    assert {r["island_id"] for r in cov if r["ferry_status"] == "served"} == mapped
