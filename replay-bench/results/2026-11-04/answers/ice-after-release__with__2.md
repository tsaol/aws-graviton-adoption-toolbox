# Web tier (mall-web-asg, eu-west-1): why night launches fail again

## 1. Verdict

Keep the Graviton rollout going. The failures are not caused by Graviton, quota or the configuration. On **2030-04-03 at 10:00Z** the customer's `platform-admin/ops` role cancelled both m8g.24xlarge capacity reservations (100 per AZ). Those reservations were what made the first two nights work. Starting that evening, the night peak has to come from the shared On-Demand pool, and that pool cannot supply enough m8g.24xlarge in either AZ. The quickest fix is to reserve capacity again for the night peak. Until then, rely more on the m8g.16xlarge fallback, which has not failed once.

## 2. Evidence (from `scripts/classify.py`; outputs are in `./output/`)

- 1,741 records. **157 duplicates removed**, leaving 1,584 (1,580 launch calls and 6 reservation events).
- Instances: **1,260 launched, 320 refused with `Server.InsufficientInstanceCapacity`**. There are **no** quota errors (`VcpuLimitExceeded`/`InstanceLimitExceeded`) and no subnet or launch template errors.
- Reservation timeline (all calls by `assumed-role/platform-admin/ops`):

| Time (UTC) | Event | Reservation | Type / AZ | Count |
|---|---|---|---|---|
| 2030-03-31 09:00 | CreateCapacityReservation | cr-0a1a1a1a1a1a1a1a1 | m8g.24xlarge / eu-west-1a (euw1-az1) | 100 |
| 2030-03-31 09:02 | CreateCapacityReservation | cr-0b2b2b2b2b2b2b2b2 | m8g.24xlarge / eu-west-1b (euw1-az2) | 100 |
| **2030-04-03 10:00** | **CancelCapacityReservation** | cr-0a1a1a1a1a1a1a1a1 | m8g.24xlarge / eu-west-1a | 100 |
| **2030-04-03 10:01** | **CancelCapacityReservation** | cr-0b2b2b2b2b2b2b2b2 | m8g.24xlarge / eu-west-1b | 100 |

