# Night-time launch failures in eu-west-1: findings and recommendation

## Short answer

**Keep rolling out Graviton, but change how the web tier asks for capacity before you add more nights of load to it.** Graviton itself isn't failing. The failures come from asking for only two instance sizes (`m8g.24xlarge` and `m8g.16xlarge`) in only two AZs during a nightly window when EC2 has run out of exactly those capacity pools. On top of that, two problems the customer owns (subnet IP exhaustion and a vCPU quota) show up every night at a fixed time.

One caveat: the export starts on 2030-03-03 at 19:06Z, which is the first night of the rollout. So there's no pre-rollout baseline, and I can't prove the old x86 setup would have launched cleanly. The data does show that every failure is tied to a specific pool, quota or subnet, and that none of them comes from Graviton (no AMI, architecture or launch-template errors).

## Data hygiene first

- The export merges two trails, so **128 events appear twice** with the same `eventID` and identical content. After removing duplicates there are **1,161 RunInstances calls**, not 1,289. Without deduplication, every failure count is inflated by about 10%. If their dashboards use the merged trail, they're over-counting too.
- All calls are from the Auto Scaling service-linked role, in account 111122223333, in eu-west-1. Subnet `subnet-0aaa1111` is in eu-west-1a (`euw1-az1`) and `subnet-0bbb2222` is in eu-west-1b (`euw1-az2`). In every successful launch, the AZ where the instance was placed matches the subnet's AZ.

## What fails (deduplicated, 3 nights: 03→04, 04→05, 05→06 March 2030)

| # | Error | Instance type / ASG | Where | Window (UTC), every night | Count per night | Total |
|---|---|---|---|---|---|---|
| 1 | `InsufficientInstanceCapacity` | m8g.24xlarge / mall-web-asg | **both** AZs | ~20:00 – 02:00 | 70 (1a) + 55 (1b) | 375 |
| 2 | `InsufficientInstanceCapacity` | m8g.16xlarge / mall-web-asg | **eu-west-1a only** | 01:00 – 03:00 | 30 | 90 |
| 3 | `VcpuLimitExceeded` (limit 1024 vCPU) | c8g.4xlarge / batch-etl-asg | eu-west-1b | 22:00 – 23:00 | 12 | 36 |
| 4 | `InsufficientFreeAddressesInSubnet` | m8g.16xlarge / mall-web-asg | subnet-0bbb2222 (1b) | 23:00 – 24:00 | 5 | 15 |

That's 516 failed calls out of 1,161 (44%). Of those, 465 (90%) are insufficient-capacity errors. The pattern repeats almost exactly each night: the counts per night are identical and the start and end times are within minutes of each other.

### Cause A: the primary type is sold out at night in both AZs
`m8g.24xlarge` returns insufficient-capacity errors in both AZs from about 20:00 to 02:00. The account team's snapshot agrees: `free: 0` in both eu-west-1a and eu-west-1b at 22:00 on all three nights. The ASG then falls back to `m8g.16xlarge`, which mostly works.

### Cause B: the fallback type runs out in eu-west-1a from 01:00 to 03:00
`m8g.16xlarge` returns insufficient-capacity errors in eu-west-1a (`euw1-az1`) from 01:00 to 03:00, and only in eu-west-1a. From 01:00 to 02:00 **both** of the web tier's types fail in eu-west-1a at the same time, so the fallback doesn't help there. The ASG can only get capacity in eu-west-1b.

**This contradicts the capacity snapshot.** The snapshot reports `free: 240` for m8g.16xlarge in "eu-west-1a" at 01:30 and 02:30 on all three nights, yet CloudTrail shows `m8g.16xlarge` insufficient-capacity errors in this account's eu-west-1a at exactly those times. The likely explanation is that **AZ names are mapped to physical AZs separately for each AWS account**. The snapshot uses AZ names only, with no AZ IDs. If it was produced from another account's view, its "eu-west-1a" may not be this account's `euw1-az1`. **Don't use the snapshot to decide where to place capacity** until it's restated in AZ IDs. It also has gaps: it has no m8g.16xlarge data for eu-west-1b, and no data at all between 20:00 and 01:00 except a single 22:00 point.

### Cause C: subnet-0bbb2222 runs out of IP addresses around 23:00
eu-west-1b is the AZ where the fallback still works, and at peak its subnet has no free IP addresses. So the only working path also gets blocked for part of the night. This is a network sizing problem, not a capacity problem.

### Cause D: the On-Demand vCPU quota is hit around 22:00
`batch-etl-asg` (c8g.4xlarge) hits the account's 1,024-vCPU On-Demand limit for the Standard instance family group. The m8g web instances (96 or 64 vCPU each) count against the same limit. As the Graviton web tier scales up at night, it uses up the headroom batch needs. This is the one problem the rollout makes worse indirectly: same pool of vCPUs, bigger instances.

## What to do and who owns it

| Priority | Action | Owner |
|---|---|---|
| 1 | Widen the web ASG's mixed instances policy beyond two sizes. Add more m8g sizes (e.g. 12xlarge) plus other Graviton families that work for the web tier (m7g.16xlarge/12xlarge, possibly c8g/r8g equivalents), or use attribute-based instance type selection. Keep an x86 type (e.g. m7i) as a last-resort entry while the rollout is in progress. Use `price-capacity-optimized` (or `capacity-optimized-prioritized` if order matters), so the ASG moves away from depleted pools instead of retrying them. | Customer platform team |
| 2 | Add a third AZ (an eu-west-1c subnet) to the web ASG, so the 01:00–03:00 shortage in `euw1-az1` doesn't leave a single AZ carrying the load. | Customer platform and network teams |
| 3 | Scale up before 20:00 using scheduled scaling or a warm pool. m8g.24xlarge launches fine in the evening and the snapshot doesn't show any shortage then. Capacity that's already running doesn't go away. | Customer platform team |
| 4 | Buy On-Demand Capacity Reservations for the guaranteed night-time baseline of m8g, per AZ, for the 20:00–03:00 window. | Customer platform team (purchase); AWS account team (help confirm availability) |
| 5 | Enlarge `subnet-0bbb2222` or add another subnet in eu-west-1b, and check IP usage across all subnets the ASGs use. | Customer network team |
| 6 | Request an increase to the On-Demand Standard vCPU quota in eu-west-1 sized for web plus batch at their combined nightly peak, and set a CloudWatch alarm on the quota usage metric. | Customer platform team or batch-etl owner (files the request); AWS (approves it) |
| 7 | Reissue the capacity snapshot **in AZ IDs** (`euw1-az1`, `euw1-az2`, …), for every hour from 20:00 to 03:00, for both m8g sizes and any candidate alternative types. Explain the 240-free vs. insufficient-capacity contradiction for m8g.16xlarge in `euw1-az1`, and give an outlook for m8g capacity in these AZs. | AWS account team |
| 8 | Deduplicate the merged CloudTrail feed by `eventID` in any failure dashboards or alerts. | Customer platform or observability team |

## On pausing the rollout

Pausing doesn't add any m8g capacity, and the quota and subnet problems would remain. What pausing *would* do is move the web tier back onto different (x86) capacity pools. If nights become critical before items 1–3 are done, keeping an x86 type as the last entry in the mixed instances policy gives the same protection without stopping the rollout. My recommendation: **keep rolling out, but don't move more web capacity onto the two-type m8g setup until items 1–3 (and 5–6 for the fixed-time errors) are in place.** After that, re-check one night of deduplicated CloudTrail data. Insufficient-capacity errors should turn into launches of other instance types, and the 22:00 and 23:00 errors should be gone.
