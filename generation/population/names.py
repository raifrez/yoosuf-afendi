"""Deterministic fictional display names, independent of input order and filtering."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Optional, Union


DEFAULT_CATALOG = Path(__file__).with_name("data") / "name_components.json"


class NameGenerator:
    """Use IDs for identity: duplicate display names are deliberately allowed."""

    def __init__(self, seed: int = 42, catalog_path: Optional[Union[str, Path]] = None):
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        self.seed = seed
        path = Path(catalog_path) if catalog_path is not None else DEFAULT_CATALOG
        raw = path.read_bytes()
        catalog = json.loads(raw)
        if not isinstance(catalog, dict):
            raise ValueError("name catalog must be an object")
        version = catalog.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("name catalog requires a nonempty version")
        self.catalog_version = version
        self.catalog_sha256 = hashlib.sha256(raw).hexdigest()
        self._components = []
        for key in ("given_names", "second_components"):
            values = catalog.get(key)
            if not isinstance(values, list) or not values:
                raise ValueError(f"{key} must be a nonempty list of names")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{key} must contain nonempty strings")
            self._components.append(tuple(value.strip() for value in values))

    def display_name(self, person_id: str) -> str:
        if not isinstance(person_id, str) or not person_id.strip():
            raise ValueError("person_id must be a nonempty string")
        payload = json.dumps(
            [self.catalog_version, self.seed, person_id],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        first_index = int.from_bytes(digest[:16], "big") % len(self._components[0])
        second_index = int.from_bytes(digest[16:], "big") % len(self._components[1])
        return f"{self._components[0][first_index]} {self._components[1][second_index]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("person_ids", nargs="+")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    generator = NameGenerator(args.seed, args.catalog)
    print(json.dumps([
        {
            "person_id": person_id,
            "display_name": generator.display_name(person_id),
            "name_is_synthetic": True,
        }
        for person_id in args.person_ids
    ], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
