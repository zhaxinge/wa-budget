#!/usr/bin/env python3
"""
Precompute summary.json from Excel/CSV, including transportation-specific facts.

Key update:
- Reads ALL sheets in an Excel workbook.
- Adds VERIFIED_FACTS["transportation"] so the Transportation Investor lens does not depend on the first 200 sample rows.
- Robust transportation classification from agency, vendor, fund, sheet name, and optional category/program columns.

Usage:
  python tools/precompute_summary.py Vendor-Payments_2021-23.xlsx summary.json
"""

import argparse, json, re
from pathlib import Path
import pandas as pd

TRANSPORT_RE = re.compile(
    r"transport|transportation|wsdot|washington state dot|\bdot\b|department of transportation|dept of transportation|"
    r"highway|roadway|roads?\b|bridge|bridges|traffic|transit|rail|ferry|aviation|airport|toll",
    re.I,
)

CONSTRUCTION_RE = re.compile(
    r"kiewit|graham|flatiron|granite|skanska|walsh|mccarthy|hensel|construction|contracting|contractor|"
    r"infrastructure|paving|asphalt|bridge|road|highway|civil",
    re.I,
)

ENGINEERING_RE = re.compile(
    r"aecom|wsp|jacobs|hntb|parsons|hdr|stantec|mott macdonald|ty lin|kpff|bergerabam|consult|consulting|"
    r"engineer|engineering|design|planning|environmental",
    re.I,
)

def fmt(n):
    n = float(n or 0)
    if n >= 1e9:
        return f"${n/1e9:.1f}B"
    if n >= 1e6:
        return f"${round(n/1e6):,.0f}M"
    return f"${round(n):,.0f}"

def pct(a,b):
    return round((float(a)/float(b))*100) if b else 0

def clean_col(c):
    return re.sub(r"[^a-z0-9 ]", "", str(c).lower())

def find_col(cols, keywords):
    clean = {c: clean_col(c) for c in cols}
    for c, cc in clean.items():
        if any(k in cc for k in keywords):
            return c
    return None

