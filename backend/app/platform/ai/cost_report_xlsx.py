"""Part 33: the cost report (cost_report.build) as an Excel workbook - used by
scripts/ai_cost_report.py, the Gate A report in docs/reports/ and the "Export cost report (Excel)"
button on AI Intelligence > Usage. `extra_sheets` adds sheets as plain rows (the Gate A report's
pricing / Bedrock tables)."""

from io import BytesIO
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.platform.ai.cost_report import UNIT_LABELS, headline

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
EST_FILL = PatternFill("solid", fgColor="FFF2CC")
TITLE = Font(bold=True, size=14)


def _sheet(wb, title: str, header: list, rows: list, *, estimate_col: Optional[int] = None, widths: Optional[dict] = None):
    ws = wb.create_sheet(title[:31])
    ws.append(header)
    for cell in ws[1]:
        cell.font, cell.fill = HEAD, HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in rows:
        ws.append(row)
        if estimate_col is not None and row[estimate_col] == "estimate":
            for cell in ws[ws.max_row]:
                cell.fill = EST_FILL
    for i, h in enumerate(header, start=1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(h, max(12, min(40, len(str(h)) + 4)))
    ws.freeze_panes = "A2"
    return ws


def _stat_row(label: str, source: str, u: dict) -> list:
    models = ", ".join(f"{m} ({n})" for m, n in u["models"].items())
    return [label, source, u["samples"], "estimate" if u["estimate"] else "measured", u["inr"]["median"], u["inr"]["p90"], u["inr"]["min"],
            u["inr"]["avg"], u["usd"]["median"], u["usd"]["p90"], u["calls_per_sample"], u["tokens_in_median"], u["tokens_out_median"],
            models, u["unpriced_calls"]]


STAT_HEADER = ["Unit", "Source", "Samples", "Estimate?", "Median Rs", "p90 Rs", "Min Rs", "Average Rs", "Median USD", "p90 USD",
               "Calls per unit", "Median tokens in", "Median tokens out", "Model (calls)", "Unpriced calls"]


def to_xlsx(report: dict, *, title: str = "AI cost report", extra_sheets: Optional[list] = None, notes: Optional[list] = None,
            headline_rows: Optional[list] = None) -> bytes:
    """`headline_rows` ([label, Rs, USD, samples, "measured"/"estimate"/"modelled", source]) replaces the automatic
    headline (median per resume / job / hire from the source with more samples)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([title])
    ws["A1"].font = TITLE
    ws.append([f"Period: {report.get('since') or '-'} to {report.get('until') or '-'}"])
    ws.append([f"Companies: {', '.join(report.get('companies') or []) or '-'}"])
    ws.append([f"Prices: ai.pricing re-applied to every call's tokens; 1 USD = Rs {report.get('usd_to_inr')}"])
    ws.append([])
    ws.append(["Headline (median)", "Rs", "USD", "Samples", "Estimate?", "Source"])
    for cell in ws[ws.max_row]:
        cell.font, cell.fill = HEAD, HEAD_FILL
    if headline_rows is not None:
        for row in headline_rows:
            ws.append(list(row))
    else:
        for unit, h in headline(report).items():
            ws.append([f"Per {unit}"] + ([h["inr"], h["usd"], h["samples"], "estimate" if h["estimate"] else "measured", h["source"]] if h else ["no data"]))
    ws.append([])
    ws.append(["Source", "Calls", "Total Rs", "Total USD"])
    for cell in ws[ws.max_row]:
        cell.font, cell.fill = HEAD, HEAD_FILL
    for name, s in report["sources"].items():
        ws.append([name, s["calls"], s["total_inr"], s["total_usd"]])
    ws.append([])
    ws.append(["Excluded", "Calls", "Rs", "USD"])
    for cell in ws[ws.max_row]:
        cell.font, cell.fill = HEAD, HEAD_FILL
    for reason, e in (report.get("excluded") or {}).items():
        ws.append([reason, e["calls"], e["inr"], e["usd"]])
    if not report.get("excluded"):
        ws.append(["(nothing excluded)"])
    ws.append([])
    if report.get("unpriced_models"):
        ws.append([f"Models with no price in ai.pricing (counted as Rs 0): {', '.join(report['unpriced_models'])}"])
    ws.append([f"'estimate' = fewer than {report.get('estimate_below', 20)} samples behind the number."])
    for line in notes or []:
        ws.append([line])
    ws.column_dimensions["A"].width = 44
    for col in "BCDEF":
        ws.column_dimensions[col].width = 14

    unit_rows, agent_rows, driver_rows = [], [], []
    for name, s in report["sources"].items():
        for unit, u in s["units"].items():
            unit_rows.append(_stat_row(UNIT_LABELS.get(unit, unit), name, u))
        for agent, u in s["agents"].items():
            agent_rows.append(_stat_row(agent, name, u))
        for d in s["drivers"]:
            driver_rows.append([name, d["feature"], d["model"], d["calls"], d["avg_in"], d["avg_out"], d["inr_per_call"], d["inr"], d["usd"], d["unpriced_calls"]])
    _sheet(wb, "Per unit", STAT_HEADER, unit_rows, estimate_col=3, widths={"Unit": 30, "Model (calls)": 36})
    _sheet(wb, "Per agent run", STAT_HEADER, agent_rows, estimate_col=3, widths={"Unit": 28, "Model (calls)": 36})
    _sheet(wb, "Cost drivers", ["Source", "Feature", "Model", "Calls", "Avg tokens in", "Avg tokens out", "Rs per call", "Total Rs", "Total USD",
                                "Unpriced calls"], driver_rows, widths={"Feature": 32, "Model": 22})
    for sheet in extra_sheets or []:
        _sheet(wb, sheet["title"], sheet["header"], sheet["rows"], widths=sheet.get("widths"))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
