# Night-time launch failures in eu-west-1: diagnosis and recommendation

## Short answer

**Don't pause the Graviton rollout across the board.** The failures don't come from Graviton itself. They come from three separate problems, and rolling back would fix none of them for sure:

1. **The web tier asks for too few capacity pools (main cause).** `mall-web-asg` can only use 2 instance types (m8g.24xlarge, m8g.16xlarge) in 2 AZs, and it grows by about 215 large instances every night. m8g.24xlarge runs out of capacity in **both** AZs from 20:00 to 01:59 UTC, and m8g.16xlarge runs out in eu-west-1a from 01:00 to 02:59 UTC.
2. **Subnet `subnet-0bbb2222` (eu-west-1b) runs out of IP addresses** around 23:00 UTC. This is a customer network problem.
3. **`batch-etl-asg` hits a vCPU quota limit** (`VcpuLimitExceeded`, limit 1024) at 22:00 UTC and **launches nothing at all**. This is a quota problem with no link to the web tier's Graviton change.

The web tier does recover: every night it reaches the same peak (170× 16xl and 145× 24xl) by about 04:00 UTC, but only after hundreds of failed attempts and retries. The batch job is the one actually failing completely.

What to do: continue the rollout, but **change the web ASG to use more instance types and AZs before moving more x86 capacity onto it**. Fix the subnet and the quota separately (owners are listed below).

## Evidence

### Data caveat: the CloudTrail export contains duplicates
`events.jsonl.gz` holds 3,754 lines but only 1,161 actual API calls. Each call (same `requestID`, same timestamp, same parameters and result) shows up 1–5 times, sometimes with different `eventID`s. Counting raw lines overstates failures by about 3×. All numbers below count unique `requestID`s. The deduplicated successes match the CUR hourly usage exactly (see the last table), which confirms this is the right way to count.

### Failures per night (identical on all three nights: 3/4, 4/5 and 5/6 March)

| ASG | Type | Subnet / AZ (AZ ID) | OK | Failed | Error | UTC hours |
|---|---|---|---|---|---|---|
| mall-web-asg | m8g.24xlarge | 0aaa1111 / eu-west-1a (euw1-az1) | 40 | **70** | InsufficientInstanceCapacity | 20–01 |
| mall-web-asg | m8g.24xlarge | 0bbb2222 / eu-west-1b (euw1-az2) | 45 | **55** | InsufficientInstanceCapacity | 20–01 |
| mall-web-asg | m8g.16xlarge (fallback) | 0aaa1111 / eu-west-1a (euw1-az1) | 60 | **30** | InsufficientInstanceCapacity | 01–02 |
| mall-web-asg | m8g.16xlarge (fallback) | 0bbb2222 / eu-west-1b (euw1-az2) | 70 | **5** | InsufficientFreeAddressesInSubnet | 23 |
| batch-etl-asg | c8g.4xlarge | 0bbb2222 / eu-west-1b | **0** | **12** | VcpuLimitExceeded ("limit of 1024") | 22 |

Each night that's 160 failed web-tier launches out of 375 attempts, plus 12 of 12 batch launches failing.

### Cause 1: capacity errors (ICE), from a launch config with too few capacity pools
- Every capacity error message names a single AZ and says capacity is available *"by not specifying an Availability Zone … or choosing a different Availability Zone"*. That points to shortages in specific pools, not a shortage across the region.
- The web fleet ramps from 100 to 315 instances each night (from about 8.3k to 24.8k vCPU, all m8g.16xl/24xl, 19:00 to 04:00 UTC per the CUR). In the busiest hours it draws only on 4 pools (2 sizes × 2 AZs). The 24xlarge pools empty out in both AZs. Then the fallback size empties out in eu-west-1a, exactly while the ASG is pushing all its retries into it.
- The account team's snapshot agrees for m8g.24xlarge: `free: 0` in both AZs at 22:00 every night.
- **Graviton itself isn't proven to be the cause.** The CUR shows m8g running from the first hour of data, and there's no x86 baseline in the files. So the data can't show that x86 would have launched cleanly. Running the same single-family, two-size, two-AZ setup on x86 large sizes could hit the same limits.

### The account team's snapshot conflicts with the CloudTrail events. Don't rely on it until it's restated in AZ IDs.
The snapshot shows **240 free m8g.16xlarge in "eu-west-1a"** at 01:30 and 02:30 UTC on all three nights. Yet the customer received 30 capacity errors per night for m8g.16xlarge in *their* eu-west-1a (euw1-az1) at exactly 01:00–02:59. Meanwhile their m8g.16xlarge launches in eu-west-1b succeeded at those hours.

