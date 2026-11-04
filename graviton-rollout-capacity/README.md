# graviton-rollout-capacity

Rollout & capacity skill (v0.1 first cut). The agent-facing instructions are in [SKILL.md](SKILL.md).

```bash
python3 -m unittest discover -s tests -v   # unit tests, use the replay-bench synthetic cases + tests/data
python3 tests/check_iam_policy.py          # checks iam/readonly-policy.json is Read/List only (needs internet)
```

| Phase | What it does |
|---|---|
| 0 Pre-rollout check | Peak demand per AZ for the target size, reservations, fallback instance types, On-Demand quotas, rollback agreed before releasing reservations |
| 1 Evidence | Pull RunInstances events from CloudTrail; remove duplicate records (eventID) and repeated rows of the same request (requestID); optionally add hourly CUR usage |
| 2 Classify | Group failures by instance type x AZ x error code x hour into three buckets: insufficient capacity, quota, other. Map AZ names to AZ IDs |
| 3 Options | Fallback types, reservation batch simulation, x86 fallback, with an owner for each option |
| 4 Daily page | Launches and failures per night, fallback types used, zero-ICE days, Arm share of new capacity |
| 5 Hand-off | What public data can't tell, packaged as evidence for the account team |

| 6 Weekly health | Graviton share at peak, Graviton share of new capacity, ICE nights per week |

`scripts/`: `classify.py` (two-layer dedupe, classification, CUR alignment), `precheck.py`, `simulate_split.py`, `daily_page.py`, `weekly_report.py`, `ec2util.py`. `iam/readonly-policy.json`: the read-only permissions. Test data is synthetic (`replay-bench/cases/`, `tests/data/`).
