# Night-time launch failures in eu-west-1: diagnosis and recommendation

## 1. Verdict

**Don't pause the Graviton rollout. Keep it going and fix the four causes below one by one.** Most failures are `InsufficientInstanceCapacity` for **m8g.24xlarge** at the evening peak (20:00–01:59), in both AZs. The account team's snapshot shows 0 free m8g.24xlarge at 22:00 in both AZs, so this pool is short at peak. The fallback mostly works: CUR shows the web tier grows from 100 to about 315 running instances every night. Two failure types are not caused by Graviton capacity at all: a vCPU quota on `batch-etl-asg` and a full subnet. One pattern can't be explained by pool depth: m8g.16xlarge capacity errors in eu-west-1a at 01:00–02:59 while the snapshot shows 240 free. That one goes to the TAM.

Pausing would not fix any of these causes. Rolling back to x86 would only help with the m8g.24xlarge shortage. It would make sense only if the web tier misses its desired capacity during peak even after the extra fallbacks in action A1 are in place and no reservation can arrive in time. See section 5.

## 2. Evidence base (from `classify.py`, not counted by hand)

| | Count |
|---|---|
| Raw CloudTrail rows | 3,754 |
| Duplicate records removed (same eventID) | 334 |
| Repeated rows for the same request collapsed (same requestID, same instance ID) | 2,259 |
| **Unique RunInstances requests** | **1,161** (all minCount = maxCount = 1) |
| Launched | 645 |
| Capacity errors (`Server.InsufficientInstanceCapacity`) | 465 |
| Quota errors (`VcpuLimitExceeded`) | 36 |
| Other (`InsufficientFreeAddressesInSubnet`) | 15 |

Window: 2030-03-03 19:06 UTC to 2030-03-06 04:58 UTC, three nights. Account 111122223333, eu-west-1. eu-west-1 is on UTC in March, so the hours below are both UTC and local time.

Note: the raw export shows 1,517 ICE rows. After removing duplicates there are **465** ICE requests. Please quote 465, not 1,517.

## 3. Causes

The same pattern repeats on all three nights. Totals are across the three nights.

| # | Type | AZ (AZ ID) | Hours (UTC) | Instances failed | Error | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|---|
| 1 | m8g.24xlarge (primary, `mall-web-asg`) | eu-west-1a (euw1-az1) | 20:00–01:59 | **210** (70/night) | InsufficientInstanceCapacity | The m8g.24xlarge pool is short at peak. The snapshot shows **0 free** at 22:00 on all three nights. | A1–A4 below | Customer platform team + AWS account team |
| 1 | m8g.24xlarge (primary, `mall-web-asg`) | eu-west-1b (euw1-az2) | 20:00–01:59 | **165** (55/night) | InsufficientInstanceCapacity | Same as above: short in both AZs, **0 free** at 22:00 | A1–A4 below | Customer platform team + AWS account team |
| 2 | m8g.16xlarge (fallback, `mall-web-asg`) | eu-west-1a (euw1-az1) | 01:00–02:59 | **90** (30/night) | InsufficientInstanceCapacity | **Not explained by pool depth.** The snapshot shows **240 free** at 01:30 and 02:30 on every night, and the script flagged all 6 snapshot points. The same type in eu-west-1b had no capacity errors. | B1–B2 below. Do **not** answer this by switching types or asking for a quota increase. | AWS account team / TAM (investigate); customer keeps the fallbacks in place meanwhile |
| 3 | c8g.4xlarge (`batch-etl-asg`, **not the web tier**) | eu-west-1b (euw1-az2) | 22:00 | **36** (12/night) | VcpuLimitExceeded ("current vCPU limit of 1024") | A real On-Demand vCPU quota. CUR shows 0 c8g.4xlarge running, so this batch job never starts. | C1 below | Customer (Service Quotas) |
| 4 | m8g.16xlarge (`mall-web-asg`) | eu-west-1b (euw1-az2), subnet-0bbb2222 | 23:00 | **15** (5/night) | InsufficientFreeAddressesInSubnet | Configuration: the subnet has no free IP addresses left | D1 below | Customer platform/network team |

Evidence for cause 2, which goes to the TAM (from `capacity_vs_snapshot_flags`):

| Snapshot time (UTC) | Type | AZ | Free in snapshot | Capacity errors within ±30 min |
|---|---|---|---|---|
| 2030-03-04 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 16 |
| 2030-03-04 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 14 |
| 2030-03-05 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 13 |
| 2030-03-05 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 17 |
| 2030-03-06 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 13 |
| 2030-03-06 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 17 |

Also include this: the m8g.24xlarge errors in eu-west-1a stop at 02:00 at the same moment the m8g.16xlarge errors there start. CUR shows about 59–76 m8g.16xlarge running in 1a at those hours. In 1b, more of the same type (82–90) run with no errors.

## 4. Actions and owners

