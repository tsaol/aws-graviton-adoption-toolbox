# Replay benchmark results (2026-11-04)

- Agent: Claude Code headless (`claude -p`), model `jp.anthropic.claude-opus-5-5`, isolated config, same task text in both modes
- Judge: `jp.anthropic.claude-opus-5-5` on Amazon Bedrock, given only the rubric and the answer
- **with** = workspace has the toolbox skills in `.claude/skills/`; **without** = same workspace, no skills

## Summary

| Case | Mode | Runs | Fact score | Wrong claims / run | Key numbers right | Time (s) | Turns | Cost (USD) |
|---|---|---|---|---|---|---|---|---|
| ice-after-release | **with** | 2 | 1.0 | 0 | 1.0 | 77.05 | 8 | 0.309 |
| ice-after-release | **without** | 2 | 0.7 | 1 | 0.667 | 91.65 | 6.5 | 0.358 |
| ice-two-causes | **with** | 2 | 1.0 | 0 | 1.0 | 108.2 | 10.5 | 0.475 |
| ice-two-causes | **without** | 2 | 0.791 | 0 | 0.4 | 134.8 | 9 | 0.558 |

Fact score: covered = 1, partly = 0.5, missing = 0, averaged over the rubric facts. Key numbers right: share of facts whose numbers all appear in the answer.

## Per run

- `ice-after-release` **with** #1: score 1.0, facts F1:C F2:C F3:C F4:C F5:C, wrong claims none, 68.8 s. Skills loaded: graviton-rollout-capacity; scripts run: classify.py. The answer ties the ICE start on 2030-04-03 to the cancellation of both 100-instance reservations and gives deduplicated counts (45/35 per night, 180/140 total). It rules out quota and gives now/next-time actions with owners; pausing the rollout appears only as a conditional last resort, not the main answer.
- `ice-after-release` **with** #2: score 1.0, facts F1:C F2:C F3:C F4:C F5:C, wrong claims none, 85.3 s. Skills loaded: graviton-rollout-capacity; scripts run: classify.py, simulate_split.py. The answer ties the ICE failures, starting the night of 04-03, to both 100-instance reservations being cancelled at 10:00 UTC, gives deduplicated counts (45/35 per night, 180/140 total), and rules out a quota cause. Its remediation re-reserves capacity, widens the fallback, sets a rollback condition before any release and names owners; it explicitly rejects a quota increase and pausing the rollout.
- `ice-after-release` **without** #1: score 0.7, facts F1:C F2:C F3:M F4:P F5:C, wrong claims W4, 99.2 s. Skills loaded: none; scripts run: none. The answer correctly ties the ICE errors to the 2030-04-03 ODCR cancellation and gives good remediation with owners. However, it reports about 258 ICE per night (1,042 total; 574 in 1a, 468 in 1b) instead of about 45 and 35 per night, which points to counts inflated by duplicate records. It notes that the 16xlarge fallback never failed but never says this is not a quota problem.
- `ice-after-release` **without** #2: score 0.7, facts F1:C F2:C F3:M F4:P F5:C, wrong claims W4, 84.1 s. Skills loaded: none; scripts run: none. The answer correctly ties the errors to the 2030-04-03 cancellation of both 100-instance reservations, but reports roughly 147/111 ICE errors per night instead of about 45/35, so it counted duplicate records. It confirms the 16xlarge fallback succeeded but never says this is not a quota problem.
- `ice-two-causes` **with** #1: score 1.0, facts F1:C F2:C F3:C F4:C F5:C F6:C, wrong claims none, 128.1 s. Skills loaded: graviton-rollout-capacity; scripts run: classify.py, daily_page.py, weekly_report.py. The answer covers every rubric fact with the correct deduplicated counts (210/165/90/36/15, 465 of 1,161 unique requests from 3,754 rows) and assigns an owner to each action. It mentions the raw figure of 1,517 ICE rows only to warn against quoting it, and it recommends a quota increase only for the VcpuLimitExceeded errors, so no wrong claims apply.
- `ice-two-causes` **with** #2: score 1.0, facts F1:C F2:C F3:C F4:C F5:C F6:C, wrong claims none, 88.3 s. Skills loaded: graviton-rollout-capacity; scripts run: classify.py. All facts are stated correctly with the right numbers and owners, and the answer explicitly says not to file a quota increase for the InsufficientInstanceCapacity errors. Two minor internal inconsistencies: it lists 'four' causes in the verdict but 'five' later, and it says m8g.16xlarge launched 'without errors' in eu-west-1b despite the subnet errors there.
- `ice-two-causes` **without** #1: score 0.833, facts F1:C F2:P F3:C F4:C F5:P F6:C, wrong claims none, 131.2 s. Skills loaded: none; scripts run: none. F2 is partly covered: the answer flags that the 240-free snapshot conflicts with the 1a failures and routes it to the account team, but explains it as an AZ-name mapping issue rather than an account-level cause. F5 is partly covered: dedup is correct (1,161 of 3,754), but the answer gives per-night figures and never states the 465 total capacity failures.
- `ice-two-causes` **without** #2: score 0.75, facts F1:P F2:P F3:C F4:C F5:P F6:C, wrong claims none, 138.4 s. Skills loaded: none; scripts run: none. F1 gives only the combined 375 m8g.24xlarge ICEs, not the 210/165 per-AZ split. F2 notes the 240-free snapshot contradiction and sends it to the account team, but still labels it a pool shortage and explains it as AZ-name mapping rather than saying pool depth doesn't explain it. F5 describes both duplicate types and the 1,161/3,754 counts, but never states 465 total capacity failures (only 516 failures overall).

Answers are in `answers/`. Raw runs in `runs.json`, grades in `scores.json`.