def read_sheets(path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return {"CSV": pd.read_csv(path)}
    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(path, sheet_name=None, engine=None)
    raise ValueError("Use .xlsx, .xls, or .csv")

def is_transport_row(row):
    text = " ".join(str(row.get(c, "")) for c in ["agency", "vendor", "fund", "source_sheet", "category", "program", "description"])
    if TRANSPORT_RE.search(text):
        return True
    # Vendor fallback catches transportation capital contractors/consultants when agency text is too generic.
    vendor = str(row.get("vendor", ""))
    return bool(CONSTRUCTION_RE.search(vendor) or ENGINEERING_RE.search(vendor))

def normalize_sheet(df, sheet_name):
    cols = list(df.columns)
    vendor_col = find_col(cols, ["vendor","payee","supplier","company","business","name"])
    agency_col = find_col(cols, ["agency","agency name","department","dept","organization","org"])
    amount_col = find_col(cols, ["amount","payment","paid","total","sum","dollar","value","expenditure"])
    fund_col = find_col(cols, ["fund","funding","source","fund type","appropriation","account","category"])
    year_col = find_col(cols, ["year","fiscal","fy","period","date"])
    category_col = find_col(cols, ["category","sector","type","class"])
    program_col = find_col(cols, ["program","activity","project","description","service"])

    if not vendor_col or not amount_col:
        return pd.DataFrame(), {
            "sheet": sheet_name,
            "status": "skipped",
            "reason": "missing vendor/payee or amount/payment column",
            "available_columns": [str(c) for c in cols[:30]],
            "detected_columns": {"vendor": vendor_col, "agency": agency_col, "amount": amount_col, "fund": fund_col, "year": year_col}
        }

    out = pd.DataFrame()
    out["vendor"] = df[vendor_col].astype(str).str.strip()
    out["agency"] = df[agency_col].astype(str).str.strip() if agency_col else "Unknown"
    out["fund"] = df[fund_col].astype(str).str.strip() if fund_col else "Unknown"
    out["category"] = df[category_col].astype(str).str.strip() if category_col else ""
    out["program"] = df[program_col].astype(str).str.strip() if program_col else ""

    amount_series = (
        df[amount_col].astype(str)
        .str.replace(r"[$,\s]", "", regex=True)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .replace({"": "0", "nan": "0", "None": "0"})
    )
    out["amount"] = pd.to_numeric(amount_series, errors="coerce").fillna(0)

    if year_col:
        yr = df[year_col].astype(str).str.extract(r"(20\d{2}|19\d{2})", expand=False)
        out["fy"] = pd.to_numeric(yr, errors="coerce").fillna(0).astype(int)
    else:
        m = re.search(r"(20\d{2}|19\d{2})", str(sheet_name))
        out["fy"] = int(m.group(1)) if m else 0

    out["source_sheet"] = str(sheet_name)
    before = len(out)
    out = out[
        (out["vendor"].ne("")) &
        (out["vendor"].str.lower().ne("nan")) &
        (out["vendor"].str.lower().ne("unknown")) &
        (out["amount"] > 0)
    ].copy()

    out["is_transportation"] = out.apply(is_transport_row, axis=1)
    out["transport_work_type"] = out.apply(
        lambda r: "Engineering / consulting" if ENGINEERING_RE.search(str(r["vendor"]) + " " + str(r["program"]))
        else ("Heavy construction" if CONSTRUCTION_RE.search(str(r["vendor"]) + " " + str(r["program"])) else "Other transport"),
        axis=1
    )

    return out, {
        "sheet": sheet_name,
        "status": "included",
        "raw_rows": int(before),
        "valid_rows": int(len(out)),
        "transport_rows": int(out["is_transportation"].sum()),
        "detected_columns": {
            "vendor": str(vendor_col),
            "agency": str(agency_col) if agency_col else None,
            "amount": str(amount_col),
            "fund": str(fund_col) if fund_col else None,
            "year": str(year_col) if year_col else None,
            "category": str(category_col) if category_col else None,
            "program": str(program_col) if program_col else None,
        }
    }

def group(data, field, total, limit=None):
    if data.empty or field not in data:
        return []
    g = data.groupby(field, dropna=False)["amount"].sum().sort_values(ascending=False)
    if limit:
        g = g.head(limit)
    return [{"name": str(k), "amount": float(v), "amount_formatted": fmt(v), "share_percent": pct(v,total)} for k,v in g.items()]

def by_year(data, years, total):
    return [
        {
            "year": int(y),
            "amount": float(data.loc[data["fy"].eq(y), "amount"].sum()),
            "amount_formatted": fmt(data.loc[data["fy"].eq(y), "amount"].sum()),
            "share_percent": pct(data.loc[data["fy"].eq(y), "amount"].sum(), total)
        }
        for y in years
    ]

def vendor_growth(data, years):
    if data.empty or len(years) < 2:
        return []
    first, last = years[0], years[-1]
    pivot = data.pivot_table(index="vendor", columns="fy", values="amount", aggfunc="sum", fill_value=0)
    rows = []
    for vendor, row in pivot.iterrows():
        a0 = float(row.get(first, 0))
        a1 = float(row.get(last, 0))
        change = a1 - a0
        rows.append({
            "vendor": str(vendor),
            "first_year": int(first),
            "first_amount": a0,
            "first_amount_formatted": fmt(a0),
            "last_year": int(last),
            "last_amount": a1,
            "last_amount_formatted": fmt(a1),
            "absolute_change": change,
            "absolute_change_formatted": fmt(abs(change)),
            "direction": "increase" if change >= 0 else "decrease",
            "pct_change": round((change/a0)*100) if a0 else None
        })
    return sorted(rows, key=lambda x: x["absolute_change"], reverse=True)

def build_summary(data, input_path, sheet_reports):
    total = float(data["amount"].sum())
    years = sorted([int(y) for y in data["fy"].unique() if int(y) > 1900])

    transport = data[data["is_transportation"]].copy()
    t_total = float(transport["amount"].sum()) if not transport.empty else 0.0
    t_years = years
    t_by_year = by_year(transport, t_years, t_total)
    t_growth = 0
    if len(t_by_year) >= 2 and t_by_year[0]["amount"]:
        t_growth = round((t_by_year[-1]["amount"] - t_by_year[0]["amount"]) / t_by_year[0]["amount"] * 100)

    work_type = group(transport, "transport_work_type", t_total)
    construction_total = sum(x["amount"] for x in work_type if x["name"] == "Heavy construction")
    engineering_total = sum(x["amount"] for x in work_type if x["name"] == "Engineering / consulting")

    sheet_totals = group(data, "source_sheet", total)
    transport_sheet_totals = group(transport, "source_sheet", t_total)

    verified = {
        "computed_at_source_file": input_path.name,
        "rule": "AUTHORITATIVE_GROUND_TRUTH. Computed from all included workbook sheets. Transportation facts are computed from full data, not sample rows.",
        "sheet_reports": sheet_reports,
        "included_sheet_count": sum(1 for r in sheet_reports if r.get("status") == "included"),
        "sheet_totals": sheet_totals,
        "row_count": int(len(data)),
        "total_payments": total,
        "total_payments_formatted": fmt(total),
        "years": years,
        "year_range": f"{years[0]}-{years[-1]}" if years else "unknown",
        "vendor_count": int(data["vendor"].nunique()),
        "agency_count": int(data["agency"].nunique()),
        "top_vendor": group(data, "vendor", total, 1)[0] if len(data) else {},
        "top_agency": group(data, "agency", total, 1)[0] if len(data) else {},
        "top_fund": group(data, "fund", total, 1)[0] if len(data) else {},
        "totals_by_year": by_year(data, years, total),
        "top_vendors": group(data, "vendor", total, 30),
        "top_agencies": group(data, "agency", total, 20),
        "fund_breakdown": group(data, "fund", total),
        "fastest_vendor_growth": vendor_growth(data, years)[:20],
        "largest_vendor_decreases": sorted(vendor_growth(data, years), key=lambda x: x["absolute_change"])[:15],
        "transportation": {
            "detection_rule": "Rows where agency/vendor/fund/program/category/sheet text matches transportation terms; vendor fallback includes common heavy-civil and engineering firms.",
            "row_count": int(len(transport)),
            "total": t_total,
            "total_formatted": fmt(t_total),
            "share_percent": pct(t_total, total),
            "years": t_years,
            "by_year": t_by_year,
            "growth_percent": t_growth,
            "top_vendors": group(transport, "vendor", t_total, 30),
            "top_agencies": group(transport, "agency", t_total, 20),
            "fund_breakdown": group(transport, "fund", t_total),
            "work_type_breakdown": work_type,
            "construction_total": construction_total,
            "construction_total_formatted": fmt(construction_total),
            "construction_share_percent": pct(construction_total, t_total),
            "engineering_total": engineering_total,
            "engineering_total_formatted": fmt(engineering_total),
            "engineering_share_percent": pct(engineering_total, t_total),
            "vendor_growth": vendor_growth(transport, years)[:20],
            "sheet_totals": transport_sheet_totals
        }
    }

    sample_rows = data.head(200).drop(columns=["is_transportation"], errors="ignore").to_dict(orient="records")

    return {
        "AI_CONTEXT": {
            "instruction": "Use VERIFIED_FACTS as authoritative ground truth. Use summarized_context and sample_rows only as secondary context. Never recompute full-dataset totals from sample_rows.",
            "VERIFIED_FACTS": verified,
            "summarized_context": {
                "top_vendors": verified["top_vendors"][:15],
                "top_agencies": verified["top_agencies"][:10],
                "fund_breakdown": verified["fund_breakdown"],
                "totals_by_year": verified["totals_by_year"],
                "transportation": verified["transportation"]
            },
            "sample_rows_limit": 200,
            "sample_rows": sample_rows
        }
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    normalized = []
    reports = []
    for sheet_name, df in read_sheets(input_path).items():
        rows, report = normalize_sheet(df, sheet_name)
        reports.append(report)
        if len(rows):
            normalized.append(rows)

    if not normalized:
        raise ValueError(f"No valid rows found. Reports: {reports}")

    data = pd.concat(normalized, ignore_index=True)
    summary = build_summary(data, input_path, reports)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    vf = summary["AI_CONTEXT"]["VERIFIED_FACTS"]
    t = vf["transportation"]
    print(f"Wrote {output_path}")
    print(f"Included sheets: {vf['included_sheet_count']} / {len(reports)}")
    for r in reports:
        print(f"  - {r['sheet']}: {r.get('valid_rows',0):,} valid rows, {r.get('transport_rows',0):,} transport rows")
    print(f"Combined rows: {vf['row_count']:,}")
    print(f"Combined total: {vf['total_payments_formatted']}")
    print(f"Transportation rows: {t['row_count']:,}")
    print(f"Transportation total: {t['total_formatted']} ({t['share_percent']}% of total)")
    if t["top_vendors"]:
        print("Top transport vendors:")
        for v in t["top_vendors"][:5]:
            print(f"  - {v['name']}: {v['amount_formatted']}")

if __name__ == "__main__":
    main()
