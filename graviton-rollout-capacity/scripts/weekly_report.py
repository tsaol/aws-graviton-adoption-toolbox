#!/usr/bin/env python3
"""Weekly adoption health from hourly CUR usage (and optional classify.py summaries).

Per ISO week:
- Graviton share of vCPU at the peak hour of the week;
- Graviton share of NEW capacity: of the vCPU added at peak since the previous week,
  how much is Graviton (the "did new demand land on Arm?" number);
- ICE nights / zero-ICE nights, from classify.py summaries if given.
Output: JSON, and HTML with --html.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ec2util import is_graviton, vcpus  # noqa: E402
from classify import load_cur, parse_time  # noqa: E402


def weekly(cur_path, summaries=(), vcpu_overrides=None):
    cur = load_cur(cur_path)
    by_hour = defaultdict(lambda: [0.0, 0.0])          # hour -> [graviton vCPU, x86 vCPU]
    for (hour, itype, _az), inst_hours in cur.items():
        v = inst_hours * vcpus(itype, vcpu_overrides)
        by_hour[hour][0 if is_graviton(itype) else 1] += v
    weeks = defaultdict(list)
    for hour, (g, x) in by_hour.items():
        y, w, _ = parse_time(hour).isocalendar()
        weeks[f"{y}-W{w:02d}"].append((g + x, g, x, hour))
    ice = defaultdict(lambda: {"ice_nights": set(), "nights": set()})
    for path in summaries:
        with open(path, encoding="utf-8") as fh:
            s = json.load(fh)
        for n in s.get("nights", []):
            y, w, _ = dt.date.fromisoformat(n["night"]).isocalendar()
            k = f"{y}-W{w:02d}"
            ice[k]["nights"].add(n["night"])
            if n.get("capacity", 0) > 0:
                ice[k]["ice_nights"].add(n["night"])
    rows, prev = [], None
    for k in sorted(weeks):
        total, g, x, hour = max(weeks[k])
        row = {"week": k, "peak_hour": hour, "peak_vcpu": round(total), "graviton_vcpu": round(g),
               "x86_vcpu": round(x), "graviton_share_at_peak": round(g / total, 4) if total else None,
               "new_capacity_vcpu": None, "graviton_share_of_new_capacity": None}
        if prev:
            dg, dx = g - prev[1], x - prev[2]
            added = max(dg, 0) + max(dx, 0)
            row["new_capacity_vcpu"] = round(dg + dx)
            row["graviton_share_of_new_capacity"] = round(max(dg, 0) / added, 4) if added else None
        if k in ice:
            row["ice_nights"] = len(ice[k]["ice_nights"])
            row["zero_ice_nights"] = len(ice[k]["nights"]) - len(ice[k]["ice_nights"])
        rows.append(row)
        prev = (total, g, x)
    return {"weeks": rows}


def to_html(out):
    head = ["week", "peak hour (UTC)", "peak vCPU", "Graviton share at peak", "new capacity vCPU",
            "Graviton share of new capacity", "ICE nights", "zero-ICE nights"]
    def pct(v):
        return "" if v is None else f"{v * 100:.1f}%"
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in [
            r["week"], r["peak_hour"], r["peak_vcpu"], pct(r["graviton_share_at_peak"]),
            "" if r["new_capacity_vcpu"] is None else r["new_capacity_vcpu"],
            pct(r["graviton_share_of_new_capacity"]), r.get("ice_nights", ""), r.get("zero_ice_nights", "")]) + "</tr>"
        for r in out["weeks"])
    return ("<!doctype html><meta charset='utf-8'><title>Weekly Graviton adoption health</title>"
            "<style>body{font-family:sans-serif;max-width:1000px;margin:24px auto}table{border-collapse:collapse}"
            "td,th{border:1px solid #ccc;padding:4px 8px}th{background:#f3f3f3}</style>"
            "<h1>Weekly Graviton adoption health</h1><table><tr>"
            + "".join(f"<th>{h}</th>" for h in head) + "</tr>" + body + "</table>"
            "<p>Graviton share of new capacity: of the vCPU added at the weekly peak since the previous week, the part on Graviton. "
            "If it stays low while the total grows, new demand is landing on x86.</p>")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cur", help="hourly usage CSV (CUR columns or short names)")
    ap.add_argument("--summary", action="append", default=[], help="classify.py output, can repeat")
    ap.add_argument("--html", help="write an HTML page here")
    a = ap.parse_args(argv)
    out = weekly(a.cur, a.summary)
    if a.html:
        with open(a.html, "w", encoding="utf-8") as fh:
            fh.write(to_html(out))
    sys.stdout.write(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
