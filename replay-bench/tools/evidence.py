#!/usr/bin/env python3
"""Add evidence of skill use to runs.json: which skills the agent loaded and which toolbox
scripts it ran, read from the Claude Code transcripts in each run's isolated config dir.

Usage: python3 tools/evidence.py results/<date>
"""
import glob
import json
import os
import re
import sys

SCRIPTS = ["classify.py", "precheck.py", "simulate_split.py", "daily_page.py", "weekly_report.py"]


def tool_calls(transcript):
    with open(transcript, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (d.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if b.get("type") == "tool_use":
                        yield b.get("name"), b.get("input") or {}


def evidence(transcripts):
    skills, scripts = set(), set()
    for t in transcripts:
        for name, inp in tool_calls(t):
            if name == "Skill" and inp.get("skill"):
                skills.add(inp["skill"])
            if name == "Bash":
                cmd = inp.get("command", "")
                scripts.update(s for s in SCRIPTS if s in cmd)
    return sorted(skills), sorted(scripts)


def main():
    d = sys.argv[1]
    path = os.path.join(d, "runs.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for r in data["runs"]:
        cfg = r.get("config_dir")
        if cfg:
            ts = glob.glob(os.path.join(cfg, "projects", "*", "*.jsonl"))
        else:   # older runs: find the transcript that mentions the workspace
            base = os.path.dirname(r["workspace"])
            ts = [t for t in glob.glob(os.path.join(base, "cc-config-*", "projects", "*", "*.jsonl"))
                  if r["workspace"] in open(t, encoding="utf-8", errors="ignore").read()]
        r["skills_loaded"], r["scripts_run"] = evidence(ts) if ts else (None, None)
        print(r["case"], r["mode"], r["rep"], "skills", r["skills_loaded"], "scripts", r["scripts_run"])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
