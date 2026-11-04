# Night-time launch failures in eu-west-1: diagnosis and recommendation

## 1. Verdict

**Keep rolling out. Don't pause.** Graviton isn't failing in general. Every night, the fallback m8g.16xlarge launched without errors in eu-west-1b, and in eu-west-1a it still reached its CUR peak of 80 running instances. The failures come from four separate causes, and each has its own fix:

1. The m8g.24xlarge pool is short at peak in both AZs.
2. Some m8g.16xlarge capacity errors in eu-west-1a happen while the account team's snapshot shows 240 instances free. Pool depth doesn't explain these, so the TAM needs to look at them.
3. A vCPU quota limit is hitting a different ASG (`batch-etl-asg`).
4. A subnet in eu-west-1b is running out of IP addresses.

Only cause 1 is about Graviton capacity, and the fix is to change the web tier's instance mix, not to stop the rollout.

## 2. Causes

All counts come from `classify.py`, applied to 3,754 raw records. 334 were exact duplicates and 2,259 were extra rows for the same request, which leaves **1,161 unique requests**:
- 645 succeeded
- 465 failed on capacity
- 36 failed on quota
- 15 failed on other errors

The window is 2030-03-03 19:06Z to 2030-03-06 04:58Z, so three nights. Hours are UTC, and eu-west-1 local time is the same in March. Every failure is a single-instance request (min/max = 1) made by the Auto Scaling service role.

| # | Type / AZ (AZ ID) | Error | Hours (UTC) | Failed instances (3 nights) | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|
| A | m8g.24xlarge, eu-west-1a (euw1-az1) | InsufficientInstanceCapacity | 20:00–01:59 | 210 (70/night) | The pool is short at peak. The snapshot shows **0 free** at 22:00 every night. 40 launches per night still succeeded (CUR peak 70 running). | Make the web ASG a mixed-instances policy with several Graviton types, using the `capacity-optimized` or `price-capacity-optimized` allocation strategy. Candidates: m8g.24xlarge, m8g.16xlarge, plus other same-generation Graviton options such as m8g.48xlarge or c8g/r8g equivalents, using instance weights. Use m7g only as a last resort. For the baseline you need guaranteed at peak, consider On-Demand Capacity Reservations (ODCRs) or a future-dated reservation, delivered in batches. | Customer platform team (ASG config). Account team + customer (reservations) |
| B | m8g.24xlarge, eu-west-1b (euw1-az2) | InsufficientInstanceCapacity | 20:00–01:59 | 165 (55/night) | Same as A. Snapshot shows **0 free** at 22:00. 45 per night succeeded (CUR peak 75). | Same as A | Same as A |
| C | m8g.16xlarge, eu-west-1a (euw1-az1) | InsufficientInstanceCapacity | 01:00–02:59 | 90 (30/night) | **Pool depth doesn't explain this.** On all 3 nights, the snapshot at 01:30 and 02:30 shows **240 free**, yet there were 13–17 capacity errors within ±30 min of each snapshot point (6 flagged points). CUR shows only about 63–76 of these instances running then. eu-west-1b got no capacity errors for this type. | Send the evidence (table below) to the TAM and ask them to check account-level or placement-level constraints for m8g.16xlarge in euw1-az1. Until they answer, keep the fallback in place and let the ASG try more types (see A) and rebalance into eu-west-1b. **Don't** just swap instance types and call it fixed. | AWS account team / TAM (investigate). Customer (send evidence, keep fallback) |
| D | c8g.4xlarge, eu-west-1b, **`batch-etl-asg`** (not the web tier) | VcpuLimitExceeded ("limit of 1024") | 22:00–22:59 | 36 (12/night) | A real quota error, separate from the web tier's problems. | Check the applied Running On-Demand Standard vCPU quota (`L-1216C47A`) in Service Quotas and raise it to cover web + batch at peak. See the caveat in section 3. | Customer (Service Quotas request). Account team can help push it through |
| E | m8g.16xlarge, eu-west-1b (euw1-az2), subnet-0bbb2222 | InsufficientFreeAddressesInSubnet | 23:00–23:59 | 15 (5/night) | Configuration: the subnet is out of IPs. Nothing to do with capacity or Graviton. | Add subnets or IP space in eu-west-1b (for example a larger or second subnet attached to the ASG). Check whether ENI/IP-per-instance settings are using up addresses. | Customer platform / network team |

