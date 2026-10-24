"""Write the baseline simulation for the demo region as static JSON (the same payloads as the API).

  uv run python -m simulator.export [--atolls F Dh GA GDh]

  data/export/simulation/meta.json      region, categories, parameters + labels, sources
  data/export/simulation/baseline.json  scores per island x category and atoll x category
  data/export/simulation/demo.json      the demo resident and scenario, with its gains and losses
"""

import argparse
import json
import sys

from pipeline.export_web import EXPORT
from simulator.demo_story import demo_story
from simulator.model import DEMO_ATOLLS, Model

OUT = EXPORT / "simulation"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--atolls", nargs="+", default=list(DEMO_ATOLLS))
    args = ap.parse_args(argv)
    model = Model(args.atolls)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in (("meta", model.meta()), ("baseline", model.scores_payload(model.baseline)),
                          ("demo", demo_story(model))):
        (OUT / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
    print(f"Wrote {OUT}/{{meta,baseline,demo}}.json for atolls {' '.join(args.atolls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