The likely explanation: AZ names are mapped separately for each account, and the snapshot is keyed by AZ name with no AZ ID. Its "eu-west-1a" is probably a different physical zone from the customer's eu-west-1a = euw1-az1. Their m8g.16xlarge launches in eu-west-1b (euw1-az2) succeeded at those exact hours, which fits the snapshot's "1a" actually being euw1-az2. Also note the snapshot doesn't cover m8g.16xlarge in eu-west-1b at all, and doesn't cover any third AZ.

### Cause 2: subnet IP exhaustion in eu-west-1b
At 23:00 UTC every night, 5 m8g.16xlarge launches into `subnet-0bbb2222` fail with `InsufficientFreeAddressesInSubnet`. This happens about an hour after batch-etl tries to launch into the same subnet, and while the web tier is at about 100–115 instances in that AZ. More AWS capacity won't help here. The subnet needs more address space.

### Cause 3: vCPU quota on batch-etl
`batch-etl-asg` (c8g.4xlarge, 16 vCPU) fails 12 of 12 attempts at 22:00 UTC every night, with "vCPU limit of 1024". It never launches an instance. Something here doesn't add up: c8g and m8g share the Standard On-Demand vCPU bucket, and the web tier is already running about 15–16k vCPU in that bucket at 22:00. So the 1024 limit the batch job hits probably isn't the same applied quota. It could be a different purchase option or bucket set in batch-etl's launch template (for example Spot), or a quota mapping problem. This needs checking in Service Quotas.

## Actions and owners

| # | Action | Owner |
|---|---|---|
| 1 | **Make the web ASG use more capacity pools.** Switch `mall-web-asg` to a mixed-instances policy (or attribute-based instance type selection) covering several Graviton types and sizes, e.g. m8g.8xl/12xl/16xl/24xl, m7g.*, c8g/r8g.* where the app's memory/CPU ratio allows. Set instance weights by vCPU and use the `price-capacity-optimized` allocation strategy (or `prioritized`, keeping 24xl first). Smaller sizes are much easier to obtain than 24xl. | Customer platform team |
| 2 | **Add a third AZ** (euw1-az3) with its own subnet to the web ASG, so it isn't limited to two AZs. | Customer platform team + network team |
| 3 | **Guarantee the nightly peak.** Use On-Demand Capacity Reservations (or future-dated reservations) for the predictable 19:00–04:00 UTC peak, at least for the 24xl baseline. Also start the scale-out earlier with scheduled or predictive scaling, so it isn't competing for capacity at its steepest part. | Customer platform team (purchase); AWS account team (help sizing/securing ODCRs) |
| 4 | **Restate the capacity snapshot by AZ ID** (euw1-az1/az2/az3) for m8g.16xl and 24xl plus the candidate types from #1. Escalate the m8g.24xlarge shortage in euw1-az1/az2 internally. | AWS account team |
| 5 | **Enlarge the address space for eu-west-1b.** Add a secondary CIDR/subnet, or move batch-etl to its own subnet. Check what else uses IPs in `subnet-0bbb2222` (ENIs, batch, Lambda/EKS). | Customer network team |
| 6 | **Fix the batch-etl vCPU quota.** In Service Quotas, check which quota batch-etl actually hits (On-Demand vs Spot, Standard bucket) and why it shows 1024. Request an increase that covers batch plus web peak plus headroom. | Customer platform team (request); AWS Support / account team (approve or expedite) |
| 7 | **Gate the rollout, don't pause it.** Move more x86 workloads onto Graviton only after #1–#2 are live, and watch unique-request ICE counts (not raw CloudTrail lines) for one night. Confirm the web ASG reaches its desired capacity on time; ASG activity history is needed for that, because these files show only that it ends at the same peak, not when it should have got there. | Customer platform team |
| 8 | **Fix the CloudTrail export deduplication** (dedupe by `requestID`/`eventID`) so failure dashboards stop overstating errors by about 3×. | Customer platform / observability team |

## Limits of this analysis
- There's no pre-rollout or x86 data, so I can't compare launch failures before and after the Graviton change.
- The ASG's desired capacity and scaling activities weren't provided. I can see the web fleet reaches the same peak every night by about 04:00 UTC, but not how late it is compared with the target.
- The snapshot is keyed only by AZ name, covers few type/AZ combinations, and contradicts the CloudTrail events for m8g.16xlarge in eu-west-1a. I treated it as unreliable until it's restated by AZ ID.
