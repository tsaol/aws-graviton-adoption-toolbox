#!/usr/bin/env python3
"""Run each replay case with and without the toolbox, using Claude Code in headless mode.

Both modes use the same model, the same task text and an empty, isolated Claude Code
config directory, so user-level CLAUDE.md files, hooks and skills do not leak in.
The only difference: in "with" mode the workspace has the toolbox skills in .claude/skills/.

Usage: python3 run.py [--cases a,b] [--repeats 2] [--model ID] [--out results/<date>]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKILLS = ["graviton-playbook", "graviton-rollout-capacity"]


def make_workspace(case, mode, base):
    ws = tempfile.mkdtemp(prefix=f"{case}-{mode}-", dir=base)
    shutil.copytree(os.path.join(HERE, "cases", case, "input"), os.path.join(ws, "input"))
    if mode == "with":
        for s in SKILLS:
            shutil.copytree(os.path.join(ROOT, s), os.path.join(ws, ".claude", "skills", s),
                            ignore=shutil.ignore_patterns("tests", "__pycache__", "README.md"))
    return ws


def run_one(case, mode, rep, model, base, timeout):
    ws = make_workspace(case, mode, base)
    cfg = tempfile.mkdtemp(prefix="cc-config-", dir=base)
    with open(os.path.join(HERE, "cases", case, "task.md"), encoding="utf-8") as fh:
        task = fh.read()
    env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
    cmd = ["claude", "-p", task, "--model", model, "--output-format", "json",
           "--dangerously-skip-permissions", "--max-turns", "60"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", "timeout", -1
    wall = time.time() - t0
    meta = {}
    try:
        meta = json.loads(out)
    except json.JSONDecodeError:
        pass
    answer_path = os.path.join(ws, "answer.md")
    answer = open(answer_path, encoding="utf-8").read() if os.path.exists(answer_path) else (meta.get("result") or "")
    used_skill = os.path.exists(os.path.join(ws, "summary.json")) or "classify.py" in json.dumps(meta)
    return {"case": case, "mode": mode, "rep": rep, "returncode": rc, "wall_seconds": round(wall, 1),
            "duration_ms": meta.get("duration_ms"), "num_turns": meta.get("num_turns"),
            "cost_usd": meta.get("total_cost_usd"), "answer": answer, "stderr_tail": err[-500:],
            "workspace": ws, "files_written": sorted(os.listdir(ws))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="ice-two-causes,ice-after-release")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--model", default="jp.anthropic.claude-opus-5-5")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=os.path.join(HERE, "results", dt.date.today().isoformat()))
    a = ap.parse_args()
    base = tempfile.mkdtemp(prefix="replay-")
    jobs = [(c, m, r) for c in a.cases.split(",") for m in ("without", "with") for r in range(1, a.repeats + 1)]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        runs = list(ex.map(lambda j: run_one(*j, a.model, base, a.timeout), jobs))
    os.makedirs(os.path.join(a.out, "answers"), exist_ok=True)
    for r in runs:
        with open(os.path.join(a.out, "answers", f"{r['case']}__{r['mode']}__{r['rep']}.md"), "w", encoding="utf-8") as fh:
            fh.write(r["answer"])
    with open(os.path.join(a.out, "runs.json"), "w", encoding="utf-8") as fh:
        json.dump({"model": a.model, "date": dt.datetime.utcnow().isoformat() + "Z", "runs": runs}, fh, indent=1, ensure_ascii=False)
    for r in runs:
        print(r["case"], r["mode"], r["rep"], "rc", r["returncode"], "s", r["wall_seconds"], "turns", r["num_turns"], "files", r["files_written"])


if __name__ == "__main__":
    main()
