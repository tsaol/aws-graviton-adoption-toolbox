# Graviton rollout: night-time launch failures (eu-west-1, account 111122223333)

## 1. Verdict

**Keep rolling out. Don't pause.** The failures don't come from Graviton or Arm. They have four separate causes, and each one has its own fix:

- **m8g.24xlarge is short of capacity at peak in both AZs.** This explains most of the failures, and the account team's snapshot confirms it (0 free).
- **The m8g.16xlarge fallback also gets capacity errors in eu-west-1a around 01:00–03:00 UTC.** The account team's snapshot shows 240 free at those times, so pool depth doesn't explain these errors. The AWS account team (TAM) needs to investigate.
- **Two smaller problems are unrelated to capacity:** the batch ASG has hit its vCPU quota, and a web subnet in 1b is running out of IP addresses.

Every night the fallback (m8g.16xlarge) still launched instances in both AZs, so the web tier has a path that works.

## 2. Causes

The figures come from `classify.py` (`work/summary.json`). The export had 1,289 records, 128 of them duplicates from the two merged trails. Removing them leaves 1,161 RunInstances calls, each for 1 instance.

Overall: 645 launched, 465 capacity errors, 36 quota errors, 15 other errors. The pattern is identical on all three nights (03-03, 03-04, 03-05). Times are UTC, which is also Irish local time in March.

