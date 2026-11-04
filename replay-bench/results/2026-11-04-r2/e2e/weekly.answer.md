# Graviton adoption health: weeks 2030-W10 to W13

Data: `input/usage-hourly.csv`, which has 4 ISO weeks (2030-03-04 to 2030-03-31), two instance types (m7i.24xlarge = x86, m8g.24xlarge = Graviton, both with 96 vCPU) and two AZs (eu-west-1a, eu-west-1b).
Numbers come from `weekly_report.py` in the graviton-rollout-capacity skill. The HTML version is at `~/tmp/gw/weekly.html`.

## Verdict

The migration went well in week 11. Since then it has **stopped**. All new capacity in weeks 12 and 13 went mostly or fully to **x86**. Graviton use has not changed at all for two weeks, so the Graviton share is going down every week.
The likely cause is that the "default to Arm for new capacity" step is missing. New demand (from scaling or new services) still starts on m7i.

## Weekly numbers (at the weekly peak hour, 21:00 UTC Sunday)

| Week | Peak vCPU | Graviton vCPU | x86 vCPU | Graviton share at peak | New vCPU vs last week | Graviton share of new capacity |
|---|---|---|---|---|---|---|
| 2030-W10 | 96,000 | 9,600 | 86,400 | 10.0% | – | – |
| 2030-W11 | 99,840 | 42,240 | 57,600 | **42.3%** | +3,840 | 100% |
| 2030-W12 | 106,560 | 43,200 | 63,360 | 40.5% | +6,720 | **14.3%** |
| 2030-W13 | 116,160 | 43,200 | 72,960 | 37.2% | +9,600 | **0.0%** |

The same data as instances per AZ at peak. Both AZs show exactly the same numbers:

| Week | m7i (x86) per AZ | m8g (Graviton) per AZ |
|---|---|---|
| W10 | 450 | 50 |
| W11 | 300 | 220 |
| W12 | 330 (+30) | 225 (+5) |
| W13 | 380 (+50) | 225 (+0) |

## What is wrong

1. **New demand is landing on x86.** The fleet grew by 16,320 vCPU from W11 to W13 (+170 instances at peak). Only 960 vCPU (10 instances) of this was Graviton. In W13 all of the growth (+100 m7i) was x86.
   - Meaning: workloads that already moved stayed on Arm, but new or scaled-out capacity still uses the m7i launch templates, ASGs or node pools.
   - Action (customer platform team): make m8g (or a list of Graviton types) the default for new launch templates, ASG mixed-instance policies and Karpenter NodePools. Find which service added about 50 m7i per AZ in W13 and about 30 per AZ in W12, and check whether it can run on Arm.
2. **Graviton is flat at exactly 225 per AZ in both AZs for two weeks.** A flat line at the same round number in both AZs often means a fixed limit: an ASG max size, a NodePool limit, or the end of a migration wave. It *could* also mean m8g launches are failing (ICE or quota), and that the extra demand spilled over to m7i as a fallback. With usage data alone I cannot tell these apart.
   - Action (customer): check the ASG/NodePool max for the m8g groups. Pull RunInstances events from CloudTrail for 2030-03-18 to 2030-03-31 and run `classify.py` with this CSV as `--cur`. That shows if there were capacity errors (`InsufficientInstanceCapacity`) or quota errors on m8g.
3. **Small note on the W11 "100%" number.** The script counts only growth. In W11 x86 went down by 300 instances and Graviton went up by 340, so that number shows migration, not only new demand. It is still a good result.

## What the data cannot show

- **Launch failures / ICE: NOT RUN.** No CloudTrail RunInstances data was given, so `classify.py` was not run. The report has no ICE / zero-ICE nights.
- **Pre-rollout checks (`precheck.py`): NOT RUN.** No quotas, offerings, reservations or capacity snapshot were given.
- The file has only **two hours per day** (10:00 and 21:00 UTC), not all 24. Peaks at other hours would be missed. The pattern is very regular, so I think the risk is low, but a full hourly export would be better.
- It shows usage, not *why*: it cannot say which service or team added the new m7i capacity. CUR resource tags or `line_item_resource_id` would answer that.
- The file uses short column names (`hour, instance_type, availability_zone, instance_hours`), not the standard CUR names. The script accepted them. The dates are in 2030, so please check the export is the period you wanted.

## Next steps

| Who | What |
|---|---|
| Platform team | Find the source of the +80 m7i per AZ in W12–W13 (tags / resource IDs). Change its defaults to Graviton if possible. |
| Platform team | Check the max size on the m8g ASGs / NodePools (now 225 per AZ). |
| Platform team | Export CloudTrail RunInstances for 2030-03-18 to 2030-03-31 and send it for `classify.py`, to rule out m8g capacity or quota errors. |
| Rollout owner | Make "Graviton share of new capacity" a weekly target (for example ≥ 80%). Re-run `weekly_report.py` next week. |

No reason to pause the rollout. The problem is that new capacity is not going to Graviton, not that Graviton is failing.
