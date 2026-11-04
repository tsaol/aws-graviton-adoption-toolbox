# Graviton rollout: night-time launch failures (eu-west-1)

All numbers come from `classify.py` (run on `input/events.jsonl`, saved in `work/summary.json`). The window is 2030-03-03 19:06 to 2030-03-06 04:58 UTC. Hours are in UTC, which is the same as Irish local time in March. The export merged two trails, so it had duplicate records. **128 duplicates were removed by eventID**, leaving 1,161 RunInstances calls with minCount=1 each. No requestID showed up under more than one eventID, so the dedupe is clean.

## 1. Verdict

**Keep rolling out. Don't pause.** The failures have four separate causes. Each cause is limited to particular instance types, AZs and hours, and none of them is a problem with Graviton itself.
- The main cause is that the primary size, **m8g.24xlarge**, runs out of capacity at peak (20:00–01:59) in both AZs. The account team's snapshot also shows 0 free for that size.
- The fallback, **m8g.16xlarge**, launched 180 instances in eu-west-1a and 210 in eu-west-1b. It failed in only one AZ, and only between 01:00 and 02:59, while the snapshot showed 240 free. That case needs the TAM to investigate.
- The other two causes are a vCPU quota limit on a different ASG (batch-etl) and a full subnet. The customer can fix both.

Outcome across all 1,161 calls: 645 launched, 465 capacity errors, 36 quota errors, 15 other errors.

## 2. Causes

| # | Cause | Type / ASG | AZ (AZ ID) | Hours (UTC) | Instances failed (launched) | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|---|
| 1 | `Server.InsufficientInstanceCapacity`, both AZs, peak hours | m8g.24xlarge / mall-web-asg | eu-west-1a (euw1-az1): 210 failed, 120 launched. eu-west-1b (euw1-az2): 165 failed, 135 launched | 20:00–01:59 every night (70 failed in 1a and 55 in 1b per night, all 3 nights) | see AZ column | The 24xlarge pool is short at peak. The snapshot shows **0 free** in both AZs at 22:00 every night, so the failures match the pool depth. | Make sure the ASG uses a mixed-instances policy with fallbacks of the same generation and architecture: m8g.16xlarge, then other m8g sizes or r8g/c8g sizes where they fit, with capacity weighted by vCPU. Use the `capacity-optimized` or `prioritized` allocation strategy so that a 24xlarge ICE falls through to another size right away. For the peak floor, ask for an On-Demand Capacity Reservation for m8g.24xlarge in both AZs for 20:00–02:00, delivered in batches. | Customer platform team (ASG config). Customer and AWS account team (ODCR). |
| 2 | `Server.InsufficientInstanceCapacity` **while the snapshot shows free capacity** | m8g.16xlarge (the fallback) / mall-web-asg | eu-west-1a (euw1-az1) only. eu-west-1b launched 210 with no capacity errors. | 01:00–02:59 only (42 in hour 01, 48 in hour 02). 30 per night, all 3 nights. | 90 failed (180 launched) | The script flagged 6 cases: 01:30 and 02:30 on 03-04, 03-05 and 03-06, each with **240 free** in the snapshot and 13–17 capacity errors within 30 min. Pool depth does not explain these failures. Something account-level or placement-related needs checking. | Send the evidence below to the TAM. Meanwhile, keep the fallback in place and let the ASG put 16xlarge in eu-west-1b, which has had no capacity errors. Don't swap instance types because of this case alone. | AWS account team / TAM (investigate). Customer (keep the fallback). |
| 3 | `VcpuLimitExceeded` ("vCPU limit of 1024 … for the instance bucket") | c8g.4xlarge / **batch-etl-asg** (not the web tier) | eu-west-1b (euw1-az2) | 22:00 (12 per night, 3 nights) | 36 failed (0 launched) | A real On-Demand vCPU quota limit. c8g and m8g fall in the same "Standard" On-Demand bucket, so the web tier and the batch tier compete for this quota as the rollout grows. | Request an increase in Service Quotas: *Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances*, L-1216C47A, eu-west-1. Size it for the web peak plus the batch peak. Note: this does **not** apply to causes 1 and 2. A quota increase does not fix ICE. | Customer platform team |
| 4 | `InsufficientFreeAddressesInSubnet` | m8g.16xlarge / mall-web-asg | eu-west-1b, subnet-0bbb2222 | 23:00 (5 per night, 3 nights) | 15 failed | Configuration problem. The subnet runs out of IPs at peak. This gets worse as more launches move to 1b. | Add subnets (or a secondary CIDR) in eu-west-1b to the ASG, and check IP use from ENIs and prefix delegation. Do this **before** moving more of the fallback to 1b. | Customer platform team |

