import csv

import pytest

from pipeline import build_gtfs as b
from pipeline.stops import DATA, load_stop_coords, stop_id

HEADER = "trip_id,schedule_idx,order,stop_name,stop_name_dv,timing\n"
COORDS = {"F.Nilandhoo": {"lat": "3.0573", "lon": "72.8881", "status": "osm_islet", "note": ""},
          "F.Magoodhoo": {"lat": "3.0777", "lon": "72.9610", "status": "osm_islet", "note": ""}}


def write_schedule(tmp_path, body):
    path = tmp_path / "s.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_stop_id_normalises_prefix_and_punctuation():
    assert stop_id("Gdh.Hon'dehdhoo") == "GDH_HONDEHDHOO"
    assert stop_id("F.Nilandhoo") == "F_NILANDHOO"


def test_unknown_atoll_code_rejected():
    with pytest.raises(ValueError):
        stop_id("X.Nowhere")


def test_load_routes_orders_stops_and_sailings(tmp_path):
    path = write_schedule(tmp_path,
        "280,1,1,F.Magoodhoo,,16:00:00\n280,1,2,F.Nilandhoo,,16:30:00\n"
        "280,0,2,F.Magoodhoo,,08:05:00\n280,0,1,F.Nilandhoo,,07:40:00\n")
    sailings = b.load_routes(path)["280"]
    assert [[st.stop_name for st in s] for s in sailings] == [
        ["F.Nilandhoo", "F.Magoodhoo"], ["F.Magoodhoo", "F.Nilandhoo"]]


def test_load_routes_rejects_order_gap(tmp_path):
    path = write_schedule(tmp_path, "1,0,1,F.Nilandhoo,,07:00:00\n1,0,3,F.Magoodhoo,,07:30:00\n")
    with pytest.raises(ValueError, match="not 1..n"):
        b.load_routes(path)


def test_identical_routes_merged_with_alias(tmp_path):
    rows = "".join(f"{r},0,1,F.Nilandhoo,,07:00:00\n{r},0,2,F.Magoodhoo,,07:30:00\n" for r in (206, 205))
    rows += "207,0,1,F.Nilandhoo,,09:00:00\n207,0,2,F.Magoodhoo,,09:30:00\n"
    routes = b.merge_duplicates(b.load_routes(write_schedule(tmp_path, rows)))
    assert [(r.route_id, r.aliases) for r in routes] == [("205", ["206"]), ("207", [])]


def route(*stops):
    return [b.Route("1", [tuple(b.StopTime(n, "", t) for n, t in stops)], [])]


def test_validate_accepts_plausible_sailing():
    errors, warnings = b.validate(route(("F.Nilandhoo", "07:00:00"), ("F.Magoodhoo", "07:30:00")), COORDS)
    assert errors == [] and warnings == []


@pytest.mark.parametrize("stops, message", [
    ((("F.Nilandhoo", "07:30:00"), ("F.Magoodhoo", "07:30:00")), "not increasing"),
    ((("F.Nilandhoo", "23:50:00"), ("F.Magoodhoo", "24:20:00")), "overnight"),
    ((("F.Nilandhoo", "07:00:00"), ("F.Feeali", "07:30:00")), "no coordinates"),
    ((("F.Nilandhoo", "07:00:00"),), "fewer than 2 stops"),
])
def test_validate_errors(stops, message):
    errors, _ = b.validate(route(*stops), COORDS)
    assert any(message in e for e in errors)


def test_validate_warns_on_implausible_speed():
    # ~8.4 km in 2 min = ~250 km/h
    _, warnings = b.validate(route(("F.Nilandhoo", "07:00:00"), ("F.Magoodhoo", "07:02:00")), COORDS)
    assert any("km/h" in w for w in warnings)


@pytest.fixture(scope="module")
def feed(tmp_path_factory):
    """Build the real feed from data/ into a temp dir."""
    routes = b.merge_duplicates(b.load_routes())
    coords = load_stop_coords()
    errors, _ = b.validate(routes, coords)
    assert errors == []
    tables = b.build_tables(routes, coords, "2026-10-24")
    return {name: rows for name, (_, rows) in tables.items()}


def test_real_feed_referential_integrity(feed):
    stop_ids = {s["stop_id"] for s in feed["stops"]}
    trip_ids = {t["trip_id"] for t in feed["trips"]}
    route_ids = {r["route_id"] for r in feed["routes"]}
    assert {st["stop_id"] for st in feed["stop_times"]} == stop_ids
    assert {st["trip_id"] for st in feed["stop_times"]} == trip_ids
    assert {t["route_id"] for t in feed["trips"]} == route_ids
    assert all(r["route_type"] == 4 for r in feed["routes"])
    assert len(feed["translations"]) == len(stop_ids)


def test_real_feed_preserves_every_unique_source_sailing(feed):
    with (DATA / "ferry_schedules.csv").open(encoding="utf-8") as f:
        source = {(r["stop_name"], r["timing"], r["schedule_idx"], r["order"]) for r in csv.DictReader(f)}
    trip_idx = {t["trip_id"]: t["trip_id"].rsplit("_", 1)[1] for t in feed["trips"]}
    names = {s["stop_id"]: s["stop_name"] for s in feed["stops"]}
    built = {(names[st["stop_id"]], st["departure_time"], trip_idx[st["trip_id"]], str(st["stop_sequence"]))
             for st in feed["stop_times"]}
    assert built == source


def test_real_feed_every_stop_has_provenance(feed):
    stops_with_prov = {p["entity_id"] for p in feed["provenance"] if p["entity_type"] == "stop"}
    assert stops_with_prov == {s["stop_id"] for s in feed["stops"]}


def test_web_export_matches_feed():
    from pipeline.export_web import build_network
    net = build_network()
    assert len(net["stops"]) == 77 and len(net["routes"]) == 27
    assert sum(len(r["trips"]) for r in net["routes"]) == 58
    for r in net["routes"]:
        for t in r["trips"]:
            minutes = [m for _, m in t["calls"]]
            assert minutes == sorted(minutes) and len(set(minutes)) == len(minutes)
    assert sum(s["approx"] for s in net["stops"]) == 0  # all approximate stops now use Census points


def test_geojson_export_covers_every_route_and_stop():
    from pipeline.export_web import build_geojson, build_network
    net = build_network()
    routes, stops = build_geojson(net)
    assert len(routes["features"]) == 27 and len(stops["features"]) == 77
    for f in routes["features"]:
        coords = f["geometry"]["coordinates"]
        assert len(coords) == len(f["properties"]["stops"]) >= 2
        assert all(72 < lon < 74 and -1 < lat < 7 for lon, lat in coords)
    assert sum(f["properties"]["departures_per_day"] for f in stops["features"]) == \
        sum(len(t["calls"]) - 1 for r in net["routes"] for t in r["trips"])