- Per night and AZ (the script's night is 18:00–08:00):

| Nights | AZ | m8g.24xlarge launched | m8g.24xlarge ICE | m8g.16xlarge launched |
|---|---|---|---|---|
| 04-01, 04-02 (reservations active) | 1a / 1b | 110 / 110 | 0 / 0 | 5 / 5 |
| 04-03 through 04-06 (after the cancel), every night | 1a | 60 | **45** | 40 |
| 04-03 through 04-06 (after the cancel), every night | 1b | 60 | **35** | 40 |

- Hours with failures: **20:00–01:59 UTC** (21:00–02:59 Irish Summer Time, UTC+1) in both AZs, on every night after the cancel. Over those four nights: 180 ICE in 1a and 140 in 1b.

The pattern is identical every night and starts on the first night after the release. Only the primary size fails, in both AZs. That matches the playbook pattern "capacity errors start right after a CancelCapacityReservation": the reserved capacity went back to the shared pool, and other customers now use it at the same peak hours.

## 3. Causes, actions and owners

| # | Cause | Type / AZ | Hours (UTC) | Instances (script) | Meaning | Action | Owner |
|---|---|---|---|---|---|---|---|
| 1 | Reservations released on 04-03 10:00Z | m8g.24xlarge / eu-west-1a (euw1-az1) | 20–02 nightly since 04-03 | 180 ICE (45/night) | Without the reservation, the shared pool is short at night peak | Reserve again: at least 45 in 1a (see batches below). Or reserve 100 again if the 110/night level is the target | Customer platform team (creates the ODCR); AWS account team / TAM (confirms it can be delivered) |
| 1 | Same | m8g.24xlarge / eu-west-1b (euw1-az2) | 20–02 nightly since 04-03 | 140 ICE (35/night) | Same | Reserve again: at least 35 in 1b | Same |
| 2 | Fallback is too small in the ASG's mix | m8g.16xlarge, both AZs | — | 0 failures. 40/night/AZ launched (up from 5) | The fallback works but does not make up for the shortfall | Allow more m8g.16xlarge in the mixed instances policy. Add more same-generation Arm sizes (for example m8g.12xlarge, or m7g.16xlarge/24xlarge). Use capacity-optimized prioritized allocation. Right-size the ASG target by vCPU or weight, not by instance count | Customer platform team |
| — | Quota | — | — | 0 | Not a cause | **No quota increase.** It would not fix ICE | — |

**Batch plan** (`scripts/simulate_split.py`, using the measured night shortfall as the peak gap: 45 in 1a, 35 in 1b):
- Batch 1, 40 per AZ: **closes eu-west-1b**. 5 still missing in eu-west-1a.
- Batch 2, +20 per AZ (60 total): **closes eu-west-1a**.
- Batch 3, +40 per AZ (100 total): restores the level of nights 1 and 2. Only needed if they want the 24xlarge mix back exactly as it was.
- Delivery dates are for the account team to confirm. The spec leaves them blank.

## 4. What the data cannot show, and what to ask the account team for

- **Capacity snapshot check: NOT RUN.** No account-team snapshot was provided, so `capacity_vs_snapshot_flags` is empty only because there was nothing to compare against. Ask the TAM for free m8g.24xlarge and m8g.16xlarge capacity in euw1-az1 and euw1-az2 between 20:00 and 02:00 UTC on 04-03 to 04-06. If the snapshot shows free capacity during those errors, the TAM needs to look at account-level limits.
- **Real demand.** CloudTrail only records launch attempts. It does not show the ASG's desired capacity or whether the tier ran short of vCPU. From the script's counts, each AZ delivered about 60×96 + 40×64 = 8,320 vCPU per night after the cancel, against about 110×96 + 5×64 = 10,880 vCPU before. The customer's ASG and CloudWatch metrics (GroupDesiredCapacity vs InService) would confirm whether the tier was actually short.
- **Why the reservations were cancelled.** We don't know. Possibly they were seen as a rollout-only buffer, or cancelled to save cost. Ask the platform team.
- **Whether ASG retries are included in the ICE count.** ICE counts are refused instances after deduplication. Some of them may be retries of the same desired slot, so 45 and 35 are an upper bound on the per-night shortfall.
- **Whether the 110 launches on nights 1–2 used the reservations.** The RunInstances records don't say whether instances matched the ODCR. The timing strongly suggests it, but the data doesn't prove it.
- Other regions and accounts: not in the export. NOT RUN.

## 5. What to do now (next 24 hours)

| When | Who | What |
|---|---|---|
| Today | Customer platform team | Create ODCRs for m8g.24xlarge again: 40/AZ now, and 60/AZ in eu-west-1a as soon as it is granted. Open/targeted matching for mall-web-asg. Start them before 20:00 UTC |
| Today | AWS account team / TAM | Confirm the batches can be delivered in euw1-az1/az2, and provide the night capacity snapshot (section 4) |
| Before tonight's peak | Customer platform team | Give m8g.16xlarge a higher share and add one or two more Arm fallback sizes to the mixed instances policy, so tonight's peak is covered even if the ODCR is late |
| Tomorrow morning | Customer + account team | Run `classify.py` again on tonight's CloudTrail. Expected result: 0 ICE for m8g.24xlarge |
| Pause the rollout only if | Customer | ICE continues with the ODCR active and the fallback widened, **or** the snapshot shows free capacity during the errors (escalate to the TAM instead) |

## 6. What to do differently next time

| Change | Owner |
|---|---|
| **Agree a rollback condition before releasing any reservation.** For example: "release only after N nights at peak with 0 ICE on On-Demand alone, and reserve again if ICE appears." Release in steps (for example 100 → 60 → 30), not all 200 at once, and watch one night peak after each step | Customer platform team + account team |
| Treat reservations for a peak-shaped workload as a running cost to review, not a rollout-only buffer. Size them to the measured night shortfall (45/35 here) | Customer (FinOps + platform) |
| Before any release, test the fallback mix at full peak, measured in vCPU rather than instance count | Customer platform team |
| Alarm on `InsufficientInstanceCapacity` from CloudTrail/EventBridge for mall-web-asg, so this is caught the first night | Customer platform team |
| Share planned reservation changes and night peak forecasts with the TAM in advance | Customer → account team |

Artifacts: `output/summary.json` (classifier output), `output/spec.json` (batch plan input), `output/rollout-report.html` (daily page).
