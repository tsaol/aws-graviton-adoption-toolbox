# Why the m8g web tier launch failures came back, and what to do

## Short answer

The first two nights after the Graviton rollout worked only because **On-Demand Capacity Reservations (ODCRs) were holding m8g.24xlarge capacity** for the web tier. Your own `platform-admin/ops` role **cancelled both reservations on 2030-04-03 at 10:00–10:01 UTC**. That evening the Auto Scaling group went back to ordinary On-Demand capacity, and at the evening peak it started getting `InsufficientInstanceCapacity` (ICE) for m8g.24xlarge again in both AZs. Nothing changed on the AWS side and nothing changed in the ASG. The capacity guarantee went away.

## Evidence (CloudTrail, eu-west-1, account 111122223333)

Note on data: the export contains 1,741 lines but only 1,584 unique `eventID`s. 157 lines are exact duplicates (155 RunInstances, 2 CreateCapacityReservation). All numbers below count each event once.

**Reservation lifecycle** (all made by `assumed-role/platform-admin/ops`):

| Time (UTC) | Action | Reservation | AZ (AZ ID) | Type / count |
|---|---|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation | cr-0a1a1a1a1a1a1a1a1 | eu-west-1a (euw1-az1) | m8g.24xlarge × 100 |
| 2030-03-31 09:02 | CreateCapacityReservation | cr-0b2b2b2b2b2b2b2b2 | eu-west-1b (euw1-az2) | m8g.24xlarge × 100 |
| 2030-04-03 10:00 | **CancelCapacityReservation** | cr-0a1a1a1a1a1a1a1a1 | eu-west-1a (euw1-az1) | — |
| 2030-04-03 10:01 | **CancelCapacityReservation** | cr-0b2b2b2b2b2b2b2b2 | eu-west-1b (euw1-az2) | — |

**RunInstances by `mall-web-asg`, one row per night (about 19:00–05:00 UTC):**

| Night of | Reservations active? | m8g.24xlarge OK | m8g.24xlarge ICE | m8g.16xlarge (fallback) OK | First ICE |
|---|---|---|---|---|---|
| 04-01 | yes | 220 (110 a / 110 b) | **0** | 10 | — |
| 04-02 | yes | 220 (110 / 110) | **0** | 10 | — |
| 04-03 | **no (cancelled that morning)** | 120 (60 / 60) | **80** (45 a / 35 b) | 80 | 20:07:47 |
| 04-04 | no | 120 | 80 (45 / 35) | 80 | 20:05:03 |
| 04-05 | no | 120 | 80 (45 / 35) | 80 | 20:01:31 |
| 04-06 | no | 120 | 80 (45 / 35) | 80 | 20:07:40 |

What the numbers show:
- Failures start the first evening after the cancellation and repeat the same way every night. About 40% of m8g.24xlarge attempts fail.
- ICE happens only between about 20:00 and 02:00 UTC, which is the regional evening peak. Every error has the same message: "We currently do not have sufficient m8g.24xlarge capacity in the Availability Zone you requested". It occurs in **both** AZs, so a single AZ switch will not fix it.
- **m8g.16xlarge never failed.** The fallback works, but it is a smaller instance. Rough compute estimate from successful launches (96 vs 64 vCPU): about 21.8k vCPU per night with the reservations, about 16.6k vCPU per night without them. That is roughly 24% less web-tier capacity at peak, unless the ASG uses instance weights.
- The ASG often retries m8g.24xlarge in the same AZ within a minute of an ICE, so failed attempts pile up before it falls back.
- The ASG only uses two subnets: subnet-0aaa1111 (eu-west-1a / euw1-az1) and subnet-0bbb2222 (eu-west-1b / euw1-az2). The region's third AZ is not used.

Limits of this analysis: the export has no TerminateInstances events and no `capacityReservationId` on RunInstances responses. So I can't prove which launches landed inside the reservations or measure peak concurrent usage. The link to the reservations is based on timing, but it is exact and repeats every night. The customer can confirm it with the ODCR CloudWatch metrics (`UsedInstanceCount` / `InstanceUtilization`) for the two reservations on 04-01 and 04-02.

