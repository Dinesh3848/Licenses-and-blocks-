#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Periodically runs license checks via `ckout_test -f <FEATURE>` and updates an HTML
summary table and a CSV log every N seconds (default 300 = 5 minutes).

Assumptions:
- Your command template is: ckout_test -f <FEATURE>
- Provide features via --features or it defaults to Innovus_Impl_System
- Output is parsed heuristically. Adjust regexes if your output differs.

Usage examples:
  python3 license_monitor.py --once
  python3 license_monitor.py --features Innovus_Impl_System,Another_Feature --interval 300
  python3 license_monitor.py --out license_usage.html --csv license_usage.csv

To customize per-team counting, share a sample `ckout_test` output so we can
extend the parser to attribute usage to specific users/hosts.
"""

import argparse
import csv
import datetime as dt
import html
import os
import re
import subprocess
import sys
import time
import shlex
from typing import Dict, Optional, Tuple, List

# Heuristic parser patterns for typical license outputs
COUNT_PATTERNS = [
    # FlexLM-like: "Total of 25 licenses issued; Total of 5 licenses in use"
    re.compile(r"Total\s+of\s+(\d+)\s+licenses\s+issued;?\s*Total\s+of\s+(\d+)\s+licenses\s+in\s+use", re.I | re.S),
    # "Total licenses: 25 ... In use: 5"
    re.compile(r"Total\s+licenses\s*:\s*(\d+).*?In\s+use\s*:\s*(\d+)", re.I | re.S),
    # "Issued=25 ... Used=5"
    re.compile(r"Issued\s*=\s*(\d+).*?Used\s*=\s*(\d+)", re.I | re.S),
]


def run_ckout(feature: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run the license command for a given feature.

    Supports overriding the command via environment variables:
      - LICENSE_CHECK_CMD or LICENSE_CMD
        Examples:
          LICENSE_CHECK_CMD="ckout_test -f {feature}"
          LICENSE_CHECK_CMD="/path/to/wrapper.sh {feature}"
          LICENSE_CHECK_CMD="lmutil lmstat -f {feature} -c 27000@server"
        If {feature} is not present, the feature name will be appended.
    """
    env_cmd = os.environ.get("LICENSE_CHECK_CMD") or os.environ.get("LICENSE_CMD")

    if env_cmd:
        cmd_str = env_cmd
        if "{feature}" in cmd_str:
            cmd_str = cmd_str.replace("{feature}", feature)
            cmd = shlex.split(cmd_str)
        else:
            # No placeholder -> split and append feature as last arg
            cmd = shlex.split(cmd_str) + [feature]
    else:
        # Fallback to default placeholder tool
        cmd = ["ckout_test", "-f", feature]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def parse_usage(output: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parse text output and return (total, used).
    Returns (None, None) if not found.
    """
    for pat in COUNT_PATTERNS:
        m = pat.search(output)
        if m:
            total = int(m.group(1))
            used = int(m.group(2))
            return total, used
    # Fallback: try to infer used by counting obvious "in use" lines (heuristic)
    lines = [l.strip() for l in output.splitlines()]
    used_guess = sum(1 for l in lines if re.search(r"\bin\s*use\b", l, re.I))
    if used_guess > 0:
        return None, used_guess
    return None, None


def render_html(rows: List[Dict], title: str) -> str:
    """Render an auto-refresh HTML table."""
    head = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
table {{ border-collapse: collapse; width: 100%; max-width: 1000px; }}
th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
th {{ background: #f7f7f7; }}
.status-ok {{ color: #0a7a0a; font-weight: 600; }}
.status-warn {{ color: #cc7a00; font-weight: 600; }}
.status-err {{ color: #b00020; font-weight: 600; }}
.small {{ color: #666; font-size: 12px; }}
</style>
</head>
<body>
<h2>{html.escape(title)}</h2>
"""
    table_header = """<table>
<thead>
<tr>
  <th>Feature</th>
  <th>Used</th>
  <th>Unused</th>
  <th>Total</th>
  <th>Last Updated</th>
  <th>Status</th>
</tr>
</thead>
<tbody>
"""
    body_rows = []
    for r in rows:
        feature = html.escape(r["feature"])
        used = r["used"]
        total = r["total"]
        unused = r["unused"]
        ts = html.escape(r["timestamp"])

        used_disp = str(used) if used is not None else "?"
        total_disp = str(total) if total is not None else "?"
        unused_disp = str(unused) if unused is not None else ("?" if total is not None else "?")

        # Simple status coloring
        if total is None or used is None:
            status_cls = "status-warn"
            status_text = "Unknown parse"
        elif used < total:
            status_cls = "status-ok"
            status_text = "OK"
        elif used == total:
            status_cls = "status-err"
            status_text = "Fully used"
        else:
            status_cls = "status-warn"
            status_text = "Over-reported"

        body_rows.append(f"""<tr>
  <td>{feature}</td>
  <td>{used_disp}</td>
  <td>{unused_disp}</td>
  <td>{total_disp}</td>
  <td>{ts}</td>
  <td class="{status_cls}">{status_text}</td>
</tr>
""")
    table_footer = "</tbody>\n</table>\n"
    footer = '<p class="small">Auto-refreshes every 5 minutes. Adjust parsing rules in the script if needed.</p>\n</body>\n</html>\n'
    return head + table_header + "".join(body_rows) + table_footer + footer


def ensure_csv_header(csv_path: str):
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "feature", "used", "unused", "total"])


def append_csv(csv_path: str, rows: List[Dict]):
    ensure_csv_header(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        for r in rows:
            writer.writerow([r["timestamp"], r["feature"], r["used"], r["unused"], r["total"]])


def gather(features: List[str]) -> List[Dict]:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = []
    for feat in features:
        rc, out, err = run_ckout(feat)
        total, used = parse_usage(out)
        unused = (total - used) if (total is not None and used is not None) else None
        results.append({
            "feature": feat,
            "total": total,
            "used": used,
            "unused": unused,
            "timestamp": now,
            "rc": rc,
            "stderr": err.strip(),
            "raw": out.strip(),
        })
    return results


def main():
    ap = argparse.ArgumentParser(description="Periodic license usage monitor for ckout_test.")
    ap.add_argument("--features", type=str, default="Innovus_Impl_System,Genus_Synthesis",
                    help="Comma-separated list of features (e.g., Innovus_Impl_System,Genus_Synthesis,Another_Feature)")
    ap.add_argument("--out", type=str, default="license_usage.html", help="Output HTML file")
    ap.add_argument("--csv", type=str, default="license_usage.csv", help="CSV log file")
    ap.add_argument("--title", type=str, default="License Usage Monitor", help="HTML page title")
    ap.add_argument("--interval", type=int, default=300, help="Interval in seconds (default 300 = 5 minutes)")
    ap.add_argument("--once", action="store_true", help="Run once and exit (no loop)")
    args = ap.parse_args()

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    if not features:
        print("No features provided.", file=sys.stderr)
        sys.exit(2)

    # Initial write
    rows = gather(features)
    html_text = render_html(rows, args.title)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_text)
    append_csv(args.csv, rows)
    print(f"Wrote {args.out} and updated {args.csv} @ {rows[0]['timestamp']}")

    if args.once:
        return

    # Loop
    while True:
        time.sleep(max(5, args.interval))
        rows = gather(features)
        html_text = render_html(rows, args.title)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html_text)
        append_csv(args.csv, rows)
        print(f"Wrote {args.out} and updated {args.csv} @ {rows[0]['timestamp']}")


if __name__ == "__main__":
    main()