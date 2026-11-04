# Night-time launch failures, eu-west-1: diagnosis and recommendation

## Bottom line

**Keep rolling out. Don't expand the rollout until the web ASG can fall back to more instance types and AZs.** Graviton isn't what's failing. The web tier depends on one large size, and the account doesn't have a fallback for when that size runs out at night. The failures come from **four separate causes**. Only the first two are EC2 capacity, and they are two different constraints, not one:

| # | Error (unique API calls, 3 nights) | What / where / when | Capacity? | Owner |
|---|---|---|---|---|
| 1 | `InsufficientInstanceCapacity`: **375** | **m8g.24xlarge** (primary), **both AZs** (1a and 1b), every night **20:00–02:00 UTC** | Yes | Customer (ASG design) + AWS account team (capacity) |
| 2 | `InsufficientInstanceCapacity`: **90** | **m8g.16xlarge** (fallback), **only eu-west-1a (euw1-az1)**, every night **01:00–03:00 UTC** | Yes | Same as above, and the account team's snapshot disagrees (see below) |
| 3 | `InsufficientFreeAddressesInSubnet`: **15** | m8g.16xlarge, **subnet-0bbb2222 (eu-west-1b)**, every night **23:00–00:00 UTC** | **No.** The subnet ran out of IP addresses | Customer (network) |
| 4 | `VcpuLimitExceeded`: **36** | **c8g.4xlarge, `batch-etl-asg`** (not the web tier), subnet 1b, every night **22:00–23:00 UTC**, "vCPU limit of 1024" | **No.** It's a quota | Customer (batch owner) files the quota request; AWS approves it |

Total: 1,161 unique RunInstances calls, 645 succeeded and 516 failed. The web ASG still reached the same peak every night (≈315 m8g instances by 04:00, then scaled in at 06:00). So, as far as this data shows, the impact is **slow or delayed scale-out during the evening ramp**, not a fleet that never reaches size. I can't see the ASG's desired capacity, so I can't say how far behind demand it fell.

## Evidence

### Data hygiene (do this before quoting any numbers)
- `events.jsonl.gz` has 3,754 lines but only **1,161 real API calls**. The export repeats calls 1–5 times. Some copies are byte-identical (same `eventID`). Others have a **new `eventID` but the same `requestID`, payload, and even the same instance ID**. Deduplicating by `eventID` still leaves 3,420 rows, and those rows claim 1,871 launches for only 645 distinct instance IDs.
- I deduplicated by `requestID`. That gives **645 successful launches, which matches the CUR exactly**: the nightly growth in instance-hours, per type and AZ, is 16xl-1a +60, 16xl-1b +70, 24xl-1a +40, 24xl-1b +45 per night, × 3 nights = 180/210/120/135 successes. Counting raw lines would have reported 1,687 failures. The real number is 516.

### Cause 1: m8g.24xlarge is out of capacity in both AZs, 20:00–02:00
- Every night from about 20:00 to 02:00 UTC, most m8g.24xlarge launches fail in both 1a and 1b (e.g. 21:00 on night 1: 13 of 18 fail in 1a, 14 of 17 in 1b). Error message: "We currently do not have sufficient m8g.24xlarge capacity in the Availability Zone you requested".
- From 02:00 to 04:00, m8g.24xlarge launches succeed again in both AZs.
- The account team's snapshot agrees: **0 free m8g.24xlarge in both AZs at 22:00** on all three nights.
- Some launches still succeed during that window, so the pool is close to exhausted rather than completely empty. That's typical of a large size competing with other demand in the same evening peak.

### Cause 2: m8g.16xlarge is out of capacity in eu-west-1a only, 01:00–03:00
- m8g.16xlarge **never** gets an ICE in 1b. In 1a it fails heavily, but only from 01:00 to 03:00 (e.g. 02:00 hours: 14/18, 17/21, 17/25 failed). Outside that window it succeeds.
- So when the primary is short in both AZs, the fallback is also short in 1a during part of the night. 1b is the only place where the fallback keeps working, and from 23:00 cause 3 also hits 1b.
- **The account team's snapshot contradicts this.** It shows **240 free m8g.16xlarge in "eu-west-1a" at 01:30 and 02:30** on every night, which is exactly when this account gets ICE for that type in its eu-west-1a. AZ *names* are mapped differently in each account. In this account, eu-west-1a = **euw1-az1** and eu-west-1b = **euw1-az2**. The snapshot has no AZ IDs, so its "eu-west-1a" is probably a different physical AZ. Don't plan around the "240 free" figure until the snapshot is reissued with AZ IDs. The snapshot is also thin: it has nothing for 1b at 01:30/02:30 and nothing for m8g.24xlarge outside 22:00.

