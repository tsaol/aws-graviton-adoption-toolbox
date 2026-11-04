"""Unit tests for the rollout & capacity scripts. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ROOT = os.path.dirname(SKILL)
sys.path.insert(0, os.path.join(SKILL, "scripts"))
import classify          # noqa: E402
import simulate_split    # noqa: E402

CASE1 = os.path.join(ROOT, "replay-bench/cases/ice-two-causes/input")
CASE2 = os.path.join(ROOT, "replay-bench/cases/ice-after-release/input")


def summary(case, snapshot=True):
    return classify.summarize(
        [os.path.join(case, "events.jsonl")],
        subnet_map=os.path.join(case, "subnet-map.json"),
        az_ids=os.path.join(case, "az-ids.json"),
        snapshot_path=os.path.join(case, "capacity-snapshot.json") if snapshot else None)


def rows(s, **kw):
    return [r for r in s["by_type_az_code"] if all(r[k] == v for k, v in kw.items())]


class TestBuckets(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(classify.bucket_of("Server.InsufficientInstanceCapacity"), "capacity")
        self.assertEqual(classify.bucket_of("InsufficientInstanceCapacity"), "capacity")
        self.assertEqual(classify.bucket_of("VcpuLimitExceeded"), "quota")
        self.assertEqual(classify.bucket_of("InsufficientFreeAddressesInSubnet"), "other")
        self.assertEqual(classify.bucket_of(None), "success")

    def test_night_window_crosses_midnight(self):
        t = classify.parse_time("2030-03-04T02:10:00Z")
        self.assertEqual(classify.night_of(t, 0, 18, 8), "2030-03-03")
        self.assertIsNone(classify.night_of(classify.parse_time("2030-03-04T12:00:00Z"), 0, 18, 8))


class TestTwoCauses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = summary(CASE1)

    def test_dedupe(self):
        self.assertEqual(self.s["records_after_dedupe"], 1161)
        self.assertEqual(self.s["duplicates_removed"], 128)

    def test_primary_short_in_both_azs(self):
        self.assertEqual(rows(self.s, instanceType="m8g.24xlarge", availabilityZone="eu-west-1a", bucket="capacity")[0]["instances"], 210)
        self.assertEqual(rows(self.s, instanceType="m8g.24xlarge", availabilityZone="eu-west-1b", bucket="capacity")[0]["instances"], 165)

    def test_fallback_fails_only_in_az_a_at_01_to_03(self):
        r = [h for h in self.s["failure_hours"] if h["instanceType"] == "m8g.16xlarge" and h["bucket"] == "capacity"]
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["availabilityZone"], "eu-west-1a")
        self.assertEqual(set(r[0]["by_local_hour"]), {"1", "2"})
        self.assertEqual(sum(r[0]["by_local_hour"].values()), 90)

    def test_snapshot_flags(self):
        f = self.s["capacity_vs_snapshot_flags"]
        self.assertEqual(len(f), 6)
        self.assertTrue(all(x["instanceType"] == "m8g.16xlarge" and x["availabilityZone"] == "eu-west-1a" for x in f))

    def test_quota_and_other_are_separate(self):
        self.assertEqual(self.s["instances_by_bucket"]["quota"], 36)
        self.assertEqual(rows(self.s, bucket="quota")[0]["instanceType"], "c8g.4xlarge")
        self.assertEqual(self.s["instances_by_bucket"]["other"], 15)

    def test_az_from_subnet_and_az_id(self):
        r = rows(self.s, instanceType="m8g.24xlarge", availabilityZone="eu-west-1a", bucket="success")[0]
        self.assertEqual(r["azId"], "euw1-az1")
        self.assertNotIn("unknown", {x["availabilityZone"] for x in self.s["by_type_az_code"]})

    def test_nights(self):
        n = [x for x in self.s["nights"] if x["instanceType"] == "m8g.24xlarge" and x["availabilityZone"] == "eu-west-1a"]
        self.assertEqual([x["night"] for x in n], ["2030-03-03", "2030-03-04", "2030-03-05"])
        self.assertTrue(all(x["capacity"] == 70 and x["launched"] == 40 for x in n))


class TestAfterRelease(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = summary(CASE2, snapshot=False)

    def test_reservation_events(self):
        ev = [(r["event"], r["availabilityZone"]) for r in self.s["reservation_events"]]
        self.assertEqual(ev.count(("CancelCapacityReservation", "eu-west-1a")), 1)
        self.assertEqual(ev.count(("CancelCapacityReservation", "eu-west-1b")), 1)

    def test_ice_only_after_cancel(self):
        n = [x for x in self.s["nights"] if x["instanceType"] == "m8g.24xlarge"]
        before = [x for x in n if x["night"] < "2030-04-03"]
        after = [x for x in n if x["night"] >= "2030-04-03"]
        self.assertTrue(before and after)
        self.assertTrue(all(x["capacity"] == 0 for x in before))
        self.assertTrue(all(x["capacity"] > 0 for x in after))


class TestSimulate(unittest.TestCase):
    def test_batches(self):
        out = simulate_split.simulate({
            "per_az": {"a": {"peak_gap": 140}, "b": {"peak_gap": 40}},
            "batches": [{"name": "first", "per_az": 50}, {"name": "second", "per_az": 150}]})
        self.assertEqual(out["closed_by"], {"a": "second", "b": "first"})
        self.assertEqual(out["steps"][0]["per_az"]["a"]["gap_left"], 90)


class TestCli(unittest.TestCase):
    def test_cli_and_page(self):
        with tempfile.TemporaryDirectory() as d:
            sj = os.path.join(d, "s.json")
            subprocess.run([sys.executable, os.path.join(SKILL, "scripts/classify.py"),
                            os.path.join(CASE1, "events.jsonl"),
                            "--subnet-map", os.path.join(CASE1, "subnet-map.json"),
                            "--capacity-snapshot", os.path.join(CASE1, "capacity-snapshot.json"),
                            "-o", sj], check=True)
            page = os.path.join(d, "p.html")
            subprocess.run([sys.executable, os.path.join(SKILL, "scripts/daily_page.py"), sj, "-o", page], check=True)
            with open(page, encoding="utf-8") as fh:
                html = fh.read()
            self.assertIn("Capacity errors while the snapshot shows free capacity", html)
            with open(sj, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["instances_by_bucket"]["capacity"], 465)


if __name__ == "__main__":
    unittest.main()
