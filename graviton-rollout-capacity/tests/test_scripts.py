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
import precheck          # noqa: E402
import weekly_report     # noqa: E402
import ec2util           # noqa: E402
import gzip              # noqa: E402

CASE1 = os.path.join(ROOT, "replay-bench/cases/ice-two-causes/input")
CASE2 = os.path.join(ROOT, "replay-bench/cases/ice-after-release/input")
DATA = os.path.join(HERE, "data")


def summary(case, snapshot=True, cur=False):
    return classify.summarize(
        [os.path.join(case, "events.jsonl.gz")],
        subnet_map=os.path.join(case, "subnet-map.json"),
        az_ids=os.path.join(case, "az-ids.json"),
        snapshot_path=os.path.join(case, "capacity-snapshot.json") if snapshot else None,
        cur_path=os.path.join(case, "usage-hourly.csv") if cur else None)


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
        cls.s = summary(CASE1, cur=True)

    def test_dedupe_two_layers(self):
        self.assertEqual(self.s["records_raw"], 3754)
        self.assertEqual(self.s["duplicates_removed"], 334)              # same eventID
        self.assertEqual(self.s["repeated_request_rows_collapsed"], 2259)  # same requestID
        self.assertEqual(self.s["unique_requests"], 1161)
        self.assertEqual(self.s["instances_by_bucket"]["capacity"], 465)

    def test_cur_alignment(self):
        h = self.s["hourly_with_cur"]
        self.assertTrue(h)
        n = [x for x in self.s["nights"] if x["instanceType"] == "m8g.24xlarge" and x["availabilityZone"] == "eu-west-1a"]
        # base 30 running + 40 launched per night
        self.assertTrue(all(x["peak_running_from_cur"] == 70 for x in n))
        row = [x for x in h if x["hour"] == "2030-03-03T22:00:00Z" and x["instanceType"] == "m8g.24xlarge"
               and x["availabilityZone"] == "eu-west-1a"][0]
        self.assertGreater(row["capacity_errors"], 0)
        self.assertGreater(row["running_instance_hours"], 30)

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