| # | Type | AZ (AZ ID) | Hours (UTC) | Failed instances (3 nights) | Error | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|---|
| A | m8g.24xlarge (primary) | eu-west-1a (euw1-az1) | 20:00–01:59 | 210 (70/night; 40/night still launched) | Server.InsufficientInstanceCapacity | The 24xlarge pool is short at evening peak. Snapshot at 22:00 shows **0 free** in both AZs. | Keep the fallback active and widen it to more same-generation Graviton types (e.g. m8g.12xlarge/m8g.8xlarge, c8g/r8g equivalents): use ASG mixed-instances with a capacity-optimized/prioritized strategy so the ASG doesn't keep retrying 24xlarge. Ask for On-Demand Capacity Reservations for the peak window, delivered in batches. | Customer platform team (fallback); customer + account team (reservations) |
| A | m8g.24xlarge (primary) | eu-west-1b (euw1-az2) | 20:00–01:59 | 165 (55/night; 45/night still launched) | Server.InsufficientInstanceCapacity | Same as above: a peak-hour pool shortage across both AZs. | Same as above | Same as above |
| B | m8g.16xlarge (fallback) | eu-west-1a (euw1-az1) | 01:00–02:59 only | 90 (30/night; 01h: 42, 02h: 48) | Server.InsufficientInstanceCapacity | **Snapshot shows 240 free** at 01:30 and 02:30 on every night. Errors within ±30 min of those points: 16/14, 13/17, 13/17. Launches in the same AZ and hours partly succeed. Pool depth doesn't explain this. | Send the evidence (table in §3) to the TAM to check account-level or placement-level limits on the EC2 side. **Don't just switch types because of this.** Meanwhile keep the fallback list wide (cause A) and let the ASG rebalance to 1b in that window. | AWS account team / TAM (investigation); customer platform team (keep the fallback) |
| C | c8g.4xlarge (`batch-etl-asg`, not web) | eu-west-1b (euw1-az2) | 22:00 | 36 (12/night) | VcpuLimitExceeded ("limit of 1024") | A real On-Demand vCPU quota limit. The Graviton web fleet uses the same Standard-instance vCPU bucket, so the rollout probably uses up headroom that batch needs (inferred; the data doesn't show running vCPU). | Request an increase to the On-Demand Standard vCPU quota in Service Quotas, sized for web peak plus batch. | Customer (platform/cloud ops) |
| D | m8g.16xlarge | eu-west-1b, subnet-0bbb2222 | 23:00 | 15 (5/night) | InsufficientFreeAddressesInSubnet | Configuration: the subnet has run out of IPs at peak. | Add subnets/CIDR in 1b to the ASG, or enlarge the subnet. | Customer (network/platform) |

Capacity errors (A, B) are **not** a quota problem. A quota increase won't fix them.

## 3. Evidence package for the TAM (cause B)

| Snapshot time (UTC) | Type | AZ / AZ ID | Free in snapshot | Capacity errors within ±30 min |
|---|---|---|---|---|
| 2030-03-04 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 16 |
| 2030-03-04 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 14 |
| 2030-03-05 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 13 |
| 2030-03-05 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 17 |
| 2030-03-06 01:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 13 |
| 2030-03-06 02:30 | m8g.16xlarge | eu-west-1a / euw1-az1 | 240 | 17 |

Calls come from the AutoScaling service-linked role, ASG `mall-web-asg`, subnet-0aaa1111, with no placement group or tenancy set in the requests. Ask the TAM why RunInstances returns ICE at a point where their own data shows free capacity: for example account-level or zonal throttling, a host or rack constraint, or a snapshot that is stale or at the wrong granularity. Use the AZ ID (euw1-az1) when you raise it.

## 4. What the data can't show, and what to ask the account team for

- **Unmet demand.** Failed calls include ASG retries, so 70 failures a night doesn't mean 70 missing instances. This means I can't size a reservation yet. The batch reservation plan (`simulate_split.py`) was **NOT RUN** because there's no reliable peak-gap figure. The platform team should provide the ASG desired vs. in-service count at peak, per AZ.
- **Capacity reservation history.** The export only contains RunInstances, so `CancelCapacityReservation` and other reservation events can't be seen. The check "did ICE start right after a reservation was released?" was **NOT RUN**. Ask for CloudTrail reservation events (or `describe-capacity-reservations`) for the week before the rollout.
- **Snapshot coverage.** The snapshot only covers m8g.24xlarge at 22:00 and m8g.16xlarge in 1a at 01:30/02:30. It has nothing for 16xlarge in 1b or other hours, and doesn't define the units of "free". Ask the account team for hourly free capacity from 19:00 to 05:00 for m8g.24xlarge, m8g.16xlarge and the other fallback candidates in euw1-az1 and euw1-az2.
- **vCPU usage.** Running vCPU against the 1024 limit isn't in the data. Check Service Quotas / CloudWatch usage metrics.
- **Timezone.** I assumed UTC = local time (Ireland in March). If the customer works in another timezone, shift the hours.
- **Window.** The data covers three nights, 2030-03-03 19:06 to 2030-03-06 04:58 UTC. Daytime behaviour isn't covered.

## 5. When pausing would make sense

Pause new rollout waves (not the fleet already migrated) only if one of these happens:
- After the fallback list is widened, web in-service capacity at peak still falls below what's needed.
- The TAM finds an account-level constraint on m8g that can't be lifted before the next wave.
- Reservations for the peak window are refused, and no same-generation Graviton fallback has enough capacity.

## 6. Next 24 hours

| Who | What |
|---|---|
| Customer platform team | Before tonight's 20:00 peak, update `mall-web-asg` to mixed instances (m8g.24xlarge → m8g.16xlarge → m8g.12xlarge and other equivalent 8th-generation Graviton types), keep both AZs, and add a subnet in 1b. Record desired vs. in-service count per AZ from 19:00 to 05:00. |
| Customer cloud ops | Request the On-Demand Standard vCPU quota increase in Service Quotas, sized for web peak plus batch-etl. |
| AWS account team / TAM | Investigate cause B using the §3 package. Provide hourly capacity for the fallback candidates. Discuss On-Demand Capacity Reservations for the 20:00–02:00 peak, delivered in batches per AZ. |
| Customer + account team | Once there's a peak-gap number, plan the reservation batches (`simulate_split.py`). If a reservation is ever released, agree a rollback condition **before** releasing it. |

Supporting files: `work/summary.json` (classifier output) and `work/rollout-report.html` (daily page).
