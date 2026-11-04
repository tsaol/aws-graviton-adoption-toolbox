# Web tier launch failures (mall-web-asg, eu-west-1): why they came back and what to do

## Short answer

The first two nights worked because two **On-Demand Capacity Reservations (ODCRs)** were active. Each held 100 × m8g.24xlarge, one in each AZ. Those reservations were **cancelled on 2030-04-03 at 10:00–10:01 UTC**. The failures started that same evening (first one at 20:07 UTC). Since then, about 60 m8g.24xlarge per AZ per night launch from unreserved On-Demand capacity. Every launch beyond that gets `Server.InsufficientInstanceCapacity` (ICE), and the ASG falls back to m8g.16xlarge.

The Graviton rollout didn't stop working. The reservations were giving the web tier guaranteed capacity, and once they were released the tier went back to competing for unreserved m8g.24xlarge capacity at peak hours.

## Evidence (from CloudTrail)

Method: I counted the 1,584 unique events in `events.jsonl`. The export had 157 duplicate eventIDs, which I removed. A "night" runs from 19:00 to 05:00 UTC. All RunInstances calls come from the Auto Scaling service role for `mall-web-asg`. Each call requests 1 instance, and the subnets map to `subnet-0aaa1111` = eu-west-1a (euw1-az1) and `subnet-0bbb2222` = eu-west-1b (euw1-az2).

**Reservation timeline** (all made by `assumed-role/platform-admin/ops`):

| Time (UTC) | Event | Details |
|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation | cr-0a1a1a1a1a1a1a1a1, m8g.24xlarge × 100, eu-west-1a / euw1-az1 |
| 2030-03-31 09:02 | CreateCapacityReservation | cr-0b2b2b2b2b2b2b2b2, m8g.24xlarge × 100, eu-west-1b / euw1-az2 |
| 2030-04-03 10:00 | **CancelCapacityReservation** | cr-0a1a1a1a1a1a1a1a1 |
| 2030-04-03 10:01 | **CancelCapacityReservation** | cr-0b2b2b2b2b2b2b2b2 |

No replacement reservation was created after the cancellations.

**Launches per night, per AZ** (both AZs follow the same pattern):

| Night starting | AZ | m8g.24xlarge OK | m8g.24xlarge ICE | m8g.16xlarge (fallback) OK |
|---|---|---|---|---|
| 04-01 | 1a / 1b | 110 / 110 | 0 / 0 | 5 / 5 |
| 04-02 | 1a / 1b | 110 / 110 | 0 / 0 | 5 / 5 |
| 04-03 (after cancel) | 1a / 1b | 60 / 60 | 45 / 35 | 40 / 40 |
| 04-04 | 1a / 1b | 60 / 60 | 45 / 35 | 40 / 40 |
| 04-05 | 1a / 1b | 60 / 60 | 45 / 35 | 40 / 40 |
| 04-06 | 1a / 1b | 60 / 60 | 45 / 35 | 40 / 40 |

What this shows:
- **The change happens exactly at the cancellation.** No ICE errors before it, and ICE errors every night after it. The first error each night is at about 20:00–20:07, and they continue until about 01:55. That is the evening peak, when the ASG scales out and capacity in the AZ is tightest.
- **On the first two nights, the reservations carried the launches.** 110 m8g.24xlarge per AZ is the 100 reserved plus about 10 from the open pool. Without the reservations, the open pool gives only about 60 per AZ.
- **Every ICE error is for m8g.24xlarge.** Every m8g.16xlarge fallback launch succeeded, so the fallback is working. eu-west-1a (euw1-az1) is a little tighter than eu-west-1b (45 vs 35 errors per night).
- **The fallback doesn't make up the full shortfall.** Each AZ now ends a night with 100 instances (60 × 24xl + 40 × 16xl) instead of 115. That is about 8,320 vCPU per AZ instead of about 10,880, roughly 24% less compute at peak. If the ASG counts instances rather than weighting them by vCPU, every m8g.16xlarge also brings a third less capacity than the m8g.24xlarge it replaces. The customer should check ASG activity history and latency/5xx metrics for those hours to confirm the impact.
- The ICE message itself says capacity existed elsewhere ("by not specifying an Availability Zone ... or choosing a different Availability Zone"). The ASG only uses two of eu-west-1's three AZs.

