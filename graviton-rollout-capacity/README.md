# graviton-rollout-capacity

Rollout & capacity skill (v0.1 first cut). The agent-facing instructions are in [SKILL.md](SKILL.md).

```bash
python3 -m unittest discover -s tests -v   # 13 tests, uses the replay-bench synthetic cases
```

| Phase | What it does |
|---|---|
| 0 Pre-rollout check | Peak demand per AZ for the target size, reservations, fallback instance types, On-Demand quotas, rollback agreed before releasing reservations |
| 1 Evidence | Pull failed RunInstances / CreateFleet events from CloudTrail and dedupe them by request ID |
| 2 Classify | Group failures by instance type x AZ x error code x hour into three buckets: insufficient capacity, quota, other. Map AZ names to AZ IDs |
| 3 Options | Fallback types, reservation batch simulation, x86 fallback, with an owner for each option |
| 4 Daily page | Launches and failures per night, fallback types used, zero-ICE days, Arm share of new capacity |
| 5 Hand-off | What public data can't tell, packaged as evidence for the account team |

`scripts/` holds the deterministic parts (`classify.py`, `simulate_split.py`, `daily_page.py`); test data is synthetic and lives in `replay-bench/cases/`.
