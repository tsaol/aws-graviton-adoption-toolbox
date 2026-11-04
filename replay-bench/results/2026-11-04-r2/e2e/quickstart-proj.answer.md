**Short answer: don't pause.** This is not a Graviton problem. At night, AWS has no free m8g.24xlarge capacity in eu-west-1a or eu-west-1b. Use other instance sizes as a fallback and plan capacity reservations, and the rollout can keep going. There are also three smaller problems with different causes. One of them needs the AWS account team (TAM).

All numbers come from `classify.py`. It read 3,754 raw records, removed 334 duplicate records, and merged 2,259 repeated rows into one row per request. That left **1,161 unique launch requests**: 645 successes, 465 capacity errors, 36 quota errors and 15 other errors. The data covers 3 nights (2030-03-03 to 03-06, UTC). The pattern is the same every night.

## Causes

| # | Type / AZ | Hours (UTC) | Instances | What it means | Action, owner |
|---|---|---|---|---|---|
| 1 | **m8g.24xlarge**, eu-west-1a (euw1-az1) + eu-west-1b (euw1-az2) | 20:00–01:59 every night | **375** `InsufficientInstanceCapacity` (210 in 1a, 165 in 1b) | AWS has run out of this size at peak time. The account team's snapshot shows **free = 0** at 22:00 each night in both AZs. CUR shows you can only reach about 70 (1a) and 75 (1b) running instances. | Add same-generation Graviton fallbacks to the ASG with mixed instances (m8g.16xlarge, c8g/r8g large sizes, m7g). Ask the account team about capacity reservations in batches. *Your platform team + account team.* **Not a quota problem. A quota increase will not help.** |
| 2 | **m8g.16xlarge**, eu-west-1a | 01:00–02:59 | **90** `InsufficientInstanceCapacity` | The snapshot shows **240 free** at the same times (6 flagged checks, 13–17 errors each). Pool size does not explain these errors. | Send the evidence to the TAM (see below). Until they answer, keep 16xlarge launches in 1b, which had 0 capacity errors. *Account team.* |
| 3 | c8g.4xlarge, eu-west-1b | 22:00 | 36 `VcpuLimitExceeded` | A real On-Demand vCPU quota limit. | Raise quota L-1216C47A in Service Quotas. Remember that the fallback types in #1 will use more vCPU too. *You.* |
| 4 | m8g.16xlarge, eu-west-1b | 23:00 | 15 `InsufficientFreeAddressesInSubnet` | subnet-0bbb2222 has run out of IP addresses. | Add subnet space or another subnet. *You.* |

There were no reservation cancel events, so this was not caused by releasing a reservation.

## When pausing would make sense

Pause only if both of these are true: the fallback sizes also fail at night (or the TAM finds an account-level block), and the missing capacity hurts your service. Even then, pause only the m8g.24xlarge part and keep the rest going.

## What the data can't show

- Why #2 happens even though the snapshot shows free capacity. Only AWS can check this, for example for account-level placement limits. Send them: m8g.16xlarge, eu-west-1a / euw1-az1, 01:30 and 02:30 UTC on 03-04, 03-05 and 03-06, 13–17 errors per check, snapshot free = 240.
- Whether the fallback sizes have free capacity at night. The snapshot only covers the two m8g sizes. Ask the account team for a night-time snapshot of the fallback types.
- The ASG settings themselves. I only saw CloudTrail and CUR data, not the launch templates.
- The data is dated 2030 and I used a UTC offset of 0. Please check that the dates are right.
- Pre-rollout check, reservation plan, daily page and weekly report: **NOT RUN**.

## Next 24 hours

- **Platform team:** add fallback types to the m8g.24xlarge ASGs before tonight's 20:00 peak. Ask for the vCPU quota increase. Add more IP space to subnet-0bbb2222.
- **Account team / TAM:** look into cause #2. Send a night-time capacity snapshot for the fallback types. Start talking about capacity reservations for m8g.24xlarge in batches.
- **Tomorrow morning:** run `classify.py` again on tonight's logs to check that capacity errors went down.

The summary is saved at `~/tmp/grav/summary.json`.