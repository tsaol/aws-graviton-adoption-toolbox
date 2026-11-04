# AWS Graviton Adoption Toolbox

Most tools help your code *migrate* to AWS Graviton. This toolbox helps a new workload *land and stay* on Graviton.

It is a plugin, which means a bundle of [Agent Skills](https://agentskills.io). It works with Claude Code, Kiro, Codex and GitHub Copilot. It walks an AWS Solutions Architect and the customer's platform and dev teams through every stage of adopting Graviton for a new business workload:

```
find workload & team -> benefit & capacity check -> dependency scan -> load test -> canary -> scale-out rollout -> default to Arm for new capacity
```

> **Status: early development (v0.1 in progress).** Nothing here is ready for production use yet.

## What is in the box

| Part | What it does | Source |
|---|---|---|
| `graviton-playbook/` | Entry skill. Asks where you are stuck and routes you to the right stage tool. Lists the decision the customer has to make at each stage. | Original |
| `integrations/` | How to call existing tools for the early stages: [Arm MCP Server](https://github.com/arm/mcp) / Kiro Graviton Migration Power, AWS Transform custom (Java), graviton-readiness, the Graviton Savings Dashboard | Existing tools, not rebuilt |
| `references/` | Benchmark-comparison checklist (same AZ, same size class, normalize per unit of traffic, set pass bars before the test) and a canary checklist | Original |
| `graviton-rollout-capacity/` | **Rollout & capacity skill.** Finds out why instances can't launch (insufficient capacity vs quota vs other) from CloudTrail request evidence, gives a pre-rollout check, plans reservation batches, and produces a daily rollout page and a weekly adoption health report | Original |
| `arm-only-failure-triage/` | **Arm-only failure triage skill.** Rules out memory ordering, compiler bugs, allocator mix-ups, `char` signedness, floating-point differences and wrong native libraries before naming a root cause. Its `harness/` builds the same commit on x86 and Graviton to reproduce the failure | Original |
| `replay-bench/` | **Replay benchmark.** Real incidents (sanitized) and public post-mortems as test cases. Each case is run with and without the toolbox and scored on correct root cause, time and wrong claims | Original |

## Principles

- **Scripts produce facts; the model makes the judgment.** Dedupe, classify and capacity math are done in scripts, so the results can be checked.
- **Honesty rules.** A check that was not run is reported as `NOT RUN`. A root cause is not stated until it has been reproduced on both architectures.
- **Read-only by default.** Skills that touch an AWS account ship a read-only IAM policy and never launch instances or change quotas on their own.
- **No customer data in this repo.** Fixtures and replay cases are sanitized or synthetic.

## Roadmap

| Version | Scope |
|---|---|
| v0.1 | `graviton-playbook` + `graviton-rollout-capacity` + 2 replay cases; a "which existing tool to use" table for the other stages |
| v0.2 | `arm-only-failure-triage` + repro harness; 5 replay cases |
| later | Benchmark-comparison checklist, weekly adoption report, 20+ replay cases, results for Kiro / Claude Code / Codex / Copilot |

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