Limits of this data: CloudTrail RunInstances responses don't include which reservation an instance used. The "100 reserved + 10 open" split is inferred from the counts and the timing, not read from a field. Reservation utilization can be confirmed in the ODCR CloudWatch metrics (`InstanceUtilization`, `UsedInstanceCount`) for 03-31 to 04-03. Also, the timestamps in the export are dated 2030, so I've reported them exactly as they appear.

## What to do now

| # | Action | Owner |
|---|---|---|
| 1 | **Re-create the ODCRs** for m8g.24xlarge in euw1-az1 and euw1-az2, sized for the peak. The first two nights used about 110 per AZ, so plan for at least 100–110 per AZ. Make them `open` so the ASG uses them without template changes, or target them from the launch template. Create them during the day, when capacity is easier to get: the originals were created at 09:00. If a full-size request is rejected, take what you can get and add more over time. ODCRs are billed whether used or not; a Compute Savings Plan or EC2 Instance Savings Plan applies to them. | Customer platform/infra team (the `platform-admin` role that created and cancelled them) |
| 2 | **Widen the ASG's capacity options while the reservations are being restored.** Add a third AZ subnet (eu-west-1c). Add more interchangeable instance types to the mixed-instances policy, such as m7g.24xlarge/m7g.16xlarge and c8g/r8g sizes if the workload allows. Set **instance weights by vCPU** so a 16xlarge fallback counts as two-thirds of a 24xlarge and the ASG launches enough of them. Use the `prioritized` allocation strategy (or `capacity-optimized-prioritized`), keeping m8g.24xlarge first. Alternatively, use attribute-based instance selection. | Customer web-tier / application team (owns `mall-web-asg` and the launch template) |
| 3 | **Ask the AWS account team (TAM/SA) for an m8g capacity outlook** in euw1-az1 and euw1-az2, and for help getting the ODCRs placed if creating them hits ICE. Give AZ IDs, not AZ names, because AZ names map differently in each account. | Customer raises it; AWS account team owns the answer and the follow-up |
| 4 | **Check what the peak hours have actually cost.** Look at ASG activity failures, time to reach desired capacity, and latency/errors from 20:00–02:00 UTC since 04-03. Use the result to decide how big the reservations need to be. | Customer web-tier / SRE team |

## What to do differently next time

| # | Practice | Owner |
|---|---|---|
| 1 | **Treat releasing capacity as a production change, not cleanup.** Before cancelling a reservation, look at its utilization during peak hours. A reservation that is used at night is covering demand the open pool may not meet. Release it in steps (for example 100 → 80 → 60) over several peak cycles while watching ICE rates, rather than cancelling it outright on a weekday morning. If the reservation is meant to be temporary, set an **end date after a hypercare period** that includes several real peaks, and put a review on the calendar before it expires. | Customer platform/infra team, with change-management approval from the web-tier owner |
| 2 | **Design for capacity from the start of a rollout.** A new or large instance size with a single fallback, spread over two AZs, has little slack. Every launch template should come with a diverse instance list, vCPU weights, and three AZs. | Customer web-tier / architecture team |
| 3 | **Alert on ICE on the first occurrence.** Use an EventBridge rule on RunInstances `Server.InsufficientInstanceCapacity` errors or failed ASG launch activities, and a CloudWatch alarm on ODCR `AvailableInstanceCount`/`InstanceUtilization`. With these in place, the problem shows up the first night, not after several. | Customer SRE / observability team |
| 4 | **Do capacity planning with AWS before big launches and before releasing reservations.** Share expected peak counts per AZ ID with the account team ahead of time. Consider future-dated capacity reservations for planned events. | Customer platform team together with the AWS account team |

## For the customer, in one line

Launches fail again because the m8g.24xlarge capacity reservations that made the first two nights work were cancelled on 04-03 at 10:00 UTC. To fix it now, recreate the reservations (platform team) and diversify the ASG (web-tier team). In future, only release reserved capacity in steps, after checking peak utilization, with alerting in place.