No `CancelCapacityReservation` or other reservation events appear in the data (`reservation_events` is empty). A released reservation is therefore not a cause here.

### Evidence package for the TAM (cause 2)

- Account 111122223333, region eu-west-1, AZ eu-west-1a = **euw1-az1**, instance type m8g.16xlarge, ASG mall-web-asg, all calls made through autoscaling.amazonaws.com.
- Error: `Server.InsufficientInstanceCapacity`, "We currently do not have sufficient m8g.16xlarge capacity in the Availability Zone you requested".
- Snapshot free = 240 at each of these times, with capacity errors within ±30 min:
  - 2030-03-04 01:30Z: 16 errors. 02:30Z: 14 errors.
  - 2030-03-05 01:30Z: 13 errors. 02:30Z: 17 errors.
  - 2030-03-06 01:30Z: 13 errors. 02:30Z: 17 errors.
- The failures are limited to hours 01 and 02 UTC, 30 per night, and repeat exactly each night. In the same hours, eu-west-1b launched m8g.16xlarge with no capacity errors.
- Questions for the TAM: Is the snapshot data per pool, and is it fresh at those times? Is there an account-level or placement-related limit on m8g.16xlarge in euw1-az1? Does something run at 01:00 UTC every night, such as another tenant's reservation or a scheduled job, that the snapshot doesn't capture?

## 3. What the data cannot show

- **True unmet demand.** ASGs retry, so the failed-instance counts (for example 70 per night for 24xlarge in 1a) include retries. They overstate the gap. We can't size a reservation from them. Ask the customer for desired capacity versus in-service capacity per hour (ASG CloudWatch metrics), and ask the account team for the free capacity per hour across the whole 20:00–03:00 window. The current snapshot only has 22:00 for 24xlarge and 01:30/02:30 for 16xlarge.
- **Snapshot coverage.** There's no snapshot for m8g.16xlarge in eu-west-1b, for any type at other hours, or for other m8g/c8g/r8g sizes we could fall back to.
- **The quota's actual value and current use.** CloudTrail only shows the limit message (1024 vCPU). The web tier launched hundreds of 64- and 96-vCPU instances over the window, so check Service Quotas and the current use of the Standard bucket directly. The data can't show how much headroom the web tier itself has.
- **Customer local time.** Hours are in UTC. If the customer's "night" means a different time zone, shift the hours accordingly.
- **Whether the ASG already has a mixed-instances policy.** The calls name single types. The ASG config is not in the export.
- **NOT RUN:** `simulate_split.py` (reservation batch plan). I haven't proposed a split because there is no reliable peak gap per AZ yet (see the first point). I'll run it once the account team proposes batch sizes and dates.
- Also produced: `work/rollout-report.html`, a daily page built from the summary.

## 4. Next 24 hours

| Who | Action |
|---|---|
| Customer platform team | Before tonight's 20:00 UTC peak: make sure mall-web-asg has a mixed-instances policy with m8g.24xlarge first and m8g.16xlarge plus other m8g/r8g/c8g sizes after it, weighted by vCPU and spread across both AZs. |
| Customer platform team | Add IP space or subnets in eu-west-1b (subnet-0bbb2222 runs out at 23:00). |
| Customer platform team | File the Service Quotas increase for the Standard On-Demand vCPU quota in eu-west-1, covering web plus batch-etl. |
| Customer platform team | Pull the ASG desired versus in-service capacity per hour for the last 3 nights to measure the real peak gap per AZ. |
| AWS account team / TAM | Investigate the m8g.16xlarge ICE in euw1-az1 at 01:00–03:00 UTC against the 240-free snapshot (evidence above). Supply hourly free-capacity data for 20:00–03:00 for m8g.24xlarge/16xlarge in both AZs. |
| Customer + account team | Scope an ODCR for m8g.24xlarge (both AZs, peak window) in batches, using the measured gap. Then run `simulate_split.py` to check which batch closes the gap in each AZ. |

**When pausing would make sense:** pause new waves only if a night with the fallback policy, extra subnets and the quota increase in place still leaves the web tier below its required in-service capacity. If that happens, hold the current wave, don't roll it back, until the TAM finding or the first reservation batch lands.
