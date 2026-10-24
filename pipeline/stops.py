"""Shared stop/atoll helpers for the ferry data pipeline."""

import csv
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SCHEDULES = DATA / "ferry_schedules.csv"
GEO_AUTO = DATA / "stops_geo.csv"        # written by geocode_stops.py
GEO_MANUAL = DATA / "stops_geo_manual.csv"  # hand-reviewed overrides

# Atoll code prefix used in stop names (e.g. "F.Nilandhoo") ->
# (English name, official Dhivehi admin name as used in OpenStreetMap).
ATOLLS = {
    "Lh": ("Lhaviyani", "ފާދިއްޕޮޅު"),
    "N": ("Noonu", "މިލަދުންމަޑުލު ދެކުނުބުރި"),
    "B": ("Baa", "މާޅޮސްމަޑުލު ދެކުނުބުރި"),
    "F": ("Faafu", "ނިލަންދެއަތޮޅު އުތުރުބުރި"),
    "Dh": ("Dhaalu", "ނިލަންދެއަތޮޅު ދެކުނުބުރި"),
    "Th": ("Thaa", "ކޮޅުމަޑުލު"),
    "L": ("Laamu", "ހައްދުންމަތި"),
    "Ga": ("Gaafu Alifu", "ހުވަދުއަތޮޅު އުތުރުބުރި"),
    "Gdh": ("Gaafu Dhaalu", "ހުވަދުއަތޮޅު ދެކުނުބުރި"),
    "Gn": ("Gnaviyani", "ފުވައްމުލައް"),
    "S": ("Seenu", "އައްޑޫ"),
}


def split_stop_name(stop_name: str) -> tuple[str, str]:
    """'F.Nilandhoo' -> ('F', 'Nilandhoo')."""
    code, _, island = stop_name.partition(".")
    if code not in ATOLLS or not island:
        raise ValueError(f"Unrecognised stop name: {stop_name!r}")
    return code, island


def stop_id(stop_name: str) -> str:
    """Stable GTFS stop_id, e.g. "Gdh.Hon'dehdhoo" -> 'GDH_HONDEHDHOO'."""
    code, island = split_stop_name(stop_name)
    return f"{code}_{re.sub(r'[^A-Za-z0-9]', '', island)}".upper()


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_stop_coords(auto: Path = GEO_AUTO, manual: Path = GEO_MANUAL) -> dict[str, dict]:
    """stop_name -> {lat, lon, status, note}; manual rows override geocoded ones."""
    coords = {}
    for row in read_csv(auto):
        if row["status"] != "unresolved":
            note = f"OSM {row['osm_type']}/{row['osm_id']}: {row['osm_display_name']}"
            coords[row["stop_name"]] = {"lat": row["lat"], "lon": row["lon"],
                                        "status": row["status"], "note": note}
    for row in read_csv(manual):
        coords[row["stop_name"]] = {k: row[k] for k in ("lat", "lon", "status", "note")}
    return coords