class TestInputFormats(unittest.TestCase):
    """The same records as JSON Lines, a CloudTrail log file ({"Records": [...]}) and lookup-events output."""
    @classmethod
    def setUpClass(cls):
        with gzip.open(os.path.join(CASE1, "events.jsonl.gz"), "rt", encoding="utf-8") as fh:
            cls.recs = [json.loads(l) for l in fh][:300]
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        with open(os.path.join(d, "a.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(r) for r in cls.recs))
        with gzip.open(os.path.join(d, "b.json.gz"), "wt", encoding="utf-8") as fh:
            json.dump({"Records": cls.recs}, fh)
        with open(os.path.join(d, "c.json"), "w", encoding="utf-8") as fh:
            json.dump({"Events": [{"EventId": r["eventID"], "CloudTrailEvent": json.dumps(r)} for r in cls.recs]}, fh)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_same_result_for_all_formats(self):
        d = self.tmp.name
        sub = os.path.join(CASE1, "subnet-map.json")
        res = [classify.summarize([os.path.join(d, f)], subnet_map=sub) for f in ("a.jsonl", "b.json.gz", "c.json")]
        self.assertEqual(res[0]["by_type_az_code"], res[1]["by_type_az_code"])
        self.assertEqual(res[0]["by_type_az_code"], res[2]["by_type_az_code"])
        self.assertEqual(res[0]["unique_requests"], res[2]["unique_requests"])

    def test_directory_input_dedupes_across_files(self):
        out = classify.summarize([self.tmp.name], subnet_map=os.path.join(CASE1, "subnet-map.json"))
        one = classify.summarize([os.path.join(self.tmp.name, "a.jsonl")], subnet_map=os.path.join(CASE1, "subnet-map.json"))
        self.assertEqual(out["unique_requests"], one["unique_requests"])
        self.assertEqual(out["records_raw"], 3 * one["records_raw"])


class TestEc2Util(unittest.TestCase):
    def test_vcpus(self):
        for t, v in [("m8g.24xlarge", 96), ("m8g.16xlarge", 64), ("c8g.large", 2), ("m6g.medium", 1),
                     ("t4g.medium", 2), ("m7a.48xlarge", 192), ("r8g.xlarge", 4)]:
            self.assertEqual(ec2util.vcpus(t), v, t)
        with self.assertRaises(ValueError):
            ec2util.vcpus("m8g.metal-24xl")
        self.assertEqual(ec2util.vcpus("m8g.metal-24xl", {"m8g.metal-24xl": 96}), 96)

    def test_is_graviton(self):
        for t in ("m8g.24xlarge", "c7gn.large", "r8gd.2xlarge", "t4g.small", "x2gd.xlarge", "im4gn.large", "is4gen.xlarge"):
            self.assertTrue(ec2util.is_graviton(t), t)
        for t in ("m7i.24xlarge", "m7a.large", "c6in.xlarge", "r7iz.large", "t3.medium"):
            self.assertFalse(ec2util.is_graviton(t), t)


class TestPrecheck(unittest.TestCase):
    def run_spec(self, name):
        with open(os.path.join(DATA, "precheck", name), encoding="utf-8") as fh:
            return precheck.check(json.load(fh), os.path.join(DATA, "precheck"))

    def test_not_ready(self):
        out = self.run_spec("spec-not-ready.json")
        st = {c["id"]: c["status"] for c in out["checks"]}
        self.assertEqual(st, {"C1": "PASS", "C2": "PASS", "C3": "FAIL", "C4": "FAIL", "C5": "FAIL", "C6": "FAIL", "C7": "FAIL"})
        self.assertEqual(out["verdict"], "not ready")
        c4 = [c for c in out["checks"] if c["id"] == "C4"][0]["detail"]
        self.assertIn("eu-west-1b: 50/100", c4)          # the cancelled reservation is not counted

    def test_ready(self):
        out = self.run_spec("spec-ready.json")
        self.assertEqual(out["counts"], {"PASS": 7, "FAIL": 0, "NOT RUN": 0})
        self.assertEqual(out["verdict"], "ready")

    def test_minimal_reports_not_run(self):
        out = self.run_spec("spec-minimal.json")
        st = {c["id"]: c["status"] for c in out["checks"]}
        self.assertEqual(st["C2"], "FAIL")              # x86 fallback for an Arm primary
        self.assertEqual(sum(1 for v in st.values() if v == "NOT RUN"), 6)   # every other check lacks input
        self.assertEqual(out["verdict"], "not ready")


class TestWeekly(unittest.TestCase):
    def test_new_capacity_share(self):
        out = weekly_report.weekly(os.path.join(DATA, "weekly-usage.csv"))
        w = out["weeks"]
        self.assertEqual([x["week"] for x in w], ["2030-W10", "2030-W11", "2030-W12", "2030-W13"])
        self.assertAlmostEqual(w[0]["graviton_share_at_peak"], 0.1, places=3)
        self.assertEqual(w[1]["graviton_share_of_new_capacity"], 1.0)    # all growth on Graviton
        self.assertLess(w[3]["graviton_share_of_new_capacity"], 0.05)    # growth back on x86
        self.assertIsNone(w[0]["new_capacity_vcpu"])

    def test_ice_nights_from_summary(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(summary(CASE1, cur=True), fh)
            out = weekly_report.weekly(os.path.join(CASE1, "usage-hourly.csv"), [p])
            w = {r["week"]: r for r in out["weeks"]}
            # nights 2030-03-03 (Sunday, ISO week 9), 03-04 and 03-05 (week 10); all have capacity errors
            self.assertEqual((w["2030-W09"]["ice_nights"], w["2030-W09"]["zero_ice_nights"]), (1, 0))
            self.assertEqual((w["2030-W10"]["ice_nights"], w["2030-W10"]["zero_ice_nights"]), (2, 0))
            self.assertAlmostEqual(w["2030-W10"]["graviton_share_at_peak"], 1.0)


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
                            os.path.join(CASE1, "events.jsonl.gz"),
                            "--subnet-map", os.path.join(CASE1, "subnet-map.json"),
                            "--capacity-snapshot", os.path.join(CASE1, "capacity-snapshot.json"),
                            "--cur", os.path.join(CASE1, "usage-hourly.csv"),
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
