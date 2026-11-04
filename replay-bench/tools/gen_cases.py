#!/usr/bin/env python3
"""Generate the synthetic CloudTrail evidence used by unit tests and replay cases.

Everything here is made up: account 111122223333, region eu-west-1, year 2030.
Deterministic (fixed seed), so re-running gives byte-identical files.
"""
import datetime as dt
import json
import os
import random
import uuid

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

    def dump(self, path, dup_rate=0.1):
        recs = list(self.records)
        dups = [r for r in recs if self.rnd.random() < dup_rate]   # same eventID: org trail + account trail
        recs += dups
        recs.sort(key=lambda r: (r["eventTime"], r["eventID"]))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
        return len(self.records), len(dups)


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
    n, dups = g.dump(os.path.join(out_dir, "events.jsonl"))
    write_json(os.path.join(out_dir, "subnet-map.json"), SUBNETS)
    write_json(os.path.join(out_dir, "az-ids.json"), AZ_IDS)
    write_json(os.path.join(out_dir, "capacity-snapshot.json"), snapshot)
    return n, dups


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
    n, dups = g.dump(os.path.join(out_dir, "events.jsonl"))
    write_json(os.path.join(out_dir, "subnet-map.json"), SUBNETS)
    write_json(os.path.join(out_dir, "az-ids.json"), AZ_IDS)
    return n, dups


if __name__ == "__main__":
    targets = {
        "two-causes": [os.path.join(ROOT, "replay-bench/cases/ice-two-causes/input")],
        "after-release": [os.path.join(ROOT, "replay-bench/cases/ice-after-release/input")],
    }
    for name, dirs in targets.items():
        fn = case_two_causes if name == "two-causes" else case_after_release
        for d in dirs:
            print(name, d, fn(d))
