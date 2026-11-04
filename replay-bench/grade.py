#!/usr/bin/env python3
"""Grade replay runs and write report.md + report.html + scores.json.

Two layers:
1. Script check: are the key numbers of each fact present in the answer?
2. Model judge (Amazon Bedrock): per fact covered / partly / missing, and which
   wrong claims the answer makes. The judge sees only the rubric and the answer,
   not which mode produced it.

Needs boto3 and Bedrock access. Usage: python3 grade.py results/<date>
"""
import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import statistics as st

import boto3
from botocore.config import Config

HERE = os.path.dirname(os.path.abspath(__file__))
JUDGE = os.environ.get("JUDGE_MODEL", "jp.anthropic.claude-opus-5-5")
JUDGE_REGION = os.environ.get("JUDGE_REGION", "ap-northeast-1")

PROMPT = """You are grading an answer to an AWS EC2 capacity troubleshooting task against a rubric.
Be strict and literal. A fact is "covered" only if the answer states it correctly and clearly;
"partly" if it is mentioned but incomplete or vague; "missing" otherwise. A wrong claim counts only
if the answer actually makes it (as advice or as a conclusion).

RUBRIC (JSON):
{rubric}

ANSWER:
<<<
{answer}
>>>

Reply with ONLY JSON:
{{"facts": {{"F1": "covered|partly|missing", ...}}, "wrong_claims": ["W1", ...], "notes": "one or two sentences"}}"""


def judge(rubric, answer):
    c = boto3.client("bedrock-runtime", region_name=JUDGE_REGION,
                     config=Config(read_timeout=600, retries={"max_attempts": 4}))
    r = c.converse(modelId=JUDGE, messages=[{"role": "user", "content": [{"text": PROMPT.format(
        rubric=json.dumps(rubric, ensure_ascii=False, indent=1), answer=answer[:60000])}]}],
        inferenceConfig={"maxTokens": 2000})
    text = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
    return json.loads(re.search(r"\{.*\}", text, re.S).group(0))


def number_check(rubric, answer):
    flat = answer.replace(",", "")
    out = {}
    for f in rubric["facts"]:
        nums = f.get("numbers") or []
        out[f["id"]] = None if not nums else all(re.search(r"(?<![\d.])" + re.escape(n) + r"(?![\d])", flat) for n in nums)
    return out


