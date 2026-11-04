# Why web-tier launches fail again at night (eu-west-1, `mall-web-asg`)

## 1. Verdict

The failures came back because the customer released the capacity reservations that had been covering night peak. Their own `platform-admin/ops` role cancelled both 100-instance m8g.24xlarge On-Demand Capacity Reservations on **2030-04-03 at 10:00–10:01 UTC**. Every night from that evening on has shown `InsufficientInstanceCapacity` (ICE). This is not a Graviton problem and not a quota problem. Keep the rollout going: put back part of the reservation now, widen the fallback, and set a rollback rule before any reservation is released again.

## 2. Evidence

All numbers come from `classify.py`. 1,741 raw records went in; 157 duplicates were removed; 1,580 RunInstances calls remain, all from the Auto Scaling service role for `mall-web-asg`. Result: 1,260 instances launched and 320 failed. The only error code is `Server.InsufficientInstanceCapacity`. There were 0 quota errors and 0 other errors.

Reservation events:

| Time (UTC) | Event | AZ (AZ ID) | Type | Count | By |
|---|---|---|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation `cr-0a1a…` | eu-west-1a (euw1-az1) | m8g.24xlarge | 100 | platform-admin/ops |
| 2030-03-31 09:02 | CreateCapacityReservation `cr-0b2b…` | eu-west-1b (euw1-az2) | m8g.24xlarge | 100 | platform-admin/ops |
| **2030-04-03 10:00** | **CancelCapacityReservation** `cr-0a1a…` | eu-west-1a | m8g.24xlarge | 100 | platform-admin/ops |
| **2030-04-03 10:01** | **CancelCapacityReservation** `cr-0b2b…` | eu-west-1b | m8g.24xlarge | 100 | platform-admin/ops |

Per night, per AZ:

| Nights | m8g.24xlarge launched | m8g.24xlarge ICE | m8g.16xlarge (fallback) launched |
|---|---|---|---|
| 04-01, 04-02 (reservation in place) | 110 in 1a / 110 in 1b | 0 / 0 | 5 / 5 |
| 04-03 to 04-06 (after cancel, all 4 nights the same) | 60 / 60 | **45 / 35** | 40 / 40 |

What this shows:
- With the reservations in place, about 100 of the 110 large instances per AZ were covered by reserved capacity. Once released, only **60 per AZ** are available from the shared pool at night peak. Other customers' demand now uses the capacity this account gave back.
- ICE hits **both AZs** in the same hours: **20:00–01:59** (hours as `classify.py` reports them, run at UTC+0). In 1a, 180 failures spread over those hours as 28/23/30/34/41/24. In 1b, 140 failures as 24/31/22/17/21/25. The error message's advice to "choose a different AZ" does not help between 1a and 1b.
- The m8g.16xlarge fallback works: 340 launches, **0 failures**. But it did not fully make up the gap. Each night 80 large launches fail, while only 70 extra 16xlarge launch, and a 16xlarge has 64 vCPU against 96. Per AZ, peak capacity fell from about 10,880 vCPU (nights 1–2) to about 8,320 vCPU.
- `capacity_vs_snapshot_flags`: none. **NOT RUN against a snapshot**, because no capacity snapshot from the account team was provided. Nothing here points to an account-level problem beyond the released reservation.

## 3. Causes, actions and owners

| # | Cause | Type / AZ | Hours (UTC) | Instances (failures) | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|
| 1 | Reservations released on 04-03 10:00 | m8g.24xlarge, eu-west-1a (euw1-az1) | 20:00–01:59 nightly | 180 (45/night × 4) | Night peak was relying on reserved capacity. The shared pool gives about 60 per AZ. | Re-reserve m8g.24xlarge in 1a | Customer platform team (has `platform-admin`), with the AWS account team for sizing and timing |
| 1 | Same | m8g.24xlarge, eu-west-1b (euw1-az2) | 20:00–01:59 nightly | 140 (35/night × 4) | Same | Re-reserve m8g.24xlarge in 1b | Same |
| 2 | Fallback too narrow and doesn't fully replace lost capacity | ASG mixed-instances policy | Same | 80 failures/night against 70 extra fallback launches | Only one fallback type in two AZs. Each 16xl gives ⅔ of the vCPU. | Add more same-generation Arm64 types (e.g. m8g.12xlarge, c8g/r8g in large sizes if the app's memory profile allows). Use weighted capacity (vCPU-based) so 16xl counts as ⅔. Use a price-capacity-optimized allocation strategy. Consider a third AZ (eu-west-1c) if the network design allows. | Customer platform team |
| — | Quota | — | — | 0 | No quota errors | **Do not** request a quota increase. It would not fix ICE. | — |

