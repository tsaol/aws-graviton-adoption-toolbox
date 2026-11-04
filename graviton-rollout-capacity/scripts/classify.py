#!/usr/bin/env python3
"""Classify EC2 launch failures from CloudTrail evidence.

Reads CloudTrail records (CloudTrail log files with {"Records": [...]},
JSON Lines, or `aws cloudtrail lookup-events` output; plain or .gz) and removes duplicates in
two layers:
  1. the same record seen twice (same eventID), e.g. when two trails are merged;
  2. several rows for the same API request (same requestID), e.g. exports or
     dashboards that write one row per instance or per log line.
Then it groups launch results by instance type x AZ x error code x hour, and can
line them up with hourly usage from the Cost and Usage Report (CUR).

Read-only: works on files, never calls AWS APIs that change anything.
Python 3.9+, standard library only.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
from collections import Counter, defaultdict

CAPACITY_CODES = {
    "Server.InsufficientInstanceCapacity", "InsufficientInstanceCapacity",
    "InsufficientCapacity", "Server.InsufficientHostCapacity",
    "InsufficientHostCapacity", "InsufficientReservedInstanceCapacity",
}
QUOTA_CODES = {
    "VcpuLimitExceeded", "InstanceLimitExceeded", "Client.VcpuLimitExceeded",
    "MaxSpotInstanceCountExceeded", "Client.InstanceLimitExceeded",
}
LAUNCH_EVENTS = {"RunInstances"}
RESERVATION_EVENTS = {
    "CreateCapacityReservation", "CancelCapacityReservation",
    "ModifyCapacityReservation", "CreateCapacityReservationFleet",
    "CancelCapacityReservationFleets",
}
AZ_IN_MESSAGE = re.compile(r"\(([a-z]{2}-[a-z]+-\d[a-z])\)")


def bucket_of(code):
    if not code:
        return "success"
    if code in CAPACITY_CODES:
        return "capacity"
    if code in QUOTA_CODES:
        return "quota"
    return "other"


def iter_records(paths):
    """Yield CloudTrail records from files or directories."""
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names)
                          if n.endswith((".json", ".jsonl", ".json.gz", ".jsonl.gz"))]
        else:
            files.append(p)
    for f in files:
        opener = gzip.open if f.endswith(".gz") else open
        with opener(f, "rt", encoding="utf-8") as fh:
            text = fh.read().strip()
        if not text:
            continue
        docs = []
        try:
            docs = [json.loads(text)]
        except json.JSONDecodeError:
            docs = [json.loads(line) for line in text.splitlines() if line.strip()]
        for d in docs:
            if isinstance(d, dict) and "Records" in d:
                yield from d["Records"]
            elif isinstance(d, dict) and "Events" in d:      # lookup-events output
                for e in d["Events"]:
                    yield json.loads(e["CloudTrailEvent"])
            elif isinstance(d, dict) and "eventName" in d:
                yield d


def record_key(r):
    return r.get("eventID") or (r.get("requestID"), r.get("eventTime"), r.get("eventName"))


def request_key(r):
    return r.get("requestID") or record_key(r)


def find_az(r, subnet_az):
    rp = r.get("requestParameters") or {}
    az = (rp.get("placement") or {}).get("availabilityZone")
    if az:
        return az
    subnet = rp.get("subnetId")
    for ni in ((rp.get("networkInterfaceSet") or {}).get("items") or []):
        subnet = subnet or ni.get("subnetId")
    if subnet and subnet in subnet_az:
        return subnet_az[subnet]
    m = AZ_IN_MESSAGE.search(r.get("errorMessage") or "")
    if m:
        return m.group(1)
    items = (((r.get("responseElements") or {}).get("instancesSet") or {}).get("items") or [])
    for it in items:
        az = (it.get("placement") or {}).get("availabilityZone")
        if az:
            return az
    return "unknown"


def instance_count(r):
    items = (((r.get("responseElements") or {}).get("instancesSet") or {}).get("items") or [])
    if items:
        return len(items)
    rp = r.get("requestParameters") or {}
    try:
        return int(rp.get("minCount") or 1)
    except (TypeError, ValueError):
        return 1


def parse_time(s):
    return dt.datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")


def night_of(t, tz_offset, start_hour, end_hour):
    """Return the date of the evening that starts the night window, or None."""
    local = t + dt.timedelta(hours=tz_offset)
    h = local.hour
    if start_hour > end_hour:          # window crosses midnight, e.g. 18 -> 08
        if h >= start_hour:
            return local.date().isoformat()
        if h < end_hour:
            return (local.date() - dt.timedelta(days=1)).isoformat()
        return None
    return local.date().isoformat() if start_hour <= h < end_hour else None


def load_snapshot(path):
    """Capacity snapshot from the account team: [{time, instanceType, availabilityZone, free}]"""
    if not path:
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_cur(path):
    """Hourly usage from a CUR export (CSV). Accepts CUR column names
    (line_item_usage_start_date, product_instance_type, line_item_availability_zone,
    line_item_usage_amount) or short ones (hour, instance_type, availability_zone,
    instance_hours). Returns {(hour_iso, type, az): instance_hours}."""
    import csv
    if not path:
        return {}
    alias = {"hour": ["line_item_usage_start_date", "hour"],
             "type": ["product_instance_type", "instance_type"],
             "az": ["line_item_availability_zone", "availability_zone"],
             "amount": ["line_item_usage_amount", "instance_hours"]}
    out = defaultdict(float)
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        cols = {k: next((c for c in v if c in rd.fieldnames), None) for k, v in alias.items()}
        missing = [k for k, c in cols.items() if c is None]
        if missing:
            raise SystemExit(f"CUR file {path}: missing columns for {missing}")
        for row in rd:
            if not row[cols["type"]]:
                continue
            h = parse_time(row[cols["hour"]].replace(" ", "T")[:19] + "Z").strftime("%Y-%m-%dT%H:00:00Z")
            out[(h, row[cols["type"]], row[cols["az"]])] += float(row[cols["amount"]] or 0)
    return dict(out)


def summarize(paths, subnet_map=None, az_ids=None, tz_offset=0, night_start=18,
              night_end=8, snapshot_path=None, cur_path=None):
    subnet_az = {}
    if subnet_map:
        with open(subnet_map, encoding="utf-8") as fh:
            subnet_az = json.load(fh)
    az_id = {}
    if az_ids:
        with open(az_ids, encoding="utf-8") as fh:
            az_id = json.load(fh)

    raw = 0
    seen = set()
    seen_req = set()
    collapsed = 0
    launches = []
    reservations = []
    for r in iter_records(paths):
        raw += 1
        k = record_key(r)
        if k in seen:
            continue
        seen.add(k)
        rk = request_key(r)
        if rk in seen_req:
            collapsed += 1
            continue
        seen_req.add(rk)
        name = r.get("eventName")
        if name in LAUNCH_EVENTS:
            launches.append(r)
        elif name in RESERVATION_EVENTS:
            reservations.append(r)

    rows = Counter()
    hours = defaultdict(Counter)
    nights = defaultdict(lambda: Counter())
    fail_times = defaultdict(list)
    codes_seen = Counter()
    per_hour = defaultdict(Counter)
    for r in launches:
        code = r.get("errorCode")
        b = bucket_of(code)
        itype = (r.get("requestParameters") or {}).get("instanceType", "unknown")
        az = find_az(r, subnet_az)
        t = parse_time(r["eventTime"])
        n = instance_count(r)
        key = (itype, az, code or "", b)
        rows[key] += n
        per_hour[(t.strftime("%Y-%m-%dT%H:00:00Z"), itype, az)][b] += n
        night = night_of(t, tz_offset, night_start, night_end)
        if night:
            nights[(night, itype, az)][b] += n
        if b != "success":
            local_h = (t + dt.timedelta(hours=tz_offset)).hour
            hours[(itype, az, b)][local_h] += n
            fail_times[(itype, az, b)].append(t)
            codes_seen[code] += 1

    # cross-check capacity errors against the account team's snapshot
    flags = []
    for s in load_snapshot(snapshot_path):
        st = parse_time(s["time"])
        if s.get("free", 0) <= 0:
            continue
        key = (s["instanceType"], s["availabilityZone"], "capacity")
        near = [t for t in fail_times.get(key, []) if abs((t - st).total_seconds()) <= 1800]
        if near:
            flags.append({
                "time": s["time"], "instanceType": s["instanceType"],
                "availabilityZone": s["availabilityZone"], "free_in_snapshot": s["free"],
                "capacity_errors_within_30min": len(near),
                "meaning": "capacity errors while the snapshot shows free capacity: "
                           "not explained by pool depth; hand this evidence to the account team",
            })

    table = [
        {"instanceType": k[0], "availabilityZone": k[1], "azId": az_id.get(k[1], ""),
         "errorCode": k[2], "bucket": k[3], "instances": v}
        for k, v in sorted(rows.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    night_rows = []
    for (night, itype, az), c in sorted(nights.items()):
        night_rows.append({"night": night, "instanceType": itype, "availabilityZone": az,
                           "launched": c.get("success", 0), "capacity": c.get("capacity", 0),
                           "quota": c.get("quota", 0), "other": c.get("other", 0)})
    hour_rows = [
        {"instanceType": k[0], "availabilityZone": k[1], "bucket": k[2],
         "by_local_hour": {str(h): n for h, n in sorted(v.items())}}
        for k, v in sorted(hours.items())
    ]
    res_rows = []
    for r in sorted(reservations, key=lambda x: x["eventTime"]):
        rp = r.get("requestParameters") or {}
        res_rows.append({"time": r["eventTime"], "event": r["eventName"],
                         "error": r.get("errorCode") or "",
                         "instanceType": rp.get("instanceType", ""),
                         "availabilityZone": rp.get("availabilityZone", ""),
                         "instanceCount": rp.get("instanceCount", ""),
                         "capacityReservationId": rp.get("capacityReservationId", "")})
    cur = load_cur(cur_path)
    hourly = []
    if cur:
        keys = sorted(set(cur) | set(per_hour))
        for k in keys:
            c = per_hour.get(k, Counter())
            hourly.append({"hour": k[0], "instanceType": k[1], "availabilityZone": k[2],
                           "running_instance_hours": round(cur.get(k, 0.0), 2),
                           "launched": c.get("success", 0), "capacity_errors": c.get("capacity", 0),
                           "quota_errors": c.get("quota", 0), "other_errors": c.get("other", 0)})
    peak = {}
    for h in hourly:
        night = night_of(parse_time(h["hour"]), tz_offset, night_start, night_end)
        if not night:
            continue
        key = (night, h["instanceType"], h["availabilityZone"])
        peak[key] = max(peak.get(key, 0), h["running_instance_hours"])
    for n in night_rows:
        if cur:
            n["peak_running_from_cur"] = peak.get((n["night"], n["instanceType"], n["availabilityZone"]), 0)
    totals = Counter()
    for k, v in rows.items():
        totals[k[3]] += v
    return {
        "records_raw": raw,
        "records_after_dedupe": len(seen),
        "duplicates_removed": raw - len(seen),
        "repeated_request_rows_collapsed": collapsed,
        "unique_requests": len(seen) - collapsed,
        "launch_api_calls": len(launches),
        "instances_by_bucket": dict(totals),
        "error_codes_seen": dict(codes_seen),
        "by_type_az_code": table,
        "nights": night_rows,
        "failure_hours": hour_rows,
        "capacity_vs_snapshot_flags": flags,
        "reservation_events": res_rows,
        "hourly_with_cur": hourly,
        "window": {
            "first": min((r["eventTime"] for r in launches), default=None),
            "last": max((r["eventTime"] for r in launches), default=None),
            "tz_offset_hours": tz_offset, "night": f"{night_start:02d}:00-{night_end:02d}:00",
        },
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="CloudTrail files or directories")
    ap.add_argument("--subnet-map", help="JSON {subnetId: availabilityZone}")
    ap.add_argument("--az-ids", help="JSON {availabilityZone: azId}")
    ap.add_argument("--capacity-snapshot", help="JSON list from the account team (optional)")
    ap.add_argument("--cur", help="hourly usage CSV from the Cost and Usage Report (optional)")
    ap.add_argument("--tz-offset", type=float, default=0, help="hours to add to UTC for local time")
    ap.add_argument("--night-start", type=int, default=18)
    ap.add_argument("--night-end", type=int, default=8)
    ap.add_argument("-o", "--output", help="write JSON here (default: stdout)")
    a = ap.parse_args(argv)
    out = summarize(a.paths, a.subnet_map, a.az_ids, a.tz_offset, a.night_start,
                    a.night_end, a.capacity_snapshot, a.cur)
    text = json.dumps(out, indent=1, ensure_ascii=False)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
