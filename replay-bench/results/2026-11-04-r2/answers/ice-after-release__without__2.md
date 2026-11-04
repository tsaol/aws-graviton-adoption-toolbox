# Why the web tier's night-time launches started failing again

## Short answer
The first two nights only worked because of two **On-Demand Capacity Reservations (ODCRs)** for m8g.24xlarge, 100 instances each, one in eu-west-1a and one in eu-west-1b. On **2030-04-03 at 10:00–10:01 UTC** the `platform-admin/ops` role cancelled both of them. About ten hours later, at the next evening peak (first failure **2030-04-03 20:07:47 UTC**), m8g.24xlarge launches started failing with `InsufficientInstanceCapacity` (ICE) again, and that has repeated every night since.

The capacity problem was never fixed. It was covered by reservations for two nights, and then the reservations were released while demand was still there.

## Evidence (CloudTrail, eu-west-1, account 111122223333)

| Time (UTC) | Event | Who |
|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation `cr-0a1a1a1a1a1a1a1a1`, m8g.24xlarge ×100, eu-west-1a (euw1-az1) | platform-admin/ops |
| 2030-03-31 09:02 | CreateCapacityReservation `cr-0b2b2b2b2b2b2b2b2`, m8g.24xlarge ×100, eu-west-1b (euw1-az2) | platform-admin/ops |
| 2030-04-01 & 04-02 nights | 0 ICE errors; 1,451 m8g.24xlarge launches succeed | mall-web-asg |
| **2030-04-03 10:00 / 10:01** | **CancelCapacityReservation for both CRs** | **platform-admin/ops** |
| 2030-04-03 20:07 | First ICE for m8g.24xlarge | mall-web-asg |

Every RunInstances call comes from Auto Scaling for `mall-web-asg` (5,215 calls, one instance per call, subnets subnet-0aaa1111 for 1a and subnet-0bbb2222 for 1b). Per night, counted from 12:00 UTC to 12:00 UTC:

| Night of | 24xl OK | 24xl ICE (1a / 1b) | 16xl fallback OK | vCPU delivered vs. vCPU if all primaries had launched |
|---|---|---|---|---|
| 04-01 (CRs active) | 742 | 0 | 36 | — |
| 04-02 (CRs active) | 709 | 0 | 34 | — |
| 04-03 (CRs cancelled) | 392 | 258 (147 / 111) | 253 | 53,824 / 62,400 (−14%) |
| 04-04 | 380 | 246 (134 / 112) | 269 | 53,696 / 60,096 (−11%) |
| 04-05 | 399 | 277 (150 / 127) | 261 | 55,008 / 64,896 (−15%) |
| 04-06 | 431 | 261 (143 / 118) | 267 | 58,464 / 66,432 (−12%) |

Patterns in the data:
- **Time of day:** ICE happens only between about 20:00 and 02:00 UTC, which is the regional evening peak. Before 20:00 and after 02:00, m8g.24xlarge launches succeed.
- **Both AZs:** euw1-az1 and euw1-az2 are both affected, with 1a slightly worse. The ASG only uses these two AZs. Both are tight at the same time, so the "choose a different AZ" hint in the error message doesn't help here.
- **The fallback works but costs capacity:** no m8g.16xlarge launch failed. The number of fallback launches roughly matches the number of ICEs. But an m8g.16xlarge has 64 vCPU against 96 for an m8g.24xlarge, so each fallback gives only two thirds of an instance. Over the night the tier ends up about 11–15% short on compute, plus the delay of a failed attempt before each fallback. That is why users see a slow or undersized tier at peak.
- The fallback is the **same family and generation (m8g)**, so it shares the same tight capacity pool. The region has only had enough m8g.16xlarge headroom so far by luck; nothing guarantees it.

Caveat: the export contains no TerminateInstances events, so I can't reconstruct how many instances were running at the peak. Size any new reservation from the ASG's peak `GroupInServiceInstances` / desired capacity during 20:00–02:00 UTC, not from launch counts.

## What to do now

| # | Action | Owner |
|---|---|---|
| 1 | **Re-create m8g.24xlarge ODCRs in euw1-az1 and euw1-az2**, sized to the 20:00–02:00 UTC peak (100 per AZ worked before). Use open instance matching so the ASG uses them automatically. Create them during the day, when capacity is available, and check that the reservations actually reach `active` with the full count. | Customer platform team (owners of the `platform-admin/ops` role that cancelled them) |
| 2 | **Widen the ASG's instance options** with a mixed instances policy / attribute-based selection and capacity weights: m8g.24xl (weight 3), m8g.16xl (weight 2), plus other pools such as m7g.24xl/16xl, and c8g/r8g or x86 m7i if the AMI and app allow. Use the `capacity-optimized` / `prioritized` allocation strategy, so a fallback still gives the right amount of capacity and doesn't depend only on m8g. | Customer web-tier / application team |
| 3 | **Add the third AZ** (eu-west-1c) subnet to `mall-web-asg`, so that two tight AZs don't limit the whole tier. | Customer network/platform team |
| 4 | **Raise peak capacity with AWS**: tell the account team / TAM the expected m8g peak per **AZ ID** (euw1-az1, euw1-az2, not AZ names, which map differently in each account) so they can include it in regional capacity planning. | Customer TAM contact → AWS account team |
| 5 | Until the steps above are in place, **pre-scale the ASG with scheduled scaling before 20:00 UTC** (e.g. at 18:00–19:00, when m8g.24xlarge launches still succeed), so instances are already running when the pool runs out. | Customer web-tier / operations team |

## What to do differently next time

| Lesson | Owner |
|---|---|
| **Don't cancel reservations because the rollout "went fine."** Two quiet nights showed the reservations worked, not that the on-demand pool had room. Before cancelling, check the ASG's peak demand against what is available without reservations. | Customer platform team |
| **Release gradually:** cancel or shrink one AZ (or part of the count) at a time, watch a full 20:00–02:00 peak for ICE, then continue. Make this a change-review step for any CancelCapacityReservation / ModifyCapacityReservation on production instance types. | Customer platform team + change-management owner |
| **Give reservations an end date tied to a decision**, not an ad-hoc cancel. If capacity is only needed for a period, use future-dated ODCRs or end dates agreed with the app owner. For permanent baseline demand, keep the ODCR and cover the cost with Savings Plans. | Customer platform team + FinOps |
| **Monitor and alert on ICE:** EventBridge / CloudWatch metric filter on RunInstances `Server.InsufficientInstanceCapacity` for `mall-web-asg`, plus alarms on ODCR `AvailableInstanceCount`/utilization. The regression would then have been caught on 04-03 at 20:07, not days later. | Customer operations/SRE team |
| **Design fallbacks across capacity pools**, not just a smaller size of the same family, and set capacity weights so a fallback doesn't quietly shrink the tier. | Customer web-tier / application team |
| **Tell AWS about big instance-type migrations (like the Graviton move) in advance**, with per-AZ-ID peak numbers. | Customer TAM contact / AWS account team |
