# Night-time ASG launch failures (eu-west-1). Should the Graviton rollout be paused?

## Short answer

**Don't pause the Graviton rollout. Change how `mall-web-asg` is configured.** Graviton itself is fine. The problem is that the web tier depends on one very large instance size (m8g.24xlarge) and has only one fallback, m8g.16xlarge, which is in the same family. At the nightly peak EC2 has no spare capacity for that narrow choice. Two smaller problems are mixed into the same "failures at night" picture, and both are on the customer's side: a subnet in eu-west-1b is running out of IP addresses, and `batch-etl-asg` is hitting its vCPU quota. Pausing the rollout fixes neither of them.

## How the data was prepared

- `events.jsonl` has 1,289 lines but only **1,161 unique events**. Because the export merged two trails, 128 events appear twice: same `eventID` and identical content. I removed the duplicates before counting. Counting raw lines overstates failures in some hours.
- All events are RunInstances calls in account 111122223333, eu-west-1, made by the Auto Scaling service-linked role. Every error message's AZ matches the subnet's AZ.
- Times below are UTC. The data covers three nights, 3–6 March 2030, from 19:00 to 05:00. **The pattern is exactly the same on all three nights.**
- AZ mapping for this account: subnet-0aaa1111 = eu-west-1a = **euw1-az1**, and subnet-0bbb2222 = eu-west-1b = **euw1-az2**.

## What fails, per night (deduplicated, identical on each of the 3 nights)

| ASG / type | AZ | OK | Failed | Error | When (UTC) |
|---|---|---|---|---|---|
| mall-web m8g.24xlarge (primary) | 1a / az1 | 40 | 70 | InsufficientInstanceCapacity | 20:00–01:59 |
| mall-web m8g.24xlarge (primary) | 1b / az2 | 45 | 55 | InsufficientInstanceCapacity | 20:00–01:59 |
| mall-web m8g.16xlarge (fallback) | 1a / az1 | 60 | 30 | InsufficientInstanceCapacity | 01:00–02:59 |
| mall-web m8g.16xlarge (fallback) | 1b / az2 | 70 | 5 | InsufficientFreeAddressesInSubnet (subnet-0bbb2222) | 23:00–23:59 |
| batch-etl c8g.4xlarge | 1b / az2 | 0 | 12 | VcpuLimitExceeded (quota is 1,024 vCPU) | 22:00–22:59 |

Each night the web tier makes 375 attempts and 160 fail (43%). 155 of those 160 are capacity errors. Over the three nights that is 465 capacity errors, 15 IP-exhaustion errors and 36 quota errors. Before 20:00 and after 03:00 nothing fails.

## Root causes

### 1. Insufficient capacity for the chosen instance types (main cause; AWS capacity, made worse by the customer's configuration)

- **Primary m8g.24xlarge has no spare capacity in either AZ from 20:00 to 02:00.** The account team's snapshot agrees: 24xlarge shows `free: 0` in both AZs at 22:00 on all three nights. A fallback in the other AZ doesn't help, because both AZs are short at the same time.
- **The fallback m8g.16xlarge also runs out in eu-west-1a (euw1-az1) from 01:00 to 03:00.** Between 01:00 and 02:00, both the primary and the fallback fail in 1a, so the only capacity the ASG can get is 16xlarge in 1b. That is the hour with the biggest risk of losing capacity in one AZ.
- So there are two separate capacity shortages: a regional shortage of 24xlarge in the evening, and an AZ-specific shortage of 16xlarge after midnight. A list of two types from the same family can't get around either one.

**Warning about the capacity snapshot.** It reports **240 free m8g.16xlarge in "eu-west-1a" at 01:30 and 02:30**. Yet at exactly those times this account received 90 capacity errors for m8g.16xlarge in its own eu-west-1a (euw1-az1). AZ *names* are mapped to physical zones separately for each account. The snapshot is keyed by name, not by AZ ID, and it has no 16xlarge rows for 1b at all. The most likely explanation is that the snapshot's "eu-west-1a" is a different physical zone from the customer's eu-west-1a. **Until the account team restates it by AZ ID, don't use it to conclude that "1a has 16xlarge capacity".** (The 24xlarge rows are unaffected, because both AZs show 0.)

### 2. IP address exhaustion in subnet-0bbb2222 (eu-west-1b), customer-owned

- 5 launches fail with `InsufficientFreeAddressesInSubnet` between 23:00 and 23:59 every night.
- This matters more than the count suggests. When 24xlarge is short in both AZs, 1b is where the fallback works, and it is the same subnet that is running out of addresses.
- Large Graviton instances can make this worse if each instance carries several ENIs or prefix delegations.

### 3. vCPU quota on `batch-etl-asg`, customer-owned (not related to the web tier)

- 12 out of 12 c8g.4xlarge launches fail with `VcpuLimitExceeded` at 22:00, and none succeed.
- The 1,024-vCPU On-Demand Standard quota covers the A, C, D, H, I, M, R, T and Z families together. So the **m8g web fleet and the c8g batch fleet draw from the same limit**. At the nightly peak, a 96-vCPU 24xlarge web instance uses up quota the batch job needs.
- This is a quota problem, not a capacity problem, and AWS won't add capacity to fix it.

## Recommendation: keep rolling out, with these actions

| # | Action | Owner | When |
|---|---|---|---|
| 1 | Widen `mall-web-asg`'s instance options: use a mixed-instances policy or attribute-based instance selection (vCPU/memory ranges) with several families and sizes, for example m8g.12xlarge/16xlarge/24xlarge, m7g.16xlarge, r8g/c8g of similar size, and optionally an x86 type (m7i/m6i) as a last resort. Use the `price-capacity-optimized` or `capacity-optimized-prioritized` allocation strategy, and set weights so smaller sizes count proportionally. | Customer platform team | Before tonight's peak (20:00 UTC) |
| 2 | Add free IP space in eu-west-1b: a new or larger subnet, or a secondary VPC CIDR, attached to the ASG. Check how many ENIs or prefixes each instance uses. Optionally add a third AZ (euw1-az3) so there is a third independent capacity pool. | Customer platform / network team | This week; urgent, since 1b is the working fallback |
| 3 | Request an increase to the On-Demand Standard vCPU quota (L-1216C47A) through Service Quotas, sized for web peak plus batch. Consider moving the batch run off the 22:00 web peak. | Customer (request) / AWS Support (approval) | Now; the request takes time to approve |
| 4 | Reserve the nightly baseline: On-Demand Capacity Reservations (scheduled or future-dated), keyed to the customer's AZ IDs, for the number of web instances needed from 20:00 to 03:00. | Customer requests; AWS account team helps secure capacity | Days |
| 5 | Restate the capacity snapshot **by AZ ID** (euw1-az1 / euw1-az2 / euw1-az3), including m8g.16xlarge for every AZ and the 00:00–03:00 window. Also share any m8g.24xlarge capacity outlook for eu-west-1. | AWS account team | Before action 4 is sized |
| 6 | Watch tonight's run: track the number of capacity errors per type and AZ, and IP and quota errors. Dedupe CloudTrail by `eventID`, or fix the duplicated trail export. | Customer platform team | Tonight and the next nights |

**When a pause would be justified:** only if the web tier can't hold its required capacity tonight even after action 1. In that case, put an x86 type back in as a lower-priority option in the same mixed-instances list rather than rolling back the whole Graviton migration. The data contains no x86 launches to compare against, so nothing shows that Graviton itself is the problem. The failures come from relying on one large instance size, not from the CPU architecture.
