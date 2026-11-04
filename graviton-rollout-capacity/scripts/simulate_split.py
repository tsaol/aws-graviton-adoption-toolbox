#!/usr/bin/env python3
"""Simulate delivering a capacity reservation in batches.

Input JSON:
{
  "per_az": {"eu-west-1a": {"peak_gap": 140}, "eu-west-1b": {"peak_gap": 90}},
  "batches": [{"name": "first", "per_az": 50, "ready": "2030-01-05"},
              {"name": "second", "per_az": 150, "ready": "2030-01-12"}]
}
Output: the gap left per AZ after each batch, and the first batch that closes it.
Pure arithmetic, no AWS calls. Python 3.9+, standard library only.
"""
import argparse
import json
import sys


def simulate(spec):
    out = {"steps": [], "closed_by": {}}
    covered = {az: 0 for az in spec["per_az"]}
    for b in spec["batches"]:
        step = {"batch": b["name"], "ready": b.get("ready", ""), "per_az": {}}
        for az, v in spec["per_az"].items():
            covered[az] += int(b["per_az"] if not isinstance(b["per_az"], dict) else b["per_az"].get(az, 0))
            gap = max(0, int(v["peak_gap"]) - covered[az])
            step["per_az"][az] = {"reserved_so_far": covered[az], "gap_left": gap}
            if gap == 0 and az not in out["closed_by"]:
                out["closed_by"][az] = b["name"]
        out["steps"].append(step)
    for az in spec["per_az"]:
        out["closed_by"].setdefault(az, None)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", help="JSON file, see module docstring")
    a = ap.parse_args(argv)
    with open(a.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    sys.stdout.write(json.dumps(simulate(spec), indent=1) + "\n")


if __name__ == "__main__":
    main()
