#!/usr/bin/env python3
"""Render the summary from classify.py as a one-page HTML rollout report."""
import argparse
import html
import json


def render(s, title):
    def tr(cells, tag="td"):
        return "<tr>" + "".join(f"<{tag}>{html.escape(str(c))}</{tag}>" for c in cells) + "</tr>"
    parts = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>",
             "<style>body{font-family:sans-serif;max-width:1000px;margin:24px auto}"
             "table{border-collapse:collapse;margin:8px 0 20px}td,th{border:1px solid #ccc;padding:4px 8px}"
             "th{background:#f3f3f3}.flag{background:#fff3cd}</style>",
             f"<h1>{html.escape(title)}</h1>",
             f"<p>Window {html.escape(str(s['window']['first']))} to {html.escape(str(s['window']['last']))} (UTC); "
             f"records {s['records_raw']}, after dedupe {s['records_after_dedupe']}.</p>",
             "<h2>Instances by result</h2><table>", tr(["bucket", "instances"], "th")]
    for k, v in sorted(s["instances_by_bucket"].items()):
        parts.append(tr([k, v]))
    parts.append("</table><h2>Per night</h2><table>")
    parts.append(tr(["night", "type", "AZ", "launched", "capacity err", "quota err", "other err"], "th"))
    for n in s["nights"]:
        parts.append(tr([n["night"], n["instanceType"], n["availabilityZone"], n["launched"],
                         n["capacity"], n["quota"], n["other"]]))
    parts.append("</table>")
    if s["capacity_vs_snapshot_flags"]:
        parts.append("<h2>Capacity errors while the snapshot shows free capacity</h2><table class='flag'>")
        parts.append(tr(["time", "type", "AZ", "free in snapshot", "errors within 30 min"], "th"))
        for f in s["capacity_vs_snapshot_flags"]:
            parts.append(tr([f["time"], f["instanceType"], f["availabilityZone"],
                             f["free_in_snapshot"], f["capacity_errors_within_30min"]]))
        parts.append("</table>")
    if s["reservation_events"]:
        parts.append("<h2>Capacity reservation events</h2><table>")
        parts.append(tr(["time", "event", "type", "AZ", "count"], "th"))
        for r in s["reservation_events"]:
            parts.append(tr([r["time"], r["event"], r["instanceType"], r["availabilityZone"], r["instanceCount"]]))
        parts.append("</table>")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("summary", help="JSON from classify.py")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--title", default="Graviton rollout: daily launch report")
    a = ap.parse_args(argv)
    with open(a.summary, encoding="utf-8") as fh:
        s = json.load(fh)
    with open(a.output, "w", encoding="utf-8") as fh:
        fh.write(render(s, a.title))


if __name__ == "__main__":
    main()
