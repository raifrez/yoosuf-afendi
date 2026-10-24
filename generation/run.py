"""Regenerate population from this repository's raw archives and rebuild shared data."""

import argparse
from pathlib import Path

from population.generate import main as generate
from population.publish import publish_run


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=root.parent / "data")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--islands", nargs="+")
    parser.add_argument("--geography", type=Path)
    parser.add_argument("--name-catalog", type=Path)
    parser.add_argument("--no-publish", action="store_true", help="Generate an immutable run without updating shared tables")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    options = ["--root", str(root), "--source-dir", str(data / "raw/archives"), "--seed", str(args.seed)]
    if args.islands:
        options.extend(["--islands", *args.islands])
    for option, value in (("--geography", args.geography), ("--name-catalog", args.name_catalog)):
        if value:
            options.extend([option, str(value.resolve())])
    output = generate(options)
    if not args.no_publish:
        print(f"Updated shared database: {publish_run(output, data)}")


if __name__ == "__main__":
    main()
