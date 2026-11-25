"""Part 33.1: AI cost report for every company on this install (read-only).

    python -m scripts.ai_cost_report --since 2026-10-01 --until 2026-11-30 [--company ctd-techs ...]
                                     [--json out.json] [--xlsx out.xlsx]

Reads ai_usage_records (+ the AI decision log, applications, jobs, BGV assignments, separations)
per company and prints cost per resume / JD / job / hire / exit / assistant question / agent run
(min, median, p90, samples, model) in INR and USD. Sandbox companies and proof / test jobs are
left out and counted; Gate A controlled-run rows (module "gate-a-run") are shown apart.
The connection is opened read-only (default_transaction_read_only).
"""

import argparse
import json
import sys
from datetime import date, datetime, time, timezone
from typing import Optional

from app.platform.ai import cost_report as cr


def _companies(only: list) -> list:
    """[(slug, tenant_id, dsn, shared_rls)] for every live company (or the ones named)."""
    from app.platform.tenancy.database_cp import ControlPlaneSessionLocal
    from app.platform.tenancy.models_cp import Tenant
    from app.platform.tenancy.provisioning import admin_dsn_for

    cp = ControlPlaneSessionLocal()
    try:
        rows = [(t.slug, t.id, admin_dsn_for(cp, t), t.isolation == "shared_rls") for t in cp.query(Tenant).filter(Tenant.status != "deleted")]
    finally:
        cp.close()
    return [r for r in rows if not only or r[0] in only]


def links_from_file(path) -> cr.Links:
    """A saved links snapshot ({"jobs": {id: title}, "applications": {id: {job_id, candidate_id}}}) - e.g. the Gate A
    run's, whose test rows were deleted after the run while its AI usage rows were kept."""
    data = json.loads(open(path, encoding="utf-8").read())
    return cr.Links(applications={a: cr.AppLink(v.get("job_id"), v.get("candidate_id"), v.get("status")) for a, v in data.get("applications", {}).items()},
                    jobs=dict(data.get("jobs", {})))


def collect(since: datetime, until: datetime, only: list = (), extra_links: Optional[list] = None) -> dict:
    from sqlalchemy import create_engine, text

    calls, links, sandbox, prices_of = [], cr.Links(), set(), {}
    for path in extra_links or []:
        links.merge(links_from_file(path))
    engines: dict = {}
    for slug, tenant_id, dsn, _shared in _companies(list(only)):
        if cr.SANDBOX_COMPANY.search(slug):
            sandbox.add(slug)
        engine = engines.setdefault(dsn, create_engine(dsn))
        with engine.connect() as conn:
            conn.execute(text("SET default_transaction_read_only = on"))
            calls += cr.load_calls(conn, tenant_id, slug, since, until)
            links.merge(cr.load_links(conn, tenant_id))
            prices_of[slug] = cr.load_prices(conn, tenant_id)
    for engine in engines.values():
        engine.dispose()
    # one price table for the whole report: the first real company's (a sandbox's settings are test settings)
    real = [s for s in prices_of if s not in sandbox]
    prices = prices_of[real[0]] if real else next(iter(prices_of.values()), cr.Prices(pricing={}))
    return cr.build(calls, links, prices, sandbox_companies=sandbox, since=since, until=until)


def _fmt(v, nd=2):
    return "-" if v is None else f"{v:,.{nd}f}"


def print_report(report: dict, out=sys.stdout) -> None:
    w = lambda s="": print(s, file=out)  # noqa: E731
    w(f"AI cost report {report['since'][:10]} .. {report['until'][:10]}  companies: {', '.join(report['companies']) or '-'}")
    w(f"prices: ai.pricing re-applied to tokens, 1 USD = Rs {report['usd_to_inr']}; 'est' = under {report['estimate_below']} samples")
    for reason, e in report["excluded"].items():
        w(f"excluded ({reason}): {e['calls']} calls, Rs {_fmt(e['inr'])}")
    if report["unpriced_models"]:
        w(f"no price for: {', '.join(report['unpriced_models'])}")
    for name, s in report["sources"].items():
        w()
        w(f"== {name}: {s['calls']} calls, Rs {_fmt(s['total_inr'])} (USD {_fmt(s['total_usd'], 4)})")
        if not s["calls"]:
            continue
        w(f"  {'unit':32} {'n':>4} {'':4} {'min':>8} {'median':>8} {'p90':>8} {'med USD':>9} {'calls':>6} {'tok in':>7} {'tok out':>7}  model")
        for label, u in [(cr.UNIT_LABELS[k], v) for k, v in s["units"].items()] + [(k, v) for k, v in s["agents"].items()]:
            if not u["samples"]:
                w(f"  {label:32} {0:>4}")
                continue
            w(f"  {label:32} {u['samples']:>4} {'est' if u['estimate'] else '':4} {_fmt(u['inr']['min']):>8} {_fmt(u['inr']['median']):>8} "
              f"{_fmt(u['inr']['p90']):>8} {_fmt(u['usd']['median'], 4):>9} {_fmt(u['calls_per_sample'], 1):>6} {_fmt(u['tokens_in_median'], 0):>7} "
              f"{_fmt(u['tokens_out_median'], 0):>7}  {', '.join(u['models'])}")
    w()
    for unit, h in cr.headline(report).items():
        w(f"per {unit}: " + (f"Rs {_fmt(h['inr'])} median ({h['samples']} samples, {h['source']}{', estimate' if h['estimate'] else ''})" if h else "no data"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ai_cost_report")
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--until", type=date.fromisoformat, required=True)
    parser.add_argument("--company", action="append", default=[], help="company slug (repeatable); default: all")
    parser.add_argument("--links", action="append", default=[], help="saved links snapshot (e.g. docs/samples/gate_a/run_links.json)")
    parser.add_argument("--json")
    parser.add_argument("--xlsx")
    args = parser.parse_args(argv)
    since = datetime.combine(args.since, time.min, tzinfo=timezone.utc)
    until = datetime.combine(args.until, time.max, tzinfo=timezone.utc)
    report = collect(since, until, args.company, args.links)
    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
    if args.xlsx:
        from app.platform.ai.cost_report_xlsx import to_xlsx

        with open(args.xlsx, "wb") as fh:
            fh.write(to_xlsx(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
