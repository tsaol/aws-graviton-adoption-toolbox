# Why web-tier launches fail again at night (eu-west-1, `mall-web-asg`)

## Verdict

The failures came back because the two m8g.24xlarge capacity reservations were **cancelled on 2030-04-03 at 10:00 UTC**. That was the morning after the two good nights. The cancellations came from role `platform-admin/ops`: `cr-0a1a1a1a1a1a1a1a1` (100 × m8g.24xlarge, eu-west-1a) and `cr-0b2b2b2b2b2b2b2b2` (100 × m8g.24xlarge, eu-west-1b). From that evening on, every night has `InsufficientInstanceCapacity` (ICE) errors on m8g.24xlarge in both AZs. Before, those launches were covered by the reservations. Now they compete for the shared On-Demand pool at peak, and that pool is too small.

This is a capacity problem. It is not a quota or Graviton-compatibility problem. **Keep the rollout going.** Reserve capacity again for the peak gap, and rely on the m8g.16xlarge fallback, which is already absorbing part of the load. Do not request a quota increase: no quota errors were seen.

## Evidence (from `classify.py`, run on `events.jsonl.gz` with the subnet and AZ-ID maps)

- 5,219 raw records. Duplicate records removed: 464. Repeated rows for the same request collapsed: 3,171. That leaves **1,584 unique requests**: 1,580 launch calls and 4 reservation events.
- Instances: **1,260 launched, 320 failed with capacity errors.** Only one error code appears: `Server.InsufficientInstanceCapacity`. There are no quota errors and no configuration errors.

Reservation timeline:

| Time (UTC) | Event | Type / AZ | Count |
|---|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation | m8g.24xlarge / eu-west-1a (euw1-az1) | 100 |
| 2030-03-31 09:02 | CreateCapacityReservation | m8g.24xlarge / eu-west-1b (euw1-az2) | 100 |
| **2030-04-03 10:00** | **CancelCapacityReservation** | m8g.24xlarge / eu-west-1a | 100 |
| **2030-04-03 10:01** | **CancelCapacityReservation** | m8g.24xlarge / eu-west-1b | 100 |

Instances per AZ per night (the pattern is identical every night within each phase):

| Nights | m8g.24xlarge launched | m8g.24xlarge ICE (1a / 1b) | m8g.16xlarge launched (fallback) |
|---|---|---|---|
| 04-01, 04-02 (reservations active) | 110 per AZ | 0 / 0 | 5 per AZ |
| 04-03 to 04-06 (after cancellation) | 60 per AZ | **45 / 35** | 40 per AZ |

ICE hours are 20:00–01:59 UTC every night, which is the evening peak. eu-west-1a: 180 failed instances in total. eu-west-1b: 140.

**Meaning:** after the cancellation, the shared pool gives roughly 60 m8g.24xlarge per AZ at peak. That is about 50 fewer than the 110 per AZ that launched with the reservations. The fallback rose from 5 to 40 per AZ but does not fully replace the lost capacity. Per AZ per night, launched vCPU fell from about 10,880 to about 8,320 (the old figure is 110 × 96 + 5 × 64). The account team's capacity snapshot was not available, so the "capacity looks free but launches fail" check was **NOT RUN**. Still, the cancellation lines up exactly with the start of the errors, so the released reservation is the explanation.

## Causes and actions

| # | Cause | Type / AZ / hours | Instances (script) | Action | Owner |
|---|---|---|---|---|---|
| 1 | Reservations released while peak demand still needed them; the shared pool is short at peak | m8g.24xlarge, eu-west-1a and eu-west-1b, 20:00–02:00 UTC, every night since 04-03 | 180 ICE (1a), 140 ICE (1b) | **Now:** re-create On-Demand Capacity Reservations for m8g.24xlarge, at least ~50 per AZ (the lost peak capacity) and up to the original 100 per AZ for headroom. They can be time-bound, for example ending automatically after the peak season. Ask the account team to help confirm that capacity can be delivered, in batches if needed. | Customer platform team (owns the CR), with the AWS account team / TAM |
| 2 | Fallback list is too narrow to absorb the shortfall | m8g.16xlarge fallback, both AZs | 40 per AZ per night launched after 04-03 | **Now:** keep m8g.16xlarge as the fallback. Add more same-architecture (arm64) options to the ASG mixed-instances policy, for example other m8g sizes, m7g.24xlarge / m7g.16xlarge, or c8g / r8g where they fit. Use instance weights so smaller sizes count by vCPU, and use the `capacity-optimized` / price-capacity-optimized allocation strategy. | Customer platform team |
| 3 | No rollback condition before the release | Process | — | **Next time:** before cancelling or shrinking a reservation, agree on a rollback condition in writing. For example: "release only after N consecutive peak nights where the open pool alone covered the peak, with zero ICE", or reduce in steps (100 → 50 → 0 with a few peak nights between steps). Also agree that ICE on the first night after a release means immediate re-reservation. Run `precheck.py` (the reservation-vs-peak and rollback-agreed checks) before any release. | Customer platform team (owns the change); account team reviews the plan |

## What the data cannot show

- **How many instances were actually running at peak.** No CUR hourly usage was supplied, so we cannot tell whether ASG retries and fallback eventually met the desired capacity or whether the tier ran short. Ask the customer for CUR hourly usage (or ASG desired vs in-service metrics) for 04-01 to 04-07.
- **Whether the launches on nights 1–2 actually used the reservations.** CloudTrail RunInstances events here carry no reservation IDs (the reservations were open-matched). The timing strongly suggests they did.
- **Free capacity in the shared pool** at 20:00–02:00 UTC: there was no account-team capacity snapshot (`capacity_vs_snapshot_flags` check NOT RUN). Ask the account team for the free m8g.24xlarge / m8g.16xlarge snapshot for euw1-az1 and euw1-az2 during those hours, so the reservation size can be set with confidence.
- **Why the reservations were cancelled.** We see only that `platform-admin/ops` did it. The intent (cost saving, or a belief that the rollout was "done") needs to be confirmed with the customer.
- Hours are in UTC (no local-time offset was given).
- Pre-rollout check (`precheck.py`): NOT RUN (offerings, quota and snapshot files were not provided).

## Next 24 hours

1. **Customer platform team:** before tonight's 20:00 UTC peak, re-create m8g.24xlarge capacity reservations in eu-west-1a and eu-west-1b, at least ~50 per AZ, ideally 100 per AZ as before. Widen the ASG's arm64 fallback list.
2. **AWS account team / TAM:** help secure the reservation capacity in both AZs (euw1-az1, euw1-az2). Share the peak-hour free-capacity snapshot.
3. **Customer:** send CUR hourly usage or ASG metrics for 04-01 to 04-07 so we can confirm whether the tier ran below desired capacity.
4. **Tomorrow morning:** re-run `classify.py` on tonight's CloudTrail. Success means zero ICE on m8g.24xlarge. Only if ICE continues even with the reservations and wider fallback should pausing further Graviton scale-out be considered (not reverting what is already running).
5. **Customer platform team + account team:** write down the rollback condition (cause 3) before any future reservation release.
