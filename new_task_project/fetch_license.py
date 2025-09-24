#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
On-demand license fetcher.

- Reuses gather()/render_html() from license_monitor.py
- Prints a concise table or JSON to stdout
- Also updates the HTML and CSV outputs (like a one-shot run)

Usage examples:
  python3 new_task_project/fetch_license.py --features Innovus_Impl_System
  python3 new_task_project/fetch_license.py --features Innovus_Impl_System,Another --format json
  python3 new_task_project/fetch_license.py --out license_usage.html --csv license_usage.csv --once

Note: If parsing shows '?' for values, share a sample of `ckout_test -f <FEATURE>` output so we can
extend the regex patterns to match your environment.
"""

import argparse
import json
import os
import sys
from typing import List

# Local import from the same folder
from license_monitor import gather, render_html, append_csv


def print_table(rows: List[dict]):
    # Determine column widths
    headers = ["Feature", "Used", "Unused", "Total", "Status", "Updated"]
    display_rows = []
    for r in rows:
        used = r["used"] if r["used"] is not None else "?"
        total = r["total"] if r["total"] is not None else "?"
        unused = r["unused"] if r["unused"] is not None else ("?" if r["total"] is not None else "?")
        if r["total"] is None or r["used"] is None:
            status = "Unknown parse"
        elif r["used"] < r["total"]:
            status = "OK"
        elif r["used"] == r["total"]:
            status = "Fully used"
        else:
            status = "Over-reported"
        display_rows.append([
            r["feature"], str(used), str(unused), str(total), status, r["timestamp"],
        ])

    cols = list(zip(*([headers] + display_rows))) if display_rows else []
    widths = [max(len(str(cell)) for cell in col) for col in cols] if cols else [8]*len(headers)

    def fmt(row):
        return "  ".join(str(cell).ljust(w) for cell, w in zip(row, widths))

    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    for row in display_rows:
        print(fmt(row))


def main():
    ap = argparse.ArgumentParser(description="Fetch and display license usage on demand.")
    ap.add_argument("--features", type=str, default="Innovus_Impl_System,Genus_Synthesis",
                    help="Comma-separated list of features")
    ap.add_argument("--out", type=str, default="license_usage.html", help="Output HTML file")
    ap.add_argument("--csv", type=str, default="license_usage.csv", help="CSV log file")
    ap.add_argument("--title", type=str, default="License Usage Monitor", help="HTML page title")
    ap.add_argument("--format", choices=["table", "json", "summary"], default="summary",
                    help="Output format to stdout")
    args = ap.parse_args()

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    if not features:
        print("No features provided.", file=sys.stderr)
        sys.exit(2)

    # Gather current snapshot
    rows = gather(features)

    # Persist outputs (HTML + CSV) so the frontend can load them if needed
    html_text = render_html(rows, args.title)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_text)
    append_csv(args.csv, rows)

    # Print to stdout for CLI/automation
    if args.format == "json":
        # Strip raw outputs to keep it concise
        slim = [{
            "feature": r["feature"],
            "used": r["used"],
            "unused": r["unused"],
            "total": r["total"],
            "timestamp": r["timestamp"],
            "rc": r["rc"],
            "error": r["stderr"],
        } for r in rows]
        print(json.dumps({"licenses": slim}, indent=2))
    elif args.format == "summary":
        # Print concise summary like: "You have X license(s) in use out of Y"
        # If totals are unknown, fall back gracefully.
        total_known = [r for r in rows if r["total"] is not None]
        used_known = [r for r in rows if r["used"] is not None]
        sum_total = sum(r["total"] for r in total_known) if total_known else None
        sum_used = sum(r["used"] for r in used_known) if used_known else None

        if sum_used is not None and sum_total is not None:
            print(f"You have {sum_used} license(s) in use out of {sum_total} total.")
        elif sum_used is not None:
            print(f"You have {sum_used} license(s) in use.")
        else:
            print("You have ? license(s) in use.")

        # Also list each feature on a single line for clarity
        for r in rows:
            used = r["used"] if r["used"] is not None else "?"
            total = r["total"] if r["total"] is not None else "?"
            print(f"- {r['feature']}: {used}/{total} in use")
    else:
        print_table(rows)

    # Helpful hint if parsing failed
    any_unknown = any(r["used"] is None or r["total"] is None for r in rows)
    if any_unknown:
        print("\nNote: One or more values could not be parsed (shown as '?').", file=sys.stderr)
        print("If possible, share sample output of `ckout_test -f <FEATURE>` so we can refine parsing.", file=sys.stderr)


if __name__ == "__main__":
    # Ensure scripts are run from repo root, but still work anywhere
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)