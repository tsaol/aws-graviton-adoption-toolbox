# Graviton web tier: pre-rollout check (as of 2030-04-01)

## 1. Verdict

**Not ready yet.** 5 of 7 checks fail. The instance types and the fallback are fine, but the vCPU quota, the reservations, the free capacity in eu-west-1a and the lead time all fall short. The release plan for `cr-0a1a1a1a1a1a1a1a1` also has no rollback. Most of these can be fixed by acting this week, so you do not need to cancel the plan. But the 2030-05-20 date only works if the quota request and the capacity talks with the account team start now. If not, move the date or roll out in phases.

Result from `scripts/precheck.py` (spec: `~/tmp/precheck-run/spec.json`, with today = 2030-04-01):

| # | Check | Result | Detail |
|---|---|---|---|
| C1 | Primary and fallback types offered in every AZ | PASS | m8g.24xlarge and m8g.16xlarge are offered in 1a and 1b |
| C2 | Fallback has the same architecture | PASS | m8g.16xlarge (Graviton, same generation) |
| C3 | On-Demand vCPU quota covers peak | **FAIL** | need 30,120 vCPU (220 × 96 = 21,120 + 9,000 other) vs quota 24,000 |
| C4 | Reservations vs peak per AZ | **FAIL** | reserved/peak: 1a 50/120, 1b 50/100 |
| C5 | Account team snapshot: free capacity at peak | **FAIL** | 1a: free 60 < peak 120 (1b: free 150, OK) |
| C6 | Lead time (8+ weeks for 100+ instances) | **FAIL** | 7.0 weeks until 2030-05-20 |
| C7 | Rollback agreed before a release | **FAIL** | no rollback agreed for cr-0a1a1a1a1a1a1a1a1 |

No check was NOT RUN. No CloudTrail or CUR data was given, so the failure-analysis steps (classify, daily page, weekly report) are **NOT RUN**. They are not needed before the rollout.

## 2. Problems and actions

| Problem | Where | Numbers | What it means | Action | Owner |
|---|---|---|---|---|---|
| vCPU quota too low | Region (eu-west-1) | Need 30,120, have 24,000. Short by 6,120 | This is a real quota limit. At peak, launches will fail with `VcpuLimitExceeded` after about 156 × 24xlarge (15,000 / 96). | Ask for a quota increase in Service Quotas (L-1216C47A) **now**. Ask for at least ~31,000 so you have some room. | Customer platform team |
| Not enough reservations | 1a and 1b, m8g.24xlarge | 1a: 70 not reserved, 1b: 50 not reserved | These 120 instances depend on the shared pool at peak. | Ask the account team about extra reservations, delivered in batches before 05-20. Use `simulate_split.py` when you have batch sizes. | Customer + account team |
| Low free capacity in 1a | eu-west-1a, m8g.24xlarge | Free 60 vs peak 120 (snapshot 2030-03-28 21:00 UTC) | The pool in 1a may be too small at peak. Even 50 reserved + 60 free = 110, still under 120 (if "free" does not include your reservation). | Plan to use m8g.16xlarge in 1a for part of the peak. Ask the TAM for more snapshots and for a reservation in 1a. Think about moving some load to 1b, which shows 150 free. | Customer platform team + TAM |
| Short lead time | Both AZs | 7.0 weeks, 8 needed | Capacity for 220 large instances may not arrive in time. | Start the requests today. If the account team cannot confirm by mid-April, move the date to 2030-05-27 or later, or roll out in phases (for example 1b first). | Customer + account team |
| Release with no rollback | cr-0a1a1a1a1a1a1a1a1 (eu-west-1a, 50 × m8g.24xlarge) | Release planned 2030-06-01 | This is the **only** reservation in 1a, the AZ that is already short. After release, 1a has 0 reserved for 120 at peak. Other accounts can take that capacity from the shared pool. | Do not release until a rollback is agreed in writing: for example "if any capacity error in 1a in the 7 days after release, we re-reserve N instances". Better: keep it, or release only part, until the web tier has run stable at peak. | Customer (owner of the reservation) + account team |

Note on the fallback and quota: if you run the **whole** peak on m8g.16xlarge (220 × 64 = 14,080 + 9,000 = 23,080), it fits the current quota, with only 920 vCPU left. But a 16xlarge has 2/3 of the power of a 24xlarge. To get the same compute you need about 330 × 16xlarge, which is the same 21,120 vCPU. So the fallback does **not** fix the quota problem. You still need the increase.

## 3. What the data cannot show

- **The snapshot is one moment.** It is one hour (2030-03-28 21:00 UTC) and covers only m8g.24xlarge. It says nothing about other peak hours, about May, or about m8g.16xlarge. Ask the TAM for snapshots at your real peak hours over several days, for both types.
- **What "free" means.** We do not know if "free" counts your own reservation or not. Ask the TAM.
- **The cancelled reservation in 1b.** `cr-0c3c3c3c3c3c3c3c3` (40 × m8g.24xlarge, eu-west-1b) is cancelled and is not counted. If someone thinks it is still there, 1b has 40 fewer reserved than they expect.
- **The 9,000 vCPU of other workloads** is your estimate. If they grow by May, the quota gap is bigger. Check real usage from CUR before you ask for the quota.
- **No launch history.** No CloudTrail or CUR files were given, so we cannot see past capacity errors for these types.
- **Peak per AZ.** If one AZ fails, can the other carry more than its share? The plan (120 / 100) does not say. If yes, the reservations and quota need to cover that too.

## 4. Next steps (next 24 hours / this week)

1. **Platform team:** send the vCPU quota increase request today (to ~31,000 or more for eu-west-1).
2. **Platform team:** set the launch template / Auto Scaling group to use m8g.24xlarge first and m8g.16xlarge as fallback in both AZs, and test it.
3. **Customer + account team (TAM):** ask for (a) extra reservations, about 70 in 1a and 50 in 1b, in batches before 2030-05-20; (b) more capacity snapshots at peak hours for both types; (c) what "free" includes.
4. **Owner of cr-0a1a1a1a1a1a1a1a1:** write and agree a rollback rule before 2030-06-01, or keep the reservation.
5. **Rollout lead:** set a decision date (for example 2030-04-15). If the quota and the reservations are not confirmed by then, move the date or roll out in phases.
6. Run `precheck.py` again with new files after these changes.
