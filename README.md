<p align="center">
  <img src="assets/banner.svg" alt="AWS Graviton Adoption Toolbox" width="100%">
</p>

<p align="center">
  <b>English</b> · <a href="README_CN.md">简体中文</a>
</p>

<p align="center">
  <img alt="License: MIT-0" src="https://img.shields.io/badge/license-MIT--0-blue.svg">
  <img alt="Status: early development" src="https://img.shields.io/badge/status-early%20development-orange.svg">
  <img alt="Agent Skills" src="https://img.shields.io/badge/format-Agent%20Skills-6f42c1.svg">
  <img alt="Works with Claude Code, Kiro, Codex, Copilot" src="https://img.shields.io/badge/works%20with-Claude%20Code%20%7C%20Kiro%20%7C%20Codex%20%7C%20Copilot-2dd4bf.svg">
  <img alt="AWS Graviton" src="https://img.shields.io/badge/AWS-Graviton-ff9900.svg?logo=amazonaws&logoColor=white">
</p>

> [!WARNING]
> **Early development (v0.1 in progress).** Nothing here is ready for production use yet.

## Why this exists

Most Graviton tools stop when the code builds. Real adoption projects usually stall **after** that point: instances can't launch at peak, or a crash shows up only on Arm, and the customer asks whether to pause.

| | Typical migration tools | This toolbox |
|---|---|---|
| Question answered | *Does my code run on Arm?* | *Will this workload land at scale and stay on Arm?* |
| Stages covered | Scan, convert, build | Every stage, from finding the workload to making Arm the default for new capacity |
| After the build passes | Mostly out of scope | Rollout & capacity diagnosis, Arm-only failure triage |
| Proof that it helps | Demos | A replay benchmark of real incidents, run with and without the toolbox |

## The adoption journey

```mermaid
flowchart LR
    A[Find workload<br/>& owner team] --> B[Benefit &<br/>capacity check]
    B --> C[Dependency<br/>scan]
    C --> D[Load test<br/>& canary]
    D --> E[Scale-out<br/>rollout]
    E --> F[Default to Arm<br/>for new capacity]
    D -. Arm-only crash, hang<br/>or wrong result .-> T[Arm-only<br/>triage]
    E -. Can't launch<br/>instances .-> R[Capacity<br/>diagnosis]

    classDef integ fill:#1e293b,stroke:#64748b,color:#e2e8f0
    classDef orig fill:#ff9900,stroke:#c26f00,color:#111827,font-weight:bold
    classDef keep fill:#2dd4bf,stroke:#0f766e,color:#042f2e,font-weight:bold
    class A,B,C,D integ
    class E,R,T orig
    class F keep
```

<sub>Grey = existing tools, integrated rather than rebuilt · Orange = original to this toolbox · Teal = weekly adoption health</sub>

## What's in the box

| | Part | What it does | Source |
|---|---|---|---|
| 🧭 | [`graviton-playbook/`](graviton-playbook/) | Entry skill. Asks where you are stuck, routes you to the right stage tool, and names the decision the customer has to make at each stage | Original |
| 🔌 | [`integrations/`](integrations/) | How to call [Arm MCP Server](https://github.com/arm/mcp) / Kiro Graviton Migration Power, AWS Transform custom (Java), graviton-readiness and the Graviton Savings Dashboard | Integrated |
| 📏 | [`references/`](references/) | Benchmark comparison checklist (same AZ, same size class, normalized per unit of traffic, pass bars agreed up front) and a canary checklist | Original |
| 🚀 | [`graviton-rollout-capacity/`](graviton-rollout-capacity/) | **Rollout & capacity skill.** Uses CloudTrail request evidence to tell insufficient capacity from quota from other errors, then gives a pre-rollout check, reservation batch planning, a daily rollout page and a weekly adoption health report | ⭐ Original |
| 🔬 | [`arm-only-failure-triage/`](arm-only-failure-triage/) | **Arm-only failure triage skill + repro harness.** Rules out memory ordering, compiler bugs, allocator mix-ups, `char` signedness, floating point and wrong native libraries, with a repro on both x86 and Graviton, before naming a root cause | ⭐ Original |
| 🏁 | [`replay-bench/`](replay-bench/) | **Replay benchmark.** Sanitized real incidents and public post-mortems. Each case is run with and without the toolbox and scored on root cause, time taken and wrong claims | ⭐ Original |

## Principles

- **Scripts produce facts; the model makes the judgment.** Dedupe, classification and capacity math happen in scripts, so the results can be checked.
- **Honesty rules.** A check that was not run is reported as `NOT RUN`. No root cause is stated until it has been reproduced on both architectures.
- **Read-only by default.** Skills that touch an AWS account ship a read-only IAM policy and never launch instances or change quotas on their own.
- **No customer data.** Fixtures and replay cases are sanitized or synthetic.

## Roadmap

- [ ] **v0.1**: `graviton-playbook` + `graviton-rollout-capacity` + 2 replay cases, plus a "which existing tool to use" table for the other stages
- [ ] **v0.2**: `arm-only-failure-triage` + repro harness, 5 replay cases
- [ ] **Later**: benchmark comparison checklist, weekly adoption report, 20+ replay cases, results for Kiro / Claude Code / Codex / Copilot

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