def grade_run(run):
    with open(os.path.join(HERE, "cases", run["case"], "answer.json"), encoding="utf-8") as fh:
        rubric = json.load(fh)
    ans = run["answer"] or ""
    pts = {"covered": 1.0, "partly": 0.5, "missing": 0.0}
    if not ans.strip():
        j = {"facts": {f["id"]: "missing" for f in rubric["facts"]}, "wrong_claims": [], "notes": "no answer"}
    else:
        j = judge(rubric, ans)
    score = sum(pts.get(j["facts"].get(f["id"], "missing"), 0) for f in rubric["facts"]) / len(rubric["facts"])
    return dict(case=run["case"], mode=run["mode"], rep=run["rep"], fact_score=round(score, 3),
                facts=j["facts"], wrong_claims=j.get("wrong_claims", []), notes=j.get("notes", ""),
                numbers=number_check(rubric, ans), wall_seconds=run["wall_seconds"],
                num_turns=run["num_turns"], cost_usd=run["cost_usd"], returncode=run["returncode"],
                skills_loaded=run.get("skills_loaded"), scripts_run=run.get("scripts_run"))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 3) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    a = ap.parse_args()
    with open(os.path.join(a.results_dir, "runs.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    with cf.ThreadPoolExecutor(8) as ex:
        graded = list(ex.map(grade_run, data["runs"]))
    graded.sort(key=lambda g: (g["case"], g["mode"], g["rep"]))
    groups = {}
    for g in graded:
        groups.setdefault((g["case"], g["mode"]), []).append(g)
    summary = []
    for (case, mode), gs in sorted(groups.items()):
        summary.append(dict(case=case, mode=mode, runs=len(gs),
                            fact_score=mean([g["fact_score"] for g in gs]),
                            wrong_claims=mean([len(g["wrong_claims"]) for g in gs]),
                            numbers_ok=mean([mean([1.0 if v else 0.0 for v in g["numbers"].values() if v is not None]) for g in gs]),
                            wall_seconds=mean([g["wall_seconds"] for g in gs]),
                            num_turns=mean([g["num_turns"] for g in gs]),
                            cost_usd=mean([g["cost_usd"] for g in gs])))
    out = dict(model=data["model"], judge=JUDGE, date=data["date"], summary=summary, graded=graded)
    with open(os.path.join(a.results_dir, "scores.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    write_reports(a.results_dir, out)
    for s in summary:
        print(s)


def write_reports(d, out):
    lines = [f"# Replay benchmark results ({out['date'][:10]})", "",
             f"- Agent: Claude Code headless (`claude -p`), model `{out['model']}`, isolated config, same task text in both modes",
             f"- Judge: `{out['judge']}` on Amazon Bedrock, given only the rubric and the answer",
             "- **with** = workspace has the toolbox skills in `.claude/skills/`; **without** = same workspace, no skills",
             "", "## Summary", "",
             "| Case | Mode | Runs | Fact score | Wrong claims / run | Key numbers right | Time (s) | Turns | Cost (USD) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in out["summary"]:
        lines.append(f"| {s['case']} | **{s['mode']}** | {s['runs']} | {s['fact_score']} | {s['wrong_claims']} | {s['numbers_ok']} | {s['wall_seconds']} | {s['num_turns']} | {s['cost_usd']} |")
    lines += ["", "Fact score: covered = 1, partly = 0.5, missing = 0, averaged over the rubric facts. Key numbers right: share of facts whose numbers all appear in the answer.", "", "## Per run", ""]
    for g in out["graded"]:
        wc = ", ".join(g["wrong_claims"]) or "none"
        facts = " ".join(f"{k}:{v[0].upper()}" for k, v in sorted(g["facts"].items()))
        used = "" if g.get("skills_loaded") is None else f" Skills loaded: {', '.join(g['skills_loaded']) or 'none'}; scripts run: {', '.join(g['scripts_run']) or 'none'}."
        lines.append(f"- `{g['case']}` **{g['mode']}** #{g['rep']}: score {g['fact_score']}, facts {facts}, wrong claims {wc}, {g['wall_seconds']} s.{used} {g['notes']}")
    lines += ["", "Answers are in `answers/`. Raw runs in `runs.json`, grades in `scores.json`."]
    md = "\n".join(lines) + "\n"
    with open(os.path.join(d, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    rows = "".join(
        f"<tr><td>{html.escape(s['case'])}</td><td><b>{s['mode']}</b></td><td>{s['runs']}</td><td>{s['fact_score']}</td>"
        f"<td>{s['wrong_claims']}</td><td>{s['numbers_ok']}</td><td>{s['wall_seconds']}</td><td>{s['num_turns']}</td><td>{s['cost_usd']}</td></tr>"
        for s in out["summary"])
    page = ("<!doctype html><meta charset='utf-8'><title>Replay benchmark</title><style>body{font-family:sans-serif;max-width:1000px;margin:24px auto}"
            "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}th{background:#f3f3f3}</style>"
            f"<h1>Replay benchmark results ({out['date'][:10]})</h1><p>Agent model {html.escape(out['model'])}; judge {html.escape(out['judge'])}.</p>"
            "<table><tr><th>Case</th><th>Mode</th><th>Runs</th><th>Fact score</th><th>Wrong claims/run</th><th>Key numbers right</th><th>Time (s)</th><th>Turns</th><th>Cost (USD)</th></tr>"
            f"{rows}</table><pre>{html.escape(md)}</pre>")
    with open(os.path.join(d, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(page)


if __name__ == "__main__":
    main()