**Web tier capacity (cause 1)**
- **A1. Customer platform team:** widen the ASG's mixed-instances policy to more Graviton types, so that one pool running short doesn't block scale-out. Candidates: m7g.24xlarge, m7g.16xlarge, m8g.12xlarge, and r8g/c8g sizes if memory and CPU ratios allow. Use instance weights by vCPU and the `price-capacity-optimized` (or `capacity-optimized`) allocation strategy. Keep m8g.16xlarge as a fallback.
- **A2. Customer platform team:** add a third AZ (for example eu-west-1c) to the ASG. Only two subnets appear in the evidence.
- **A3. Customer platform team:** start the evening scale-out earlier using scheduled scaling or a warm pool. Launches at 19:00 succeeded on every night, and errors start at 20:00.
- **A4. Customer + AWS account team:** reserve the peak gap in m8g.24xlarge with On-Demand Capacity Reservations per AZ, delivered in batches. Rough size from the evidence: about 70 instances/night in 1a and 55 in 1b were refused. Confirm the real gap against the ASG's desired capacity first (see section 5). Plan the batches with `simulate_split.py` (NOT RUN, no gap or batch spec yet).

**Unexplained fallback errors (cause 2)**
- **B1. AWS account team / TAM:** investigate account-level or placement constraints for m8g.16xlarge in euw1-az1 at 01:00–02:59 UTC, using the table above. Ask whether the snapshot's "free" figure actually reflects capacity this account can get. Avoid statements like "it's just capacity" until the TAM has looked.
- **B2. Customer platform team:** until the TAM answers, keep the fallback chain from A1 in place so the ASG can move to other types or to 1b.

**Batch ETL quota (cause 3)**
- **C1. Customer (whoever owns `batch-etl-asg`), via Service Quotas:** check quota L-1216C47A ("Running On-Demand Standard instances") in eu-west-1 and request an increase that covers the batch job's peak. Ask the TAM to check one inconsistency: the error says the limit is **1024 vCPU**, but CUR shows the web tier alone at **24,800 vCPU** of M-family On-Demand at peak, which is in the same Standard bucket. Confirm which limit actually applies before sizing the request.

**Subnet IPs (cause 4)**
- **D1. Customer network team:** add IP space for subnet-0bbb2222 or add a second subnet in eu-west-1b to the ASG. Also check for IPs held by unused ENIs.

## 5. What the data cannot show, and what to ask for

- **The ASG's desired capacity.** CloudTrail shows failed attempts, and CUR shows peak usage of about 315 web instances (1a: 70×24xl + 80×16xl, 1b: 75×24xl + 90×16xl). Neither shows whether the ASG actually reached its target, or how long it ran short. Ask the customer for ASG activity history and the `GroupDesiredCapacity` / `GroupInServiceInstances` CloudWatch metrics. This decides whether there is a real shortfall for users, and whether pausing ever needs to be considered.
- **Reservation history.** The export contains only `RunInstances`. A `CancelCapacityReservation` just before the rollout would not appear in it. Ask for CloudTrail `*CapacityReservation*` events and `describe-capacity-reservations` output.
- **The x86 baseline.** CUR contains only m8g.16xlarge and m8g.24xlarge, so the fleet is already 100% Graviton (from `weekly_report.py`: 17,920 → 24,800 peak vCPU, Graviton share of new capacity = 1.0). "Pause" probably means rolling back to x86. Whether x86 capacity would be any better at these hours is unknown.
- **Snapshot coverage.** There is no snapshot for m8g.16xlarge in 1b, and no snapshot outside 22:00 (24xl) or 01:30/02:30 (16xl, 1a). Ask the account team for hourly snapshots from 19:00 to 03:00 for all candidate types in A1, by AZ ID.
- **Timestamps.** The events and CUR are dated March 2030, but today is 2026-11-04. Please confirm with the customer that the export is the right data and that the clocks or export tool aren't misconfigured.
- **Checks not run:**
  - `precheck.py`: NOT RUN. Offerings, reservations and quota files weren't provided.
  - `simulate_split.py`: NOT RUN. There's no batch spec yet.
  - Only these were run: `classify.py`, `daily_page.py` and `weekly_report.py`.

## 6. Next 24 hours

| Who | What |
|---|---|
| Customer platform team | Before tonight's 20:00 peak: add the extra Graviton fallback types and, if possible, a third AZ to `mall-web-asg` (A1, A2). Schedule the scale-out to start around 19:00 (A3). Pull ASG desired vs in-service metrics for the last three nights. |
| Customer network team | Free up or add IP space for subnet-0bbb2222 before 23:00 (D1). |
| `batch-etl-asg` owner | Check quota L-1216C47A and file the increase (C1). |
| AWS account team / TAM | Investigate cause 2 using the evidence table. Explain the 1024-vCPU limit message. Share hourly snapshots for 19:00–03:00. Start sizing m8g.24xlarge ODCR batches per AZ (A4, B1). |
| Both | Review tomorrow morning with that night's CloudTrail and CUR (re-run `classify.py`). Consider pausing only if the ASG still misses its desired capacity at peak after A1–A3 are in place and no reservation can arrive in time. |

Supporting files (generated, not in ./input): `/tmp/work-ice/summary.json`, `/tmp/work-ice/rollout-report.html`, `/tmp/work-ice/weekly.html`.
