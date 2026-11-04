# replay-bench

Replay benchmark. Cases so far: `ice-two-causes`, `ice-after-release` (synthetic data, regenerate with `python3 tools/gen_cases.py`).

```bash
python3 run.py --repeats 2          # needs Claude Code (claude -p) with Bedrock or API access
python3 grade.py results/<date>     # needs boto3 + Amazon Bedrock access for the judge model
```

Results are committed under `results/<date>/`: `runs.json`, `scores.json`, `report.md`, `report.html`, `answers/`.

```
cases/<case>/
  input/       material given to the agent (sanitized logs, dump summaries, dashboard numbers)
  task.md      the question and what the agent is allowed to do
  answer.json  rubric: facts that must be covered, wrong claims to watch for
run.py        runs each case headless (claude -p / kiro-cli), with and without the toolbox
grade.py      checks key facts with scripts, then scores with a model against a rubric
report.html   per case: correct or not, time taken, wrong claims made
```

The case format borrows from Build-bench: fixed inputs, an explicit allowed scope, and replay in a clean environment.