## 4. What to do now (next 24 hours)

1. **Re-reserve m8g.24xlarge before tonight's 20:00 UTC peak.** Owner: customer platform team. Request it in batches. `simulate_split.py` with the observed per-night shortfall (1a: 45, 1b: 35):
   - Batch 1: 40 per AZ closes 1b; 1a still needs 5.
   - Batch 2: +20 per AZ (60 per AZ in total) closes both AZs.
   - Batch 3: +40 per AZ (100 per AZ, the original size) restores nights 1–2 and gives headroom for growth.

   The minimum is 60 per AZ; 100 per AZ is what worked. If a request itself returns ICE, retry in smaller batches and escalate to the account team.
2. **Widen the ASG fallback** (cause 2). Owner: customer platform team. Do this today so that tonight's leftover gap lands on other Arm64 types instead of failing.
3. **Ask the account team (TAM)** for a capacity outlook for m8g.24xlarge in euw1-az1 and euw1-az2 at 20:00–02:00 UTC. Ask whether a Future-dated Capacity Reservation is possible for the remaining rollout. Owner: customer to request, AWS account team to answer.
4. **Watch tonight.** Owner: customer platform team. Re-run `classify.py` tomorrow morning. Success means 0 ICE for m8g.24xlarge in both AZs and m8g.16xlarge back near 5 per AZ. A daily page was generated as `rollout-report.html`.

Pausing the rollout is **not** needed. Consider it only if the reservation can't be obtained *and* the wider fallback still leaves unmet desired capacity at peak. Even then, pause adding new Graviton capacity; don't roll back the instances already running.

## 5. What to do differently next time

| Change | Owner |
|---|---|
| Agree a written **release condition before** cancelling any reservation. For example, release only after N consecutive peak nights with on-demand ICE = 0 while running *unreserved* at the same size. Release in steps (e.g. 100 → 60 → 30 → 0, one step per peak night), never all at once. Also agree a **rollback trigger**: any ICE at peak means re-reserve the last step. | Customer platform team, with the account team signing off on timing |
| Never release capacity just before a known peak (here 10:00 UTC, 10 hours before the night peak). Release after peak, during daytime, and watch the next night. | Customer platform team |
| Before releasing, ask the account team for a capacity check of the exact type × AZ ID × hour. | Customer → AWS account team |
| Ship the ASG with a wide, weighted mixed-instances policy from day one. Don't depend on one fallback size. | Customer platform team |
| Add a CloudWatch / EventBridge alarm on ASG launch failures with `InsufficientInstanceCapacity` for this group, so ICE is seen the same night. | Customer platform team |

## 6. What the data cannot show

- **True demand / desired capacity.** CloudTrail only shows launch attempts. It can't show whether the ASG reached its desired capacity, or how much the web tier was actually short (user impact). Get ASG activity history and desired-vs-in-service metrics.
- **Whether the cancellation was intentional cost cleanup or a mistake.** CloudTrail shows who (`platform-admin/ops`) and when, not why. Ask the platform team.
- **Shared-pool depth.** There is no capacity snapshot, so the snapshot cross-check is **NOT RUN**. The "~60 per AZ available" figure comes from what succeeded, not from a measured pool size. Ask the account team for a snapshot covering 2030-04-03 to 04-06, 20:00–02:00 UTC.
- **Local time.** Hours are UTC (`--tz-offset 0`). If the customer works in Irish time (UTC+1 in April), the failure window is 21:00–02:59 local.
- **Data window.** The data runs from 2030-04-01 19:00 to 2030-04-07 05:00 UTC. Launches outside that window, and other regions or accounts, are not covered. Nothing was changed in the account; this analysis was read-only.
