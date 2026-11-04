# Why the web tier's night launches fail again (eu-west-1)

## Verdict

Keep the Graviton rollout going. The failures came back because **the two m8g.24xlarge capacity reservations that covered the first two nights were cancelled on 2030-04-03 at 10:00 UTC**. From that night on, the web tier has had to get its night peak from the shared On-Demand pool, and in both AZs that pool runs out of m8g.24xlarge at night. Every failure is `InsufficientInstanceCapacity`, which means AWS had no capacity left for that type. It is not a quota problem and not an Arm/Graviton problem, and m8g.16xlarge has not failed once. The fix is to get reserved capacity back for the night peak and to lean harder on the fallback types.

## Evidence (from `classify.py` on events.jsonl.gz)

- 5,219 raw records. 464 exact duplicates were removed, then 3,171 repeated rows for the same request were collapsed, leaving **1,584 unique requests**: 1,580 launch calls and 4 reservation events.
- Launch results: **1,260 instances launched and 320 failed on capacity** (`Server.InsufficientInstanceCapacity`). There were no quota errors and no other error codes.
- Reservation timeline (all made by `assumed-role/platform-admin/ops` in account 111122223333):

| Time (UTC) | Event | Reservation | Type / AZ | Count |
|---|---|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation | cr-0a1a1a1a1a1a1a1a1 | m8g.24xlarge / eu-west-1a (euw1-az1) | 100 |
| 2030-03-31 09:02 | CreateCapacityReservation | cr-0b2b2b2b2b2b2b2b2 | m8g.24xlarge / eu-west-1b (euw1-az2) | 100 |
| **2030-04-03 10:00** | **CancelCapacityReservation** | cr-0a1a1a1a1a1a1a1a1 | m8g.24xlarge / eu-west-1a | 100 |
| **2030-04-03 10:01** | **CancelCapacityReservation** | cr-0b2b2b2b2b2b2b2b2 | m8g.24xlarge / eu-west-1b | 100 |

- Instances per night and AZ (a night runs 18:00–08:00 UTC and is labelled by its start date):

| Night | AZ | m8g.24xlarge launched | m8g.24xlarge capacity failures | m8g.16xlarge launched |
|---|---|---|---|---|
| 04-01, 04-02 (reserved) | 1a | 110 | 0 | 5 |
| 04-01, 04-02 (reserved) | 1b | 110 | 0 | 5 |
| 04-03 to 04-06 (each night, after the cancel) | 1a | 60 | **45** | 40 |
| 04-03 to 04-06 (each night, after the cancel) | 1b | 60 | **35** | 40 |

  The pattern changes on the first night after the cancel and then repeats exactly every night. Without the reservation, only about 60 m8g.24xlarge per AZ can be launched at night.
- Failure hours: **20:00–01:59 UTC**, which is 21:00–02:59 Irish local time (UTC+1 in April). The failures are spread evenly over that window in both AZs.
- `capacity_vs_snapshot_flags`: none. **The check did not run.** No account-team capacity snapshot was provided, so the tool had nothing to compare against. It does not mean free capacity was confirmed.

## Causes

| # | Cause | Type / AZ | Hours (UTC) | Instances (script) | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|
| 1 | Reservations released before the On-Demand pool could carry the night peak | m8g.24xlarge, eu-west-1a (euw1-az1) | 20:00–02:00, nights 04-03 to 04-06 | 180 capacity failures (45 per night) | The cancelled 100-instance reservation was what made the first two nights work. Without it, the shared pool has about 60 per night here. | Re-reserve m8g.24xlarge in this AZ (at least 45, or 100 like before) | Customer platform team (owns the platform-admin role), with the AWS account team / TAM to confirm the capacity |
| 2 | Same cause | m8g.24xlarge, eu-west-1b (euw1-az2) | 20:00–02:00, nights 04-03 to 04-06 | 140 capacity failures (35 per night) | Same: about 60 per night from the shared pool | Re-reserve m8g.24xlarge in this AZ (at least 35, or 100 like before) | Customer platform team, with the account team |
| 3 | The fallback type covers only part of the shortfall | m8g.16xlarge, both AZs | same nights | 40 per AZ per night launched, 0 failures | The fallback works and has room, but each AZ still ends up about 2,560 vCPU short at night compared with the reserved nights.* | Give the fallback more room and add more same-architecture types (see below) | Customer platform team |

