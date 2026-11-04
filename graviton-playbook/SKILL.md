---
name: graviton-playbook
description: Entry point for adopting AWS Graviton (Arm64) for a new business workload. Use when someone asks how to move a workload to Graviton, where to start, what to do next in a Graviton migration or rollout, or describes a problem at any stage (finding workloads, dependency scan, load test, canary, scale-out, default-to-Arm). Routes to the right stage tool.
---

# Graviton adoption playbook

First find out which stage the user is in, then hand off. Ask one short question only if the stage is unclear.

| Stage | Decision the customer makes | Use |
|---|---|---|
| Find workload & owner team | Will a team try it? | graviton-readiness for Kubernetes workloads; Graviton Savings Dashboard; rank by usage, price gap, porting effort, risk, owner |
| Benefit & capacity check | Is it worth investing? | Benefit = price ratio x resource ratio (multiply, don't add); check target sizes per AZ at peak |
| Dependency scan | Use as is, upgrade, rebuild, or wait? | Arm MCP Server / Kiro Graviton Migration Power; AWS Transform custom for Java; aws-graviton-getting-started language skills |
| Load test & canary | Is it safe to widen traffic? | Same AZ, same size class, normalize per unit of traffic; agree pass bars before testing; rehearse rollback |
| Scale-out rollout, "can't launch instances" | Is the rollout safe to continue? | **graviton-rollout-capacity** skill |
| Crash, hang or wrong result only on Arm | Root cause before the next step | arm-only-failure-triage skill (planned for v0.2): reproduce on both architectures before naming a cause |
| Default to Arm for new capacity | Will they keep adopting? | Weekly Arm share of new capacity; ready services default to Arm, the rest are listed as exceptions |

If the user is at the scale-out stage, or mentions launch failures, ICE or capacity, use the `graviton-rollout-capacity` skill right away.
