#!/usr/bin/env python3
"""Check that every action in iam/readonly-policy.json exists and is Read or List only,
using the public AWS service authorization reference. Needs internet access."""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.path.join(os.path.dirname(HERE), "iam", "readonly-policy.json")


def level(props):
    if props.get("IsWrite"):
        return "write"
    if props.get("IsPermissionManagement"):
        return "permissions"
    if props.get("IsTaggingOnly"):
        return "tagging"
    return "list" if props.get("IsList") else "read"


def main():
    with open(POLICY, encoding="utf-8") as fh:
        pol = json.load(fh)
    idx = json.load(urllib.request.urlopen("https://servicereference.us-east-1.amazonaws.com/", timeout=60))
    urls = {x["service"]: x["url"] for x in idx}
    cache, bad = {}, []
    for st in pol["Statement"]:
        for a in st["Action"]:
            svc, name = a.split(":")
            if svc not in cache:
                d = json.load(urllib.request.urlopen(urls[svc], timeout=60))
                cache[svc] = {x["Name"]: x for x in d["Actions"]}
            x = cache[svc].get(name)
            lv = level(x.get("Annotations", {}).get("Properties", {})) if x else "NOT FOUND"
            print(f"{a:45s} {lv}")
            if lv not in ("read", "list"):
                bad.append(a)
    print("RESULT:", "PASS: all actions exist and are read/list only" if not bad else f"FAIL: {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
