# Why web-tier launches fail again at night (eu-west-1, mall-web-asg)

## Short answer

The Graviton move did not fix the capacity problem. The two capacity reservations did. On 2030-03-31 `platform-admin/ops` created two On-Demand Capacity Reservations (ODCRs): 100 × m8g.24xlarge in eu-west-1a and 100 × m8g.24xlarge in eu-west-1b. Both nights while they existed were clean. The same role **cancelled both reservations on 2030-04-03 at 10:00–10:01 UTC**, the morning after the second clean night. The `InsufficientInstanceCapacity` (ICE) errors came back that evening at 20:07 UTC and have recurred every night since.

The ASG's launch requests never changed. All of them came from the same Auto Scaling service role, with the same subnets and instance types, and none of them targeted a reservation. The only change in the account was the cancellation. Without the reservations, the ASG competes for m8g.24xlarge capacity in the shared On-Demand pool during the evening peak, and there isn't enough of it in either AZ.

## Evidence (from events.jsonl.gz)

| Time (UTC) | Event |
|---|---|
| 03-31 09:00 / 09:02 | `CreateCapacityReservation` cr-0a1a1a1a1a1a1a1a1 (eu-west-1a = **euw1-az1**) and cr-0b2b2b2b2b2b2b2b2 (eu-west-1b = **euw1-az2**), 100 × m8g.24xlarge each |
| Night 04-01→02 | 742 m8g.24xlarge launches, **0 ICE** |
| Night 04-02→03 | 709 m8g.24xlarge launches, **0 ICE** |
| 04-03 10:00 / 10:01 | `CancelCapacityReservation` for both, by `assumed-role/platform-admin/ops` |
| Night 04-03→04 | 258 ICE (first at 20:07:47 in eu-west-1a) |
| Night 04-04→05 | 246 ICE |
| Night 04-05→06 | 277 ICE |
| Night 04-06→07 | 261 ICE |

How the failures look:
- **Every failure is m8g.24xlarge.** There were 1,042 ICE errors in total: 574 in 1a and 468 in 1b. None of the 1,500+ m8g.16xlarge launches failed.
- **Both AZs fail at the same time**, with about 35–40% of 24xlarge requests rejected in each. This is not one bad AZ, and moving traffic between 1a and 1b won't help. The ASG uses only these two AZs. eu-west-1 has a third AZ (euw1-az3), which the ASG doesn't use.
- **The failures happen at the same time every night, about 20:00 to 02:00 UTC.** That is the regional demand peak. 19:00–20:00 and 02:00–05:00 launch cleanly.
- **The fallback works, but only partly and slowly.** After a 24xlarge ICE, the next 16xlarge launch in the same AZ comes a median of about 7 minutes later, and up to about 66 minutes later. Over the same nights, 16xlarge launches went from about 35 a night to about 250–270. Each 16xlarge has two-thirds of the vCPU of a 24xlarge (64 vs 96), so the tier is short on capacity during the peak even when launches "succeed".
- None of the RunInstances calls has a `capacityReservationSpecification`. The reservations were *open* and were consumed automatically. That is why cancelling them changed behaviour without anyone touching the ASG or launch template.

Limits of this data: the export has no TerminateInstances or DescribeCapacityReservations events. I can't calculate peak concurrent instance count, so I can't say from this file alone whether 100 per AZ was enough. Size the replacement reservations from the ASG's peak InService metric, not from the old number.

## What to do now (before tonight's 19:00 UTC ramp)

| # | Action | Owner |
|---|---|---|
| 1 | **Recreate m8g.24xlarge ODCRs in euw1-az1 and euw1-az2**, sized to the measured nightly peak per AZ plus headroom. Make them *open* so the ASG uses them with no other change. Create them **now, during the day**: ODCR creation itself can fail with ICE, and daytime is when capacity is free. If you can't get the full count, take what you can and retry in steps. Use no end date, or an end date well past the busy season. | Customer, platform team (`platform-admin`, the role that cancelled them) |
| 2 | **Escalate to AWS through the account team / TAM.** Share the forecast (count × m8g.24xlarge, euw1-az1/az2, 19:00–05:00 UTC) and ask for help getting the ODCRs filled. Use **AZ IDs**, not AZ names, when you talk to AWS. | Customer opens it; AWS account team / EC2 capacity owns the response |
| 3 | **Make the fallback carry the full load.** In the ASG mixed-instances policy, set `WeightedCapacity` by vCPU (24xlarge = 3, 16xlarge = 2, or similar) so that 16xlarge launches count as less capacity and the ASG launches enough of them. Add more Graviton options of similar size (e.g. m8g.48xlarge, c8g/r8g.24xlarge, m7g.16xlarge/m7g.metal), or use attribute-based instance selection. Use the `prioritized` allocation strategy with "use capacity reservations first". | Customer, application / web-tier team |
| 4 | **Add a third AZ (euw1-az3) subnet to the ASG.** The ICE message itself says capacity may exist in another AZ. | Customer, network / platform team |
| 5 | **Pre-scale before the peak.** Add a scheduled action or warm pool that brings the tier to its nightly peak by about 19:30 UTC, before contention starts around 20:00. Don't scale reactively into the worst hour. | Customer, application / web-tier team |

Cost of item 1: an ODCR is billed at the On-Demand rate whether or not instances run in it. Savings Plans apply to ODCR usage, so cover the reserved baseline with a Compute or EC2 Instance Savings Plan. That cost is the price of not having ICE at peak. (Customer FinOps.)

## What to do differently next time

| Practice | Owner |
|---|---|
| **Don't release capacity reservations when a rollout ends.** Treat cancelling an ODCR as a production change: it needs a ticket, an approval from the web-tier owner, and evidence that peak-hour launches succeed without it (for example, several nights with the ODCR in place but unused, or a test launch at peak). Here the reservations were cancelled after just two nights, with nothing to show they weren't needed. | Customer, platform team plus change management |
| **Separate the instance-type migration from the capacity plan.** Moving to Graviton changed which pool the tier draws from. It didn't guarantee that pool has room. For every new primary type, plan a reservation and an equal-capacity fallback ahead of time. | Customer, architecture / platform team |
| **Alert on ICE.** Use an EventBridge rule on ASG "EC2 Instance Launch Unsuccessful" or a CloudTrail `InsufficientInstanceCapacity` metric filter, and page when the error appears. That would have flagged 04-03 20:07 straight away, not days later. | Customer, SRE / operations |
| **Share capacity forecasts before large changes and the busy season**, giving instance types, AZ IDs and time windows. | Customer, with the AWS account team (AWS owns the capacity follow-up) |
| **Keep at least three AZs and several instance types** in the ASG as the default, so no single type in a single AZ is a single point of failure. | Customer, platform team |