## What to do now

| # | Action | Owner |
|---|---|---|
| 1 | **Re-create ODCRs for m8g.24xlarge in euw1-az1 and euw1-az2.** Do it now, during the day (off-peak), when capacity can be obtained. Leave them open-ended (no end date) or set the end date past the peak season. Size them to peak concurrent instances: at least the previous 100 per AZ. The ICE shortfall above (35–45 launches per AZ per night) is a minimum, not the target. If a reservation can't be fully filled right away, create a smaller one and grow it, or request a future-dated reservation. | Customer (platform team that owns `platform-admin`). AWS account team / TAM helps if the request can't be fulfilled. |
| 2 | Make the ASG use the reservations deliberately: set the On-Demand capacity reservation preference to **capacity-reservations-first** (or target them through a resource group). Then it fills reserved capacity before trying open On-Demand. | Customer (web-tier / ASG owner) |
| 3 | Set **instance weights** in the mixed instances policy (for example m8g.24xlarge = 3, m8g.16xlarge = 2, or weight by vCPU). Then a fallback launch adds the right amount of capacity and peak compute doesn't quietly drop by about 24%. | Customer (web-tier owner) |
| 4 | Broaden the fallback list with more Graviton sizes and families the app is validated on (for example m8g.48xlarge, m7g.16xlarge, c8g/r8g equivalents), so a single-pool ICE doesn't stall scale-out. | Customer (web-tier owner + app team for validation) |
| 5 | Add a subnet in the third eu-west-1 AZ to the ASG, after checking that m8g is offered there (`describe-instance-type-offerings --location-type availability-zone-id`). Spreading across more AZs reduces the impact of a capacity shortage in one AZ. | Customer (network/platform team) |
| 6 | Until 1–5 are done, pre-scale before 20:00 UTC with a scheduled action. Instances launched in the afternoon get capacity more easily than instances launched in the peak. | Customer (web-tier owner) |

## What to do differently next time

| # | Practice | Owner |
|---|---|---|
| 1 | **Treat capacity reservations as part of the steady-state architecture, not as release scaffolding.** If a workload needs a specific large instance type at a predictable daily peak, keep the reservation for as long as that peak exists. Reserving only for the rollout window and then releasing it is exactly what caused this. | Customer (platform/capacity owner) |
| 2 | Put `CancelCapacityReservation` / `ModifyCapacityReservation` under change control. Require a utilization check first: ODCR `InstanceUtilization` / `UsedInstanceCount` over at least a full weekly peak cycle. Add an EventBridge rule on CloudTrail that alerts the web-tier owners when a reservation they depend on is cancelled or expires. Tag reservations with the owning service. | Customer (platform team + cloud governance) |
| 3 | Add a CloudWatch alarm on ASG failed launch activities / ICE, and on reservation utilization near 100%. Then a capacity gap shows up before customers notice. | Customer (SRE/observability) |
| 4 | For future migrations or peak events, plan capacity with the AWS account team ahead of time. Use future-dated ODCRs for known peaks, and include the target instance types per **AZ ID** (euw1-az1 / euw1-az2, not AZ names, which map differently per account). Note that Savings Plans and Reserved Instances alone are billing discounts. Only zonal RIs or ODCRs actually reserve capacity. | Customer drives it; AWS account team / TAM supports it |
| 5 | Design the launch configuration to tolerate ICE: several instance types with weights, at least three AZs, and an allocation strategy that falls back quickly. The shortage comes back whenever reserved capacity is missing, so the ASG design is the long-term safety net. | Customer (web-tier owner) |

**Responsibility split:** AWS owns the physical capacity in each AZ, and an ICE at the regional peak is not a fault in the customer's account. The customer owns the reservations, the ASG design, and change control. Here the trigger was a customer-side change, cancelling the two reservations on 2030-04-03. Steps 1–6 under "now" and all items under "next time" are customer actions. AWS (account team / TAM) supports with capacity planning and with fulfilling large or future-dated reservations.
