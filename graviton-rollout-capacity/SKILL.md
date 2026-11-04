---
name: graviton-rollout-capacity
description: Diagnose and manage EC2 launch failures during a Graviton (or any EC2) scale-out rollout. Use when someone says instances can't launch, Auto Scaling or Karpenter can't add nodes, they see InsufficientInstanceCapacity / ICE / VcpuLimitExceeded, or the customer asks whether to pause a Graviton rollout. Also use before a large rollout to check capacity, and weekly to track Graviton adoption health (share of new capacity on Arm). Works from CloudTrail and CUR evidence; read-only.
---

# Graviton rollout & capacity

Turn "we can't launch instances" into causes that can be acted on, each with an owner. Then help the rollout keep going.

## Rules

1. **Scripts produce the facts. You explain them.** Never count, dedupe or add up failures by hand or by reading the raw logs. Run `scripts/classify.py` and quote its numbers.
2. **Split before you advise.** Report capacity, quota and other errors separately, per instance type x AZ x hour. Each cause needs its own action.
3. **`InsufficientInstanceCapacity` is not a quota problem.** Never suggest a quota increase for it.
4. **Capacity errors while capacity shows as free.** If the account team's snapshot shows free capacity at the time of capacity errors (`capacity_vs_snapshot_flags`), pool depth does not explain the failures. Do not just switch instance types. Package the evidence (times, type, AZ, error count, snapshot value) for the AWS account team (TAM) to investigate.
5. **Don't recommend pausing the rollout as the first answer.** Give the options that keep it going, the fallback, and when pausing would make sense.
6. **Honesty.** Write `NOT RUN` for any check you did not run. Say what the data cannot show.
7. **Read-only.** Do not launch instances, create or cancel reservations, or change quotas. Recommend; don't act. The permissions needed are in `iam/readonly-policy.json`.

## Steps

All paths are relative to this skill's directory. Python 3.9+, standard library only.

Pick the steps that fit the question:
- **"We can't launch instances" / ICE / "should we pause?"** → steps 1, 2, 3 (then 4 and 5 if useful).
- **"We are about to roll out"** → step 0.
- **"How is adoption going?"** → step 6.

### 0. Pre-rollout check

```bash
python3 scripts/precheck.py spec.json
```

The spec lists the primary and fallback types, the peak instances per AZ, the rollout date, and (optionally) files collected with read-only calls:
- `aws ec2 describe-instance-type-offerings --location-type availability-zone` → `offerings_file`;
- `aws ec2 describe-capacity-reservations` → `reservations_file`;
- the On-Demand vCPU quota from `aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A` → `vcpu_quota`;
- the account team's capacity snapshot → `snapshot_file`;
- planned reservation releases → `release_plan`.

It reports PASS / FAIL / NOT RUN for 7 checks: offered in every AZ, fallback of the same architecture, quota headroom, reservations vs peak per AZ, free capacity at peak, lead time (8+ weeks for 100+ instances), and rollback agreed before any release. See the docstring for the spec format. Report every NOT RUN as a gap, not as a pass.

### 1. Get the evidence

Use CloudTrail files (`{"Records": [...]}`), JSON Lines, or saved output of:

```bash
aws cloudtrail lookup-events --region <region> \
  --lookup-attributes AttributeKey=EventName,AttributeValue=RunInstances \
  --start-time <iso> --end-time <iso> > lookup.json
```

Also collect, if available:
- hourly usage from the Cost and Usage Report (CUR) as CSV with `line_item_usage_start_date, product_instance_type, line_item_availability_zone, line_item_usage_amount`. It shows how many instances were really running while launches failed;
- a subnet-to-AZ map: `aws ec2 describe-subnets` → `{"subnet-…": "az"}`;
- AZ IDs: `aws ec2 describe-availability-zones` → `{"az name": "az id"}`. AZ names differ per account; compare across accounts by AZ ID;
- a capacity snapshot from the account team: `[{"time", "instanceType", "availabilityZone", "free"}]`.

### 2. Classify

```bash
python3 scripts/classify.py <files or dirs> \
  --subnet-map subnet-map.json --az-ids az-ids.json \
  [--capacity-snapshot capacity-snapshot.json] [--cur usage-hourly.csv] \
  [--tz-offset <hours>] [--night-start 18 --night-end 8] -o summary.json
```

Input can be plain or `.gz`, files or directories. Duplicates are removed in two layers: the same record twice (`duplicates_removed`, e.g. merged trails), then several rows for the same request (`repeated_request_rows_collapsed`, e.g. exports with one row per instance or log line). Always quote counts after both layers (`unique_requests`).

Read these fields from `summary.json`: `unique_requests`, `instances_by_bucket`, `by_type_az_code`, `nights` (with `peak_running_from_cur` when CUR is given), `failure_hours`, `capacity_vs_snapshot_flags`, `reservation_events`, `hourly_with_cur`.

### 3. Decide what each pattern means

| Pattern in the summary | Meaning | Action and owner |
|---|---|---|
| Capacity errors for one type in several AZs, during peak hours | The pool for that size is short at peak | Fallback types of the same generation and architecture (customer platform team); capacity reservations delivered in batches (customer + account team) |
| Capacity errors in `capacity_vs_snapshot_flags` | Not explained by pool depth | Send the evidence to the TAM to check account-level limits; keep the fallback in place meanwhile |
| `VcpuLimitExceeded` / `InstanceLimitExceeded` | Real quota | Raise the On-Demand vCPU quota in Service Quotas (customer) |
| `InsufficientFreeAddressesInSubnet` and other codes | Configuration | Add subnet/IP space or fix the launch template (customer) |
| Capacity errors start right after a `CancelCapacityReservation` | Released reservation; shared pool now used by others | Re-reserve or keep part of it; next time agree a rollback condition **before** releasing |

### 4. Plan reservation batches (if a reservation is part of the answer)

```bash
python3 scripts/simulate_split.py spec.json
```

The spec gives the peak gap per AZ and the batches. Report which batch closes the gap in each AZ.

### 5. Daily page

```bash
python3 scripts/daily_page.py summary.json -o rollout-report.html
```

### 6. Weekly adoption health

```bash
python3 scripts/weekly_report.py usage-hourly.csv [--summary summary.json ...] --html weekly.html
```

Per ISO week: Graviton share of vCPU at the weekly peak, **Graviton share of new capacity** (of the vCPU added since last week, how much is on Arm), and ICE / zero-ICE nights from the summaries. If the share of new capacity drops while the total grows, new demand is landing on x86: the "default to Arm for new capacity" step is missing.

## Answer format

1. **Verdict** in two or three sentences: whether to keep rolling out, and why.
2. **Causes**: one row per cause, with type, AZ, hours, instance count (from the script), meaning, action and owner.
3. **What the data cannot show**, and what to ask the account team for.
4. **Next 24 hours**: who does what.
