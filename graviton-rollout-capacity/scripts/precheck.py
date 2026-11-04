#!/usr/bin/env python3
"""Pre-rollout capacity check. Gives PASS / FAIL / NOT RUN for each check.

Inputs are files you collect with read-only calls (see SKILL.md). Every check
whose input is missing is reported as NOT RUN. Never calls AWS itself.

Spec (JSON):
{
  "rollout_date": "2030-05-20", "today": "2030-04-01",
  "primary": "m8g.24xlarge", "fallbacks": ["m8g.16xlarge"],
  "peak_instances_per_az": {"eu-west-1a": 120, "eu-west-1b": 100},
  "lead_time_weeks_needed": 8,               # optional, default 8 when peak total >= 100
  "vcpu_quota": 24000,                       # optional: Running On-Demand Standard vCPU quota
  "vcpu_in_use_at_peak": 9000,               # optional: other workloads sharing the quota
  "offerings_file": "offerings.json",        # optional: aws ec2 describe-instance-type-offerings --location-type availability-zone
  "reservations_file": "reservations.json",  # optional: aws ec2 describe-capacity-reservations
  "snapshot_file": "capacity-snapshot.json", # optional: account team snapshot at peak hours
  "release_plan": [{"capacityReservationId": "cr-...", "release_on": "2030-06-01", "rollback_agreed": false}]
}
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ec2util import is_graviton, vcpus  # noqa: E402


def _load(spec_dir, name):
    if not name:
        return None
    p = name if os.path.isabs(name) else os.path.join(spec_dir, name)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def check(spec, spec_dir="."):
    res = []

    def add(cid, title, status, detail):
        res.append({"id": cid, "check": title, "status": status, "detail": detail})

    azs = spec["peak_instances_per_az"]
    types = [spec["primary"]] + list(spec.get("fallbacks", []))
    total_peak = sum(azs.values())

    # C1 offerings
    off = _load(spec_dir, spec.get("offerings_file"))
    if off is None:
        add("C1", "Target and fallback types are offered in every AZ", "NOT RUN", "no offerings_file")
    else:
        have = {(o["InstanceType"], o["Location"]) for o in off.get("InstanceTypeOfferings", [])}
        miss = [f"{t} in {az}" for t in types for az in azs if (t, az) not in have]
        add("C1", "Target and fallback types are offered in every AZ", "FAIL" if miss else "PASS",
            "missing: " + ", ".join(miss) if miss else f"{len(types)} types x {len(azs)} AZs offered")

    # C2 fallback defined, same architecture
    fb = spec.get("fallbacks", [])
    if not fb:
        add("C2", "A fallback type of the same architecture exists", "FAIL", "no fallback types")
    else:
        bad = [t for t in fb if is_graviton(t) != is_graviton(spec["primary"])]
        add("C2", "A fallback type of the same architecture exists", "FAIL" if bad else "PASS",
            ("different architecture: " + ", ".join(bad)) if bad else ", ".join(fb))

    # C3 vCPU quota headroom
    if "vcpu_quota" not in spec:
        add("C3", "On-Demand vCPU quota covers the peak", "NOT RUN", "no vcpu_quota")
    else:
        need = total_peak * vcpus(spec["primary"]) + int(spec.get("vcpu_in_use_at_peak", 0))
        ok = need <= int(spec["vcpu_quota"])
        add("C3", "On-Demand vCPU quota covers the peak", "PASS" if ok else "FAIL",
            f"need {need} vCPU at peak (incl. {spec.get('vcpu_in_use_at_peak', 0)} already in use) vs quota {spec['vcpu_quota']}")

    # C4 reservations vs peak per AZ
    rsv = _load(spec_dir, spec.get("reservations_file"))
    if rsv is None:
        add("C4", "Capacity reservations per AZ for the primary type", "NOT RUN", "no reservations_file")
    else:
        have = {}
        for r in rsv.get("CapacityReservations", []):
            if r.get("State") == "active" and r.get("InstanceType") == spec["primary"]:
                have[r["AvailabilityZone"]] = have.get(r["AvailabilityZone"], 0) + int(r.get("TotalInstanceCount", 0))
        parts = [f"{az}: {have.get(az, 0)}/{n}" for az, n in azs.items()]
        short = [az for az, n in azs.items() if have.get(az, 0) < n]
        add("C4", "Capacity reservations per AZ for the primary type", "FAIL" if short else "PASS",
            "reserved/peak " + "; ".join(parts) + (" (the rest relies on the shared pool)" if short else ""))

    # C5 account team snapshot at peak
    snap = _load(spec_dir, spec.get("snapshot_file"))
    if snap is None:
        add("C5", "Account team snapshot shows enough free capacity at peak", "NOT RUN", "no snapshot_file; ask the account team (TAM)")
    else:
        worst = {}
        for s in snap:
            if s["instanceType"] == spec["primary"] and s["availabilityZone"] in azs:
                worst[s["availabilityZone"]] = min(worst.get(s["availabilityZone"], 10**9), int(s["free"]))
        low = [f"{az}: free {worst.get(az, 'n/a')} < peak {n}" for az, n in azs.items() if worst.get(az, -1) < n]
        add("C5", "Account team snapshot shows enough free capacity at peak", "FAIL" if low else "PASS",
            "; ".join(low) if low else "enough free capacity in every AZ")

    # C6 lead time
    need_weeks = int(spec.get("lead_time_weeks_needed", 8 if total_peak >= 100 else 0))
    if "rollout_date" not in spec:
        add("C6", "Enough lead time to arrange capacity", "NOT RUN", "no rollout_date")
    else:
        today = dt.date.fromisoformat(spec.get("today") or dt.date.today().isoformat())
        weeks = (dt.date.fromisoformat(spec["rollout_date"]) - today).days / 7
        add("C6", "Enough lead time to arrange capacity", "PASS" if weeks >= need_weeks else "FAIL",
            f"{weeks:.1f} weeks until rollout; {need_weeks} needed for {total_peak} instances at peak")

    # C7 release plan
    plan = spec.get("release_plan")
    if plan is None:
        add("C7", "Rollback agreed before any reservation is released", "NOT RUN", "no release_plan")
    else:
        bad = [p["capacityReservationId"] for p in plan if not p.get("rollback_agreed")]
        add("C7", "Rollback agreed before any reservation is released", "FAIL" if bad else "PASS",
            ("no rollback agreed for " + ", ".join(bad)) if bad else f"{len(plan)} releases covered")

    counts = {k: sum(1 for r in res if r["status"] == k) for k in ("PASS", "FAIL", "NOT RUN")}
    return {"checks": res, "counts": counts,
            "verdict": "not ready" if counts["FAIL"] else ("incomplete" if counts["NOT RUN"] else "ready")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec")
    a = ap.parse_args(argv)
    with open(a.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    out = check(spec, os.path.dirname(os.path.abspath(a.spec)))
    sys.stdout.write(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
