"""Extract the supplied local archives and cache narrowly selected XLSX columns."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time

from .xlsx import rows


SOURCES = {
    "census_households": ("Census2022HouseholdExcelDataset.7z", "household/hh_data.xlsx", "unit__id",
                          ["unit__id", "fcode", "atoll_code", "island_code", "longitude", "latitude", "island_type", "male_atoll", "unit_type", "hh_type", "no_of_ppl"]),
    "census_persons": ("Census2022IndividualExcelDataset.7z", "individual/Indvidual_data.xlsx", "unit__id",
                       ["unit__id", "ind__id", "fcode", "atoll_code", "island_code", "island_type", "age", "usual_residence"]),
    "census_dictionary": ("Census2022HouseholdExcelDataset.7z", "household/HH_ data_dictionary.xlsx", None, None),
    "hies_income": ("HIES_2019_Dataset.7z", "Non-Raised_CombinedIncome_HHLevel.xlsx", "uqhh__id",
                    ["uqhh__id", "atoll_code", "atoll", "maleatoll", "wgt", "totalIncome", "hhsize"]),
    "hies_expenditure": ("HIES_2019_Dataset.7z", "Non-Raised_master_exp.xlsx", "uqhh__id",
                         ["uqhh__id", "wgt", "annexp"]),
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract(archive, member, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with temporary.open("wb") as output:
            subprocess.run(["bsdtar", "-xOf", str(archive), member], stdout=output, check=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root, refresh=False, source_dir=None):
    root = Path(root)
    source_dir = Path(source_dir) if source_dir is not None else root
    cache = root / "data/cache"
    raw = root / "data/raw"
    cache.mkdir(parents=True, exist_ok=True)
    source_hashes = {name: sha256(source_dir / name) for name in sorted({s[0] for s in SOURCES.values()})}
    paths = {}
    for key, (archive_name, member, header, columns) in SOURCES.items():
        start = time.monotonic()
        archive = source_dir / archive_name
        if key.startswith("hies_"):
            inner = raw / "hies/non_raised.7z"
            stamp = inner.with_suffix(".source.json")
            expected = {"archive_sha256": source_hashes[archive_name]}
            if refresh or not inner.exists() or not stamp.exists() or json.loads(stamp.read_text()) != expected:
                extract(archive, "Dataset/HIES2019_EXCEL format/Non-Raised_Dataset.7z", inner)
                stamp.write_text(json.dumps(expected))
            archive = inner
            member = "Non-Raised_Dataset/Non-Raised_Dataset/" + member
        workbook = raw / (key + ".xlsx")
        output = cache / (key + ".csv")
        stamp = cache / (key + ".source.json")
        expected = {"archive_sha256": source_hashes[archive_name], "member": member, "columns": columns, "reader_version": 1}
        valid = not refresh and stamp.exists() and json.loads(stamp.read_text()) == expected
        if key == "census_dictionary":
            if not valid or not workbook.exists():
                extract(archive, member, workbook)
                stamp.write_text(json.dumps(expected))
            paths[key] = workbook
            continue
        if not valid or not output.exists():
            extract(archive, member, workbook)
            temporary = output.with_suffix(".partial")
            count = 0
            try:
                with temporary.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=columns)
                    writer.writeheader()
                    for row in rows(workbook, columns, header_key=header):
                        writer.writerow(row)
                        count += 1
                        if count % 100000 == 0:
                            print(f"{key}: {count:,} rows read", flush=True)
                temporary.replace(output)
                stamp.write_text(json.dumps(expected))
            finally:
                temporary.unlink(missing_ok=True)
            print(f"{key}: cached {count:,} rows in {time.monotonic() - start:.1f}s", flush=True)
        paths[key] = output
    return paths, source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-dir", type=Path, help="Directory containing the three original Census/HIES archives")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    paths, _ = prepare(args.root, args.refresh, args.source_dir)
    print(json.dumps({key: str(path) for key, path in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
