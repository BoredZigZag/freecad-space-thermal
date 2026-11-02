# SPDX-License-Identifier: MIT OR Apache-2.0
"""Local campaign execution and report generation."""
from html import escape
import json
from pathlib import Path

from fcst_app.campaign import read_json, report_campaign, run_campaign
from fcst_app.persistence import reject


def parsers(commands):
    run = commands.add_parser("campaign-run")
    run.add_argument("thermal_input")
    run.add_argument("specification")
    run.add_argument("directory")
    run.add_argument("--worker", required=True)
    run.add_argument("--transient", help="JSON transient settings")
    report = commands.add_parser("campaign-report")
    report.add_argument("directory")
    report.add_argument("limits")
    report.add_argument("--html", help="Create a human-readable report at a new path")


def html_report(report):
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>Thermal campaign</title>",
             "<h1>Thermal campaign</h1>"]
    fit = report["correlation"]
    if fit and fit["status"] == "complete":
        parts.append("<h2>Measured and predicted temperatures (K)</h2>")
        traces = [[row[key] for row in rows] for rows, key in (
            (fit["baseline"], "measured_K"), (fit["baseline"], "predicted_K"),
            (fit["fitted"], "predicted_K"))]
        low, high = min(map(min, traces)), max(map(max, traces))
        parts.append("<p>Observation order from the table. Black is measured, orange is baseline, blue is fitted.</p>")
        parts.append("<svg viewBox='0 0 640 210' width='640' role='img' aria-label='Sensor temperature comparisons'>")
        for values, color in zip(traces, ("black", "darkorange", "royalblue")):
            for index, value in enumerate(values):
                x = 15 + 610 * index / (len(values) - 1)
                y = 195 - 180 * (value - low) / (high - low or 1)
                parts.append(f"<circle cx='{x:.4f}' cy='{y:.4f}' r='3' fill='{color}'/>")
        parts.append("</svg>")
        parts.append("<table><thead><tr><th>Sensor</th><th>Time (s)</th><th>Split</th>"
                     "<th>Measured</th><th>Baseline</th><th>Fitted</th></tr></thead><tbody>")
        for baseline, fitted in zip(fit["baseline"], fit["fitted"]):
            row = baseline["observation"]
            values = (row["sensor"], row["time_s"], row["split"], baseline["measured_K"],
                      baseline["predicted_K"], fitted["predicted_K"])
            parts.append("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in values) + "</tr>")
        parts.append("</tbody></table>")
    parts.extend(("<h2>Run and report evidence</h2><pre>",
                  escape(json.dumps(report, indent=2, sort_keys=True)), "</pre></html>"))
    return "\n".join(parts)


def execute(args):
    try:
        if args.command == "campaign-run":
            return run_campaign(read_json(args.thermal_input), read_json(args.specification), args.directory,
                                args.worker, transient=read_json(args.transient) if args.transient else None)
        report = report_campaign(args.directory, read_json(args.limits))
    except (KeyError, TypeError, AttributeError, IndexError):
        reject("campaign_document")
    if args.html:
        with Path(args.html).open("x", encoding="utf-8") as stream:
            stream.write(html_report(report))
    return report