\*This is approximate, using standard sizes (m8g.24xlarge = 96 vCPU, m8g.16xlarge = 64 vCPU). Reserved nights: 110 × 96 + 5 × 64 = 10,880 vCPU per AZ. Nights after the cancel: 60 × 96 + 40 × 64 = 8,320 vCPU per AZ. CloudTrail does not show whether the failed requests were retried, so check this against CUR.

Not causes: quota (no `VcpuLimitExceeded` or `InstanceLimitExceeded`, so **don't** ask for a quota increase), and subnet or launch template configuration (no other error codes).

## What to do now (next 24 hours)

1. **Get capacity back for tonight.** Create On-Demand Capacity Reservations for m8g.24xlarge in eu-west-1a and eu-west-1b, sized to cover the night peak: at least 45 in 1a and 35 in 1b, or 100 per AZ as before. Make them `open` or target the web tier's launch template, and create them early in the day, well before 20:00 UTC. If a request is only partly filled, take what is available and ask the account team for the rest. *Owner: customer platform team. Escalation: the AWS account team / TAM, if a reservation can't be fully filled.*
2. **Widen the fallback in the Auto Scaling group.** Keep m8g.24xlarge first. Increase the share m8g.16xlarge is allowed to take (weights or overrides) so that ICE on the primary type is absorbed by the fallback. Add more Graviton types of similar size, for example m8g.12xlarge and m7g.16xlarge (also m7g.12xlarge, c8g/r8g if the workload fits), and use the `capacity-optimized` or `price-capacity-optimized` allocation strategy. All of these are arm64, so the AMI doesn't change. *Owner: customer platform team.*
3. **Start scale-out earlier.** The failures start at 20:00 UTC. Scheduled scaling or warm pools that bring capacity up before then make the evening ramp less exposed. *Owner: customer platform / application team.*
4. **Don't pause the rollout or roll back to x86 as the first move.** Pausing only makes sense if steps 1–2 can't close the gap by tonight and the web tier is losing user-facing capacity. In that case, a temporary x86 fallback type in the same group is better than a full rollback.

## What to do differently next time

- **Before releasing a reservation, agree on a rollback condition.** For example: "Release only after N nights at peak with the reservation unused, and with the account team confirming that the On-Demand pool can carry the peak. If ICE appears, re-reserve the same day." Here the reservation was released after only two good nights, and those nights were good *because of* the reservation. *Owner: customer platform team and the account team, agreed before the release.*
- **Release in steps, not all at once.** For example, reduce from 100 to 75 to 50 and watch a night at each step. Don't cancel 100% in both AZs within one minute. *Owner: customer platform team.*
- **Run the pre-rollout check** (`precheck.py`: offerings, fallback, quota, reservations vs peak per AZ, free capacity at peak, lead time, rollback agreed before release) before the next rollout or reservation change. *Owner: customer platform team, with the account team supplying the capacity snapshot.*
- **Set up the fallback mix before go-live.** Several same-architecture types and a capacity-optimized strategy should be in place on day one, not added after an incident. *Owner: customer platform team.*
- **Alert on ICE.** Alert on Auto Scaling launch failures and CloudTrail `InsufficientInstanceCapacity` per type and AZ, so that a regression is seen on the first night. *Owner: customer platform / SRE team.*

## What the data cannot show, and what to ask for

- **No CUR was provided (NOT RUN).** I can't tell how many instances were actually running at peak, or whether the web tier was short on capacity or just retried and caught up. Provide hourly CUR to confirm the real shortfall.
- **No capacity snapshot from the account team (NOT RUN).** I can't confirm how deep the shared m8g.24xlarge pool is at night, so the "about 60 per AZ" figure is an inference from the successful launches. Ask the TAM for free m8g.24xlarge / m8g.16xlarge capacity in euw1-az1 and euw1-az2 between 20:00 and 02:00 UTC, and whether a 100-per-AZ reservation can be filled now.
- **CloudTrail doesn't record why the reservations were cancelled.** Ask the platform team who triggered it (`platform-admin/ops`) and whether it was a planned cost-saving step.
- **Not run:** `simulate_split.py` (no batch dates or sizes from the account team yet; run it once they offer batches, with gaps of 45 in 1a and 35 in 1b as the minimum), `precheck.py` (no spec or offerings data), and the daily and weekly reports.
- Times are UTC. The tool's night window of 18:00–08:00 was applied in UTC, not local time.
