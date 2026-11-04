#!/usr/bin/env python3
"""Generate the synthetic CloudTrail evidence used by unit tests and replay cases.

Everything here is made up: account 111122223333, region eu-west-1, year 2030.
Deterministic (fixed seed), so re-running gives byte-identical files.
"""
import datetime as dt
import gzip
import json
import os
import random
import uuid
from collections import defaultdict

ACCOUNT = "111122223333"
REGION = "eu-west-1"
SUBNETS = {"subnet-0aaa1111": "eu-west-1a", "subnet-0bbb2222": "eu-west-1b"}
AZ_IDS = {"eu-west-1a": "euw1-az1", "eu-west-1b": "euw1-az2"}
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ice_msg(itype, az):
    return (f"We currently do not have sufficient {itype} capacity in the Availability Zone you "
            f"requested ({az}). Our system will be working on provisioning additional capacity. "
            f"You can currently get {itype} capacity by not specifying an Availability Zone in "
            f"your request or choosing a different Availability Zone.")


class Gen:
    def __init__(self, seed):
        self.rnd = random.Random(seed)
        self.records = []

    def uid(self):
        return str(uuid.UUID(int=self.rnd.getrandbits(128)))

    def run(self, t, itype, az, ok, code=None, msg=None, asg="mall-web-asg"):
        subnet = [s for s, a in SUBNETS.items() if a == az][0]
        r = {
            "eventVersion": "1.10", "eventTime": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eventSource": "ec2.amazonaws.com", "eventName": "RunInstances",
            "awsRegion": REGION, "sourceIPAddress": "autoscaling.amazonaws.com",
            "userAgent": "autoscaling.amazonaws.com",
            "userIdentity": {"type": "AssumedRole", "accountId": ACCOUNT,
                             "invokedBy": "autoscaling.amazonaws.com",
                             "arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/AWSServiceRoleForAutoScaling/AutoScaling"},
            "requestParameters": {"instanceType": itype, "minCount": 1, "maxCount": 1,
                                  "networkInterfaceSet": {"items": [{"subnetId": subnet}]},
                                  "tagSpecificationSet": {"items": [{"resourceType": "instance", "tags": [
                                      {"key": "aws:autoscaling:groupName", "value": asg}]}]}},
            "requestID": self.uid(), "eventID": self.uid(), "eventType": "AwsApiCall",
            "recipientAccountId": ACCOUNT,
        }
        if ok:
            r["responseElements"] = {"instancesSet": {"items": [
                {"instanceId": "i-" + self.uid().replace("-", "")[:17], "instanceType": itype,
                 "placement": {"availabilityZone": az}}]}}
        else:
            r["errorCode"] = code
            r["errorMessage"] = msg or ""
            r["responseElements"] = None
        self.records.append(r)

    def reservation(self, t, name, itype, az, count, cr_id):
        self.records.append({
            "eventVersion": "1.10", "eventTime": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "eventSource": "ec2.amazonaws.com", "eventName": name, "awsRegion": REGION,
            "userIdentity": {"type": "AssumedRole", "accountId": ACCOUNT,
                             "arn": f"arn:aws:sts::{ACCOUNT}:assumed-role/platform-admin/ops"},
            "requestParameters": {"capacityReservationId": cr_id, "instanceType": itype,
                                  "availabilityZone": az, "instanceCount": count},
            "responseElements": {"return": True}, "requestID": self.uid(), "eventID": self.uid(),
            "eventType": "AwsApiCall", "recipientAccountId": ACCOUNT})

    def spread(self, day, start_h, end_h, n):
        """n timestamps spread over [start_h, end_h) local=UTC, end may pass midnight."""
        span = (end_h - start_h) % 24 or 24
        base = dt.datetime(day.year, day.month, day.day, start_h, tzinfo=dt.timezone.utc)
        return sorted(base + dt.timedelta(seconds=self.rnd.randint(0, span * 3600 - 1)) for _ in range(n))

    def dump(self, path, dup_rate=0.1, max_extra_rows=4):
        recs = list(self.records)
        # rows for the same request (same requestID, new eventID): exports that write one row
        # per instance or per log line. Mean 3 rows per request, close to the ~70% reduction
        # seen in real exports.
        extra = []
        for r in recs:
            if r["eventName"] == "RunInstances":
                for _ in range(self.rnd.randint(0, max_extra_rows)):
                    c = dict(r)
                    c["eventID"] = self.uid()
                    extra.append(c)
        recs += extra
        dups = [r for r in recs if self.rnd.random() < dup_rate]   # same eventID: org trail + account trail
        recs += dups
        recs.sort(key=lambda r: (r["eventTime"], r["eventID"]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            for r in recs:
                gz.write((json.dumps(r, sort_keys=True) + "\n").encode("utf-8"))
        return {"requests": len(self.records), "extra_rows_same_request": len(extra), "duplicate_records": len(dups),
                "total_rows": len(recs)}

    def cur(self, path, start, end, base):
        """Hourly running instance-hours per (type, AZ) from successful launches.
        Instances launched in a night run until 06:00 UTC next morning, then scale in."""
        launched = defaultdict(int)
        for r in self.records:
            if r["eventName"] == "RunInstances" and not r.get("errorCode"):
                t = dt.datetime.strptime(r["eventTime"], "%Y-%m-%dT%H:%M:%SZ")
                az = r["responseElements"]["instancesSet"]["items"][0]["placement"]["availabilityZone"]
                launched[(t.replace(minute=0, second=0), r["requestParameters"]["instanceType"], az)] += 1
        keys = sorted({(k[1], k[2]) for k in launched} | set(base))
        rows = []
        h = start
        running = {k: 0 for k in keys}
        while h < end:
            for k in keys:
                if h.hour == 6:
                    running[k] = 0
                running[k] += launched.get((h, k[0], k[1]), 0)
                rows.append((h.strftime("%Y-%m-%d %H:%M:%S"), k[0], k[1], base.get(k, 0) + running[k]))
            h += dt.timedelta(hours=1)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("line_item_usage_start_date,product_instance_type,line_item_availability_zone,line_item_usage_amount,line_item_usage_type\n")
            for hr, t, az, n in rows:
                fh.write(f"{hr},{t},{az},{n},EU-BoxUsage:{t}\n")
        return len(rows)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True)
        fh.write("\n")


def case_two_causes(out_dir):
    """Primary size short in both AZs; fallback fails in one AZ while the pool shows free capacity;
    plus one real quota problem and one subnet problem."""
    g = Gen(7)
    days = [dt.date(2030, 3, 3), dt.date(2030, 3, 4), dt.date(2030, 3, 5)]
    snapshot = []
    for d in days:
        nxt = d + dt.timedelta(days=1)
        for t in g.spread(d, 19, 5, 40): g.run(t, "m8g.24xlarge", "eu-west-1a", True)
        for t in g.spread(d, 20, 2, 70): g.run(t, "m8g.24xlarge", "eu-west-1a", False,
                                              "Server.InsufficientInstanceCapacity", ice_msg("m8g.24xlarge", "eu-west-1a"))
        for t in g.spread(d, 19, 5, 45): g.run(t, "m8g.24xlarge", "eu-west-1b", True)
        for t in g.spread(d, 20, 2, 55): g.run(t, "m8g.24xlarge", "eu-west-1b", False,
                                              "Server.InsufficientInstanceCapacity", ice_msg("m8g.24xlarge", "eu-west-1b"))
        for t in g.spread(d, 19, 5, 60): g.run(t, "m8g.16xlarge", "eu-west-1a", True)
        for t in g.spread(nxt, 1, 3, 30): g.run(t, "m8g.16xlarge", "eu-west-1a", False,
                                               "Server.InsufficientInstanceCapacity", ice_msg("m8g.16xlarge", "eu-west-1a"))
        for t in g.spread(d, 19, 5, 70): g.run(t, "m8g.16xlarge", "eu-west-1b", True)
        for t in g.spread(d, 22, 23, 12): g.run(t, "c8g.4xlarge", "eu-west-1b", False, "VcpuLimitExceeded",
                                              "You have requested more vCPU capacity than your current vCPU limit of 1024 allows for the instance bucket that the specified instance type belongs to.",
                                              asg="batch-etl-asg")
        for t in g.spread(d, 23, 0, 5): g.run(t, "m8g.16xlarge", "eu-west-1b", False, "InsufficientFreeAddressesInSubnet",
                                             "There are not enough free addresses in subnet 'subnet-0bbb2222' to satisfy the requested number of instances.")
        for h in (1, 2):
            snapshot.append({"time": f"{nxt.isoformat()}T0{h}:30:00Z", "instanceType": "m8g.16xlarge",
                             "availabilityZone": "eu-west-1a", "free": 240})
        for az in ("eu-west-1a", "eu-west-1b"):
            snapshot.append({"time": f"{d.isoformat()}T22:00:00Z", "instanceType": "m8g.24xlarge",
                             "availabilityZone": az, "free": 0})
    stats = g.dump(os.path.join(out_dir, "events.jsonl.gz"))
    stats["cur_rows"] = g.cur(os.path.join(out_dir, "usage-hourly.csv"), dt.datetime(2030, 3, 3, 12), dt.datetime(2030, 3, 6, 12),
                              {("m8g.24xlarge", "eu-west-1a"): 30, ("m8g.24xlarge", "eu-west-1b"): 30,
                               ("m8g.16xlarge", "eu-west-1a"): 20, ("m8g.16xlarge", "eu-west-1b"): 20})
    write_json(os.path.join(out_dir, "subnet-map.json"), SUBNETS)
    write_json(os.path.join(out_dir, "az-ids.json"), AZ_IDS)
    write_json(os.path.join(out_dir, "capacity-snapshot.json"), snapshot)
    return stats


def case_after_release(out_dir):
    """No capacity errors while reservations are active; errors return after they are cancelled."""
    g = Gen(11)
    days = [dt.date(2030, 4, 1) + dt.timedelta(days=i) for i in range(6)]
    t0 = dt.datetime(2030, 3, 31, 9, 0, tzinfo=dt.timezone.utc)
    g.reservation(t0, "CreateCapacityReservation", "m8g.24xlarge", "eu-west-1a", 100, "cr-0a1a1a1a1a1a1a1a1")
    g.reservation(t0 + dt.timedelta(minutes=2), "CreateCapacityReservation", "m8g.24xlarge", "eu-west-1b", 100, "cr-0b2b2b2b2b2b2b2b2")
    cancel = dt.datetime(2030, 4, 3, 10, 0, tzinfo=dt.timezone.utc)
    g.reservation(cancel, "CancelCapacityReservation", "m8g.24xlarge", "eu-west-1a", 100, "cr-0a1a1a1a1a1a1a1a1")
    g.reservation(cancel + dt.timedelta(minutes=1), "CancelCapacityReservation", "m8g.24xlarge", "eu-west-1b", 100, "cr-0b2b2b2b2b2b2b2b2")
    for d in days:
        released = d >= dt.date(2030, 4, 3)
        for az in ("eu-west-1a", "eu-west-1b"):
            ok24 = 60 if released else 110
            for t in g.spread(d, 19, 5, ok24): g.run(t, "m8g.24xlarge", az, True)
            if released:
                for t in g.spread(d, 20, 2, 45 if az == "eu-west-1a" else 35):
                    g.run(t, "m8g.24xlarge", az, False, "Server.InsufficientInstanceCapacity", ice_msg("m8g.24xlarge", az))
                for t in g.spread(d, 20, 3, 40): g.run(t, "m8g.16xlarge", az, True)
            else:
                for t in g.spread(d, 20, 3, 5): g.run(t, "m8g.16xlarge", az, True)
    stats = g.dump(os.path.join(out_dir, "events.jsonl.gz"))
    write_json(os.path.join(out_dir, "subnet-map.json"), SUBNETS)
    write_json(os.path.join(out_dir, "az-ids.json"), AZ_IDS)
    return stats


def weekly_usage(path):
    """Four weeks of usage at the daily peak (21:00 UTC) plus one quiet hour.
    Weeks 1-2: new demand lands on Graviton. Weeks 3-4: Graviton stays flat, new demand lands on x86."""
    plan = {  # week index -> (m7i.24xlarge, m8g.24xlarge) instances at peak, per AZ
        0: (450, 50), 1: (300, 220), 2: (330, 225), 3: (380, 225)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("hour,instance_type,availability_zone,instance_hours\n")
        for day in range(28):
            d = dt.date(2030, 3, 4) + dt.timedelta(days=day)
            x86, arm = plan[day // 7]
            for az in ("eu-west-1a", "eu-west-1b"):
                fh.write(f"{d}T21:00:00Z,m7i.24xlarge,{az},{x86}\n")
                fh.write(f"{d}T21:00:00Z,m8g.24xlarge,{az},{arm}\n")
                fh.write(f"{d}T10:00:00Z,m7i.24xlarge,{az},{x86 // 3}\n")
                fh.write(f"{d}T10:00:00Z,m8g.24xlarge,{az},{arm // 3}\n")


def precheck_inputs(d):
    os.makedirs(d, exist_ok=True)
    write_json(os.path.join(d, "offerings.json"), {"InstanceTypeOfferings": [
        {"InstanceType": t, "LocationType": "availability-zone", "Location": az}
        for t in ("m8g.24xlarge", "m8g.16xlarge") for az in ("eu-west-1a", "eu-west-1b")]})
    write_json(os.path.join(d, "reservations.json"), {"CapacityReservations": [
        {"CapacityReservationId": "cr-0a1a1a1a1a1a1a1a1", "InstanceType": "m8g.24xlarge", "AvailabilityZone": "eu-west-1a",
         "TotalInstanceCount": 50, "State": "active"},
        {"CapacityReservationId": "cr-0b2b2b2b2b2b2b2b2", "InstanceType": "m8g.24xlarge", "AvailabilityZone": "eu-west-1b",
         "TotalInstanceCount": 50, "State": "active"},
        {"CapacityReservationId": "cr-0c3c3c3c3c3c3c3c3", "InstanceType": "m8g.24xlarge", "AvailabilityZone": "eu-west-1b",
         "TotalInstanceCount": 40, "State": "cancelled"}]})
    write_json(os.path.join(d, "capacity-snapshot.json"), [
        {"time": "2030-03-28T21:00:00Z", "instanceType": "m8g.24xlarge", "availabilityZone": "eu-west-1a", "free": 60},
        {"time": "2030-03-28T21:00:00Z", "instanceType": "m8g.24xlarge", "availabilityZone": "eu-west-1b", "free": 150}])
    base = {"today": "2030-04-01", "rollout_date": "2030-05-20", "primary": "m8g.24xlarge", "fallbacks": ["m8g.16xlarge"],
            "peak_instances_per_az": {"eu-west-1a": 120, "eu-west-1b": 100},
            "vcpu_quota": 24000, "vcpu_in_use_at_peak": 9000,
            "offerings_file": "offerings.json", "reservations_file": "reservations.json",
            "snapshot_file": "capacity-snapshot.json",
            "release_plan": [{"capacityReservationId": "cr-0a1a1a1a1a1a1a1a1", "release_on": "2030-06-01", "rollback_agreed": False}]}
    write_json(os.path.join(d, "spec-not-ready.json"), base)
    ok = dict(base, rollout_date="2030-06-10", vcpu_quota=40000, fallbacks=["m8g.16xlarge"],
              release_plan=[{"capacityReservationId": "cr-0a1a1a1a1a1a1a1a1", "release_on": "2030-06-30", "rollback_agreed": True}],
              peak_instances_per_az={"eu-west-1a": 50, "eu-west-1b": 50})
    write_json(os.path.join(d, "spec-ready.json"), ok)
    minimal = {"primary": "m8g.24xlarge", "fallbacks": ["m7i.24xlarge"], "peak_instances_per_az": {"eu-west-1a": 10}}
    write_json(os.path.join(d, "spec-minimal.json"), minimal)


if __name__ == "__main__":
    targets = {
        "two-causes": [os.path.join(ROOT, "replay-bench/cases/ice-two-causes/input")],
        "after-release": [os.path.join(ROOT, "replay-bench/cases/ice-after-release/input")],
    }
    weekly_usage(os.path.join(ROOT, "graviton-rollout-capacity/tests/data/weekly-usage.csv"))
    precheck_inputs(os.path.join(ROOT, "graviton-rollout-capacity/tests/data/precheck"))
    for name, dirs in targets.items():
        fn = case_two_causes if name == "two-causes" else case_after_release
        for d in dirs:
            print(name, d, fn(d))