### Cause 3: subnet-0bbb2222 runs out of IPs at 23:00
- 15 failures, all in the 23:00 hour, all in subnet-0bbb2222 (1b). That's when 1b is busy and the web fleet in 1b is around 105–120 instances and growing.
- This isn't a capacity problem and has nothing to do with Graviton. It would happen with any instance type. It does get worse when the ASG falls back to a smaller size, because the same capacity then needs more instances and so more IPs.

### Cause 4: batch-etl hits a vCPU quota at 22:00
- `batch-etl-asg` launches c8g.4xlarge in subnet 1b at 22:00 every night. All 36 calls failed ("vCPU limit of 1024"), so batch launched nothing.
- **Open question:** the web tier runs about 24,800 vCPU of m8g On-Demand at peak (80×64 + 90×64 + 70×96 + 75×96). m8g and c8g share the same Standard On-Demand quota bucket. A 1,024-vCPU limit therefore can't be the On-Demand Standard quota this web fleet is running under. Batch is most likely launching through a different quota, for example **Spot** via its launch template. Check in Service Quotas before filing the increase.

### What the data can't show
- There's no data from before the rollout and no x86 usage in the CUR. I can't tell whether these pools were already tight before, or whether the rollout made it worse by moving demand onto m8g.24xlarge. Either way, the failures are tied to specific sizes, AZs, and hours, which is the pattern of a fleet that depends on too few instance pools. They don't point to a problem with Graviton.
- The timestamps in the data are from 2030 (03-03 → 03-06). I've used them as given.

## What to do and who owns it

### Customer platform team (web tier). Before the next evening ramp
1. **Widen the web ASG's instance list** (mixed instances policy). Today it uses only m8g.24xlarge and m8g.16xlarge. Add more Graviton sizes and families with equivalent capacity, e.g. m8g.12xlarge, m8g.48xlarge, m7g.16xlarge, m7g.12xlarge, and r8g/c8g if the app's memory profile allows. Use weighted capacity (vCPU-based) so smaller sizes count correctly. Use `prioritized` allocation if 24xl must stay first, or `price-capacity-optimized`/`capacity-optimized`. Attribute-based instance selection is an alternative to listing types by hand.
2. **Add a third AZ** (euw1-az3) subnet to the ASG. Today both the primary and the fallback depend on only two AZs.
3. **Start the scale-out earlier.** At 19:00 there are no failures. Use scheduled scaling to launch the night's base capacity at about 19:00, or a warm pool, instead of chasing the ramp from 20:00 to 04:00.
4. **Fix subnet IP space in 1b.** Enlarge subnet-0bbb2222 or add more subnets or a secondary CIDR. Do this anyway, because diversifying to smaller sizes will need more IPs.
5. **For capacity that must be there every night:** with the account team, buy **On-Demand Capacity Reservations** for the evening peak, or future-dated ODCRs for m8g.24xlarge in each AZ.

### Customer (batch-etl owner)
6. Find out which quota `batch-etl-asg` actually uses (On-Demand Standard vs. Spot, per its launch template) and **request an increase through Service Quotas**, sized for the nightly 22:00 run. Consider moving it out of the 22:00 slot or out of subnet 1b, where it competes with the web tier's peak.

### Customer (data/observability)
7. Fix the CloudTrail export pipeline or the analysis: **deduplicate by `requestID`**, not `eventID`. Otherwise every failure report is overstated about 3×.

### AWS account team
8. **Reissue the capacity snapshot keyed by AZ ID** (euw1-az1/euw1-az2/euw1-az3). Cover m8g.24xlarge and m8g.16xlarge (plus the alternative types from step 1) for 19:00–04:00 UTC. Explain why the snapshot showed 240 free m8g.16xlarge when this account's euw1-az1 was returning ICE.
9. Advise on and support **capacity reservations** for the m8g.24xlarge evening peak, and say whether more m8g capacity is coming to eu-west-1.
10. Approve the batch quota increase once it's filed (step 6).

### Recommendation on the rollout
Keep migrating. Before moving **more web capacity** onto m8g.24xlarge, complete steps 1–4 first, so the web fleet doesn't depend on a single pool that runs out in both AZs every night. Then add more as the account team's AZ-ID capacity data (step 8) and any reservations (step 9) come in. Pausing or rolling back wouldn't fix causes 3 and 4 at all. For causes 1 and 2, diversifying instance types and AZs fixes the underlying problem directly.
