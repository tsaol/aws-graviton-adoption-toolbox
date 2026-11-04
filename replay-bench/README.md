# replay-bench

Replay benchmark (planned for v0.1, 2 cases first).

```
cases/<case>/
  input/      material given to the agent (sanitized logs, dump summaries, dashboard numbers)
  task.md     the question and what the agent is allowed to do
  answer.md   expected answer and common wrong answers
run.py        runs each case headless (claude -p / kiro-cli), with and without the toolbox
grade.py      checks key facts with scripts, then scores with a model against a rubric
report.html   per case: correct or not, time taken, wrong claims made
```

The case format borrows from Build-bench: fixed inputs, an explicit allowed scope, and replay in a clean environment.
