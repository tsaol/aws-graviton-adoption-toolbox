# graviton-rollout-capacity

Rollout & capacity skill (planned for v0.1).

| Phase | What it does |
|---|---|
| 0 Pre-rollout check | Peak demand per AZ for the target size, reservations, fallback instance types, On-Demand quotas, rollback agreed before releasing reservations |
| 1 Evidence | Pull failed RunInstances / CreateFleet events from CloudTrail and dedupe them by request ID |
| 2 Classify | Group failures by instance type x AZ x error code x hour into three buckets: insufficient capacity, quota, other. Map AZ names to AZ IDs |
| 3 Options | Fallback types, reservation batch simulation, x86 fallback, with an owner for each option |
| 4 Daily page | Launches and failures per night, fallback types used, zero-ICE days, Arm share of new capacity |
| 5 Hand-off | What public data can't tell, packaged as evidence for the account team |

`scripts/` holds the deterministic parts; `tests/fixtures/` holds synthetic data only.
