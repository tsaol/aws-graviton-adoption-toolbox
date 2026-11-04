#!/usr/bin/env python3
"""Draw the replay results (agent with vs without the toolbox) as two static SVGs
(light and dark) for the README. Reads replay-bench/results/<run>/scores.json.

Usage: python3 tools/make_chart.py results/2026-11-04-r2 ../assets
Palette: validated two-slot categorical (blue, orange); light and dark steps.
"""
import html
import json
import os
import sys

THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e4e3df",
              "with": "#2a78d6", "without": "#eb6834"},
    "dark": {"surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "grid": "#383835",
             "with": "#3987e5", "without": "#d95926"},
}
CASE_LABEL = {"ice-two-causes": "Two causes mixed", "ice-after-release": "ICE after reservation release"}
PANELS = [("fact_score", "Rubric facts covered"), ("numbers_ok", "Key numbers right")]


def bar(x, y, w, h, r, fill):
    """Bar anchored at x (baseline, square), rounded only at the data end (right)."""
    r = min(r, w / 2, h / 2)
    if w <= 0:
        return ""
    return (f'<path d="M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z" fill="{fill}"/>')


def svg(summary, t, title):
    W, H = 900, 236
    cases = ["ice-two-causes", "ice-after-release"]
    val = {(s["case"], s["mode"]): s for s in summary}
    label_w, pad, top = 210, 24, 92
    panel_w = (W - label_w - pad * 3) / 2
    scale_w = panel_w - 44          # leave room for the value label after a full bar
    bar_h, gap, group_gap = 18, 2, 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="-apple-system, \'Segoe UI\', Helvetica, Arial, sans-serif" role="img" aria-label="{html.escape(title)}">',
           f'<rect width="{W}" height="{H}" rx="12" fill="{t["surface"]}"/>',
           f'<text x="{pad}" y="34" fill="{t["ink"]}" font-size="17" font-weight="700">{html.escape(title)}</text>',
           f'<text x="{pad}" y="56" fill="{t["ink2"]}" font-size="12.5">Claude Code + Opus 5.5, 2 runs per case and mode, synthetic data, judged by Opus 5.5 on Bedrock</text>']
    # legend
    lx = W - pad - 290
    for i, (mode, name) in enumerate([("with", "With the toolbox"), ("without", "Without")]):
        x = lx + i * 160
        out.append(f'<rect x="{x}" y="24" width="12" height="12" rx="3" fill="{t[mode]}"/>')
        out.append(f'<text x="{x + 18}" y="34.5" fill="{t["ink"]}" font-size="12.5">{name}</text>')
    for p, (key, ptitle) in enumerate(PANELS):
        x0 = label_w + pad + p * (panel_w + pad)
        out.append(f'<text x="{x0}" y="{top - 14}" fill="{t["ink"]}" font-size="13" font-weight="600">{ptitle}</text>')
        for g in (0, 0.5, 1.0):
            gx = x0 + g * scale_w
            out.append(f'<line x1="{gx:.1f}" y1="{top - 4}" x2="{gx:.1f}" y2="{H - 34}" stroke="{t["grid"]}" stroke-width="1"/>')
            out.append(f'<text x="{gx:.1f}" y="{H - 18}" fill="{t["ink2"]}" font-size="11" text-anchor="middle">{g:g}</text>')
        for c, case in enumerate(cases):
            gy = top + c * (2 * bar_h + gap + group_gap)
            if p == 0:
                out.append(f'<text x="{pad}" y="{gy + bar_h + 5}" fill="{t["ink"]}" font-size="13">{CASE_LABEL[case]}</text>')
            for m, mode in enumerate(("with", "without")):
                v = val[(case, mode)][key] or 0
                y = gy + m * (bar_h + gap)
                w = v * scale_w
                out.append(f'<g><title>{CASE_LABEL[case]}, {"with" if mode == "with" else "without"} the toolbox: {v:.2f}</title>'
                           + bar(x0, y, w, bar_h, 4, t[mode])
                           + f'<text x="{x0 + w + 6:.1f}" y="{y + 13}" fill="{t["ink"]}" font-size="12" font-weight="{600 if mode == "with" else 400}">{v:.2f}</text></g>')
        out.append(f'<line x1="{x0}" y1="{top - 4}" x2="{x0}" y2="{H - 34}" stroke="{t["ink2"]}" stroke-width="1"/>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    res, outdir = sys.argv[1], sys.argv[2]
    with open(os.path.join(res, "scores.json"), encoding="utf-8") as fh:
        summary = json.load(fh)["summary"]
    os.makedirs(outdir, exist_ok=True)
    for name, t in THEMES.items():
        p = os.path.join(outdir, f"replay-results-{name}.svg")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(svg(summary, t, "Same agent, same task: with vs without the toolbox"))
        print(p)


if __name__ == "__main__":
    main()