There were no `CancelCapacityReservation` events in the logs (`reservation_events` is empty), so a released reservation isn't behind the failures.

### Evidence pack for the TAM (cause C)

The table below lists all 6 flagged points: capacity errors while the account team's snapshot shows capacity free.

| Snapshot time (UTC) | Type | AZ / AZ ID | Free in snapshot | Capacity errors within ±30 min |
|---|---|---|---|---|
| 2030-03-04 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 16 |
| 2030-03-04 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 14 |
| 2030-03-05 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 13 |
| 2030-03-05 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 17 |
| 2030-03-06 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 13 |
| 2030-03-06 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 17 |

Account 111122223333, ASG `mall-web-asg`, subnet-0aaa1111. Each night, 42 failures fell in the 01:00 hour and 48 in the 02:00 hour.

## 3. What the data can't show, and what to ask for

- **Why cause C happens.** CloudTrail only shows the error. Whether there is an account-level limit, a placement constraint, or a mismatch between the snapshot and the real pool can only be checked on the AWS side. Ask the TAM.
- **The snapshot is sparse.** It covers m8g.24xlarge only at 22:00 and m8g.16xlarge in eu-west-1a only at 01:30 and 02:30. Ask the account team for hourly free capacity from 18:00 to 06:00 for both types in both AZs, plus any same-generation alternatives being considered (other m8g sizes, c8g, r8g).
- **The quota numbers don't add up.** The error message gives a vCPU limit of 1024, but CUR shows the web tier alone running roughly 24,800 Standard-family vCPU at peak: 145 × m8g.24xlarge (96 vCPU) + 170 × m8g.16xlarge (64 vCPU). m8g and c8g count against the same `L-1216C47A` bucket. The customer should check the applied quota value and its history in Service Quotas, and include this mismatch when they file the request or talk to the TAM.
- **Unmet demand.** CUR shows what ran, not what the ASG wanted to run. The night peaks were still reached (by about 04:00), so the failures look like slower scale-out rather than a permanent shortfall. ASG desired-capacity history (CloudWatch `GroupDesiredCapacity`) would confirm how much demand went unmet and for how long.
- **Checks not run:**
  - Pre-rollout check (`precheck.py`): NOT RUN. Offerings, reservations and quota files weren't provided.
  - Reservation batch simulation (`simulate_split.py`): NOT RUN. No reservation plan was given.
  - Daily page (`daily_page.py`): NOT RUN.
  - Weekly adoption report (`weekly_report.py`): NOT RUN. CUR only covers m8g, so there's no x86 baseline to compare against.

## 4. Next 24 hours

| Who | What |
|---|---|
| Customer platform team | Before tonight's 20:00 ramp: switch `mall-web-asg` to a mixed-instances policy with several Graviton types and sizes (weighted), using `price-capacity-optimized` or `capacity-optimized`. Keep m8g.16xlarge as a fallback, and let the ASG rebalance across both AZs. Consider starting the scale-out earlier (scheduled action around 18:00–19:00) so the ramp doesn't hit the 20:00–01:00 shortage. |
| Customer network team | Add IP space or another subnet in eu-west-1b for the web ASG (cause E). |
| Customer (`batch-etl-asg` owner) | Check the applied value of `L-1216C47A` and file a quota increase for peak web + batch vCPU (cause D). Don't file one for the InsufficientInstanceCapacity errors. |
| AWS account team / TAM | Investigate cause C using the evidence pack above. Provide hourly free-capacity data for the night window. Discuss ODCRs or future-dated reservations, in batches, for the m8g baseline in euw1-az1 and euw1-az2. |
| Everyone, tomorrow morning | Re-run `classify.py` on tonight's CloudTrail. |

**When pausing would make sense:** pause new waves (not a rollback) only if, after the mixed-instances change is in place, the web tier still can't reach its night peak, or capacity errors spread to the fallback types in both AZs. Until then, pausing wouldn't fix any of the five causes.
