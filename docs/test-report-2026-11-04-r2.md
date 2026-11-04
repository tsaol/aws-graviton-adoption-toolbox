# Test report: v0.1, round 2 (2026-11-04)

What changed since [round 1](test-report-2026-11-04.md):
- **Two-layer dedupe** in `classify.py`: the same record twice (eventID), then several rows for the same request (requestID).
- **CUR alignment**: `classify.py --cur` lines up hourly usage with launch results.
- **Pre-rollout check**: `precheck.py`, 7 checks with PASS / FAIL / NOT RUN.
- **Weekly adoption health**: `weekly_report.py` reports the Graviton share at the weekly peak and the Graviton share of new capacity.
- **Read-only IAM policy**: `iam/readonly-policy.json`.
- **README**: quick start for Claude Code added. The badge now says "tested with Claude Code"; Kiro, Codex and Copilot are marked as not yet tested.
- **Harder replay data and task text**: each request now appears as 1 to 5 rows (3,754 rows for 1,161 requests, about 70% fewer after dedupe, close to real exports). The hint "the export was merged from two trails" was removed. Because of this, round 2 scores **cannot be compared directly** with round 1.

All data is synthetic (account 111122223333, eu-west-1, year 2030).

## 1. Unit tests: 23 / 23 passed

Output: [tests/results/2026-11-04-r2-unittest.txt](../graviton-rollout-capacity/tests/results/2026-11-04-r2-unittest.txt)

| Area | Tests |
|---|---|
| Error buckets, night window | 2 |
| Two-layer dedupe (3,754 rows, 334 duplicate records, 2,259 repeated request rows, 1,161 requests) | 1 |
| Causes in case 1 (210 / 165 / 90 / 36 / 15, 6 snapshot flags, AZ from subnet) | 6 |
| CUR alignment (peak running from CUR, errors and running count in the same hour) | 1 |
| Case 2: reservation cancel, capacity errors only afterwards | 2 |
| Same result for JSON Lines, CloudTrail log file (gzip) and `lookup-events` output; directory input | 2 |
| vCPU and Graviton detection by instance type | 2 |
| Pre-rollout check: not ready (5 FAIL), ready (7 PASS), minimal input (6 NOT RUN) | 3 |
| Weekly report: share of new capacity 100% → 0%, ICE nights per week | 2 |
| Batch simulation, CLI end to end | 2 |

## 2. IAM policy check: PASS

`tests/check_iam_policy.py` checks every action against the public AWS service authorization reference. All 12 actions exist and are Read or List only. Output: [tests/results/2026-11-04-r2-iam-policy.txt](../graviton-rollout-capacity/tests/results/2026-11-04-r2-iam-policy.txt). (IAM Access Analyzer `validate-policy` was **NOT RUN**: the test role has no permission for it.)

## 3. End-to-end with Claude Code (Opus 5.5, isolated config)

Evidence comes from the Claude Code transcripts (`replay-bench/tools/evidence.py`). Results: [replay-bench/results/2026-11-04-r2/e2e.json](../replay-bench/results/2026-11-04-r2/e2e.json), answers in [replay-bench/results/2026-11-04-r2/e2e/](../replay-bench/results/2026-11-04-r2/e2e/).

| Test | What was done | Skill loaded | Script run | Result |
|---|---|---|---|---|
| Quick start, project-level install | Followed README steps 1-2 (local copy in place of `git clone`, because the repo is private), used the README prompt | graviton-rollout-capacity | classify.py | Matches the case 1 rubric: 1,161 requests, 375 (210 + 165), 90 with 240 free → TAM, not a quota problem, don't pause |
| User-level install | Skills copied to the user skills dir (`$CLAUDE_CONFIG_DIR/skills`) | both found | — | PASS |
| Pre-rollout | "Are we ready?" without naming any stage | graviton-rollout-capacity | precheck.py | "Not ready", 5 of 7 FAIL with the right numbers; noticed that the cancelled reservation is not counted |
| Weekly health | "How is adoption going?" on 4 weeks of CUR | graviton-rollout-capacity | weekly_report.py | Found that new capacity went to x86 in weeks 12-13 (14% → 0% on Graviton): the default-to-Arm step is missing |
| Replay, "with" runs (4) | see below | graviton-rollout-capacity | classify.py (+ simulate_split, daily_page) | 4 / 4 |

**Not covered yet: the `graviton-playbook` entry skill was never loaded** in any run. The agent went straight to `graviton-rollout-capacity`, whose description already matches these questions. Routing questions for other stages (for example dependency scan) still need a test.

## 4. Replay benchmark: with vs without the toolbox

Report: [replay-bench/results/2026-11-04-r2/report.md](../replay-bench/results/2026-11-04-r2/report.md) · answers: [replay-bench/results/2026-11-04-r2/answers/](../replay-bench/results/2026-11-04-r2/answers/)

| Case | Mode | Runs | Fact score | Wrong claims / run | Key numbers right | Time (s) | Turns | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| ice-after-release | **with** | 2 | 1.0 | 0 | 1.0 | 77.05 | 8 | 0.309 |
| ice-after-release | **without** | 2 | 0.7 | 1 | 0.667 | 91.65 | 6.5 | 0.358 |
| ice-two-causes | **with** | 2 | 1.0 | 0 | 1.0 | 108.2 | 10.5 | 0.475 |
| ice-two-causes | **without** | 2 | 0.791 | 0 | 0.4 | 134.8 | 9 | 0.558 |

Fact score: covered = 1, partly = 0.5, missing = 0, averaged over the rubric facts. Key numbers right: share of facts whose numbers all appear in the answer.

### What the numbers say

- **With the toolbox: score 1.0 in 4 / 4 runs, no wrong claims, every key number right.**
- **Without the toolbox: 0.70-0.79, and the main failure is the count.**
  - ice-after-release, both runs: the per-night failures were inflated 3 to 6 times (about 258 and 147 / 111 per night instead of 45 / 35), because rows of the same request were not merged. The judge flagged this as a wrong claim (W4).
  - ice-two-causes: duplicates were handled, but the answers did not give the per-AZ split or the 465 total, and they explained the "free capacity in the snapshot" conflict as an AZ-name mapping issue instead of saying that pool depth does not explain it.
- **About 15-20% faster and 13-15% cheaper** with the toolbox (77 vs 92 s; 108 vs 135 s).

### Honest reading

- The harder data shows the main value of the scripts: **counts that can be trusted**. A strong model reasons well without the toolbox, but reports wrong numbers when the export repeats rows. In a real incident, wrong numbers mean the wrong size of reservation request.
- Small sample: 2 cases x 2 modes x 2 runs. The data and the rubric were written by the toolbox author, and the judge is the same model family as the agent.
- Only Claude Code + Opus 5.5 was tested.

### Next tests

1. A routing test for `graviton-playbook` (a question about an early stage).
2. Kiro / Codex / Copilot, and a smaller model.
3. 5+ runs per mode, and a judge model from another vendor.
4. More cases: CreateFleet errors inside responseElements, Karpenter, a case where pausing *is* the right answer.
