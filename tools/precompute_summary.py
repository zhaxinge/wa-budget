#!/usr/bin/env python3
"""
Precompute summary.json from Excel/CSV.

Updated behavior:
- Excel workbooks: reads ALL sheets by default.
- Each sheet is normalized independently because column names may vary by sheet.
- Rows from all valid sheets are combined before VERIFIED_FACTS are computed.

Usage:
  python tools/precompute_summary.py Vendor-Payments_2021-23.xlsx summary.json
  python tools/precompute_summary.py vendor_payments.csv summary.json
  python tools/precompute_summary.py Vendor-Payments.xlsx summary.json --sheets "2021,2022"
"""

import sys, json, re, argparse
from pathlib import Path
import pandas as pd

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

def read_sheets(path, selected_sheets=None):
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return {"CSV": pd.read_csv(path)}

    if suffix in [".xlsx", ".xls"]:
        # sheet_name=None reads all sheets into a dict
        sheets = pd.read_excel(path, sheet_name=None, engine=None)

        if selected_sheets:
            wanted = [s.strip() for s in selected_sheets.split(",") if s.strip()]
            missing = [s for s in wanted if s not in sheets]
            if missing:
                raise ValueError(f"Requested sheet(s) not found: {missing}. Available sheets: {list(sheets.keys())}")
            sheets = {name: sheets[name] for name in wanted}

        return sheets

    raise ValueError("Use .xlsx, .xls, or .csv")

def normalize_sheet(df, sheet_name):
    cols = list(df.columns)

    vendor_col = find_col(cols, ["vendor","payee","supplier","company","name"])
    agency_col = find_col(cols, ["agency","department","dept","organization"])
    amount_col = find_col(cols, ["amount","payment","paid","total","sum","dollar","value"])
    fund_col = find_col(cols, ["fund","funding","source","type","category"])
    year_col = find_col(cols, ["year","fiscal","fy","period","date"])

    if not vendor_col or not amount_col:
        return pd.DataFrame(), {
            "sheet": sheet_name,
            "status": "skipped",
            "reason": "missing vendor or amount column",
            "detected_columns": {
                "vendor": vendor_col,
                "agency": agency_col,
                "amount": amount_col,
                "fund": fund_col,
                "year": year_col,
            },
            "available_columns": [str(c) for c in cols[:25]]
        }

    out = pd.DataFrame()
    out["vendor"] = df[vendor_col].astype(str).str.strip()
    out["agency"] = df[agency_col].astype(str).str.strip() if agency_col else "Unknown"
    out["fund"] = df[fund_col].astype(str).str.strip() if fund_col else "Unknown"

    amount_series = (
        df[amount_col].astype(str)
        .str.replace(r"[$,\s]", "", regex=True)
        .replace({"": "0", "nan": "0", "None": "0"})
    )
    out["amount"] = pd.to_numeric(amount_series, errors="coerce").fillna(0)

    if year_col:
        yr = df[year_col].astype(str).str.extract(r"(\d{4})", expand=False)
        out["fy"] = pd.to_numeric(yr, errors="coerce").fillna(0).astype(int)
    else:
        # Fallback: infer year from sheet name if possible
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

    return out, {
        "sheet": sheet_name,
        "status": "included",
        "raw_rows": int(before),
        "valid_rows": int(len(out)),
        "detected_columns": {
            "vendor": str(vendor_col),
            "agency": str(agency_col) if agency_col else None,
            "amount": str(amount_col),
            "fund": str(fund_col) if fund_col else None,
            "year": str(year_col) if year_col else None,
        }
    }

def group(data, field, total, limit=None):
    g = data.groupby(field, dropna=False)["amount"].sum().sort_values(ascending=False)
    if limit:
        g = g.head(limit)
    return [
        {"name": str(k), "amount": float(v), "amount_formatted": fmt(v), "share_percent": pct(v,total)}
        for k,v in g.items()
    ]

def build_summary(data, input_path, sheet_reports):
    total = float(data["amount"].sum())
    years = sorted([int(y) for y in data["fy"].unique() if int(y) > 1900])

    totals_by_year = []
    for y in years:
        amt = float(data.loc[data["fy"].eq(y), "amount"].sum())
        totals_by_year.append({
            "year": y,
            "amount": amt,
            "amount_formatted": fmt(amt),
            "share_percent": pct(amt,total)
        })

    growth = []
    if len(years) >= 2:
        first, last = years[0], years[-1]
        pivot = data.pivot_table(index="vendor", columns="fy", values="amount", aggfunc="sum", fill_value=0)
        for vendor, row in pivot.iterrows():
            a0 = float(row.get(first, 0))
            a1 = float(row.get(last, 0))
            change = a1 - a0
            growth.append({
                "vendor": str(vendor),
                "first_year": first,
                "first_amount": a0,
                "first_amount_formatted": fmt(a0),
                "last_year": last,
                "last_amount": a1,
                "last_amount_formatted": fmt(a1),
                "absolute_change": change,
                "absolute_change_formatted": fmt(abs(change)),
                "direction": "increase" if change >= 0 else "decrease",
                "pct_change": round((change/a0)*100) if a0 else None
            })
        growth.sort(key=lambda x: x["absolute_change"], reverse=True)

    top_vendor = group(data, "vendor", total, 1)[0] if len(data) else {}
    top_agency = group(data, "agency", total, 1)[0] if len(data) else {}
    fund_breakdown = group(data, "fund", total)

    # Useful for multi-sheet audit
    rows_by_sheet = (
        data.groupby("source_sheet")["amount"]
        .agg(["count", "sum"])
        .sort_values("sum", ascending=False)
        .reset_index()
    )
    sheet_totals = [
        {
            "sheet": str(r["source_sheet"]),
            "valid_rows": int(r["count"]),
            "amount": float(r["sum"]),
            "amount_formatted": fmt(r["sum"]),
            "share_percent": pct(r["sum"], total)
        }
        for _, r in rows_by_sheet.iterrows()
    ]

    verified = {
        "computed_at_source_file": input_path.name,
        "rule": "AUTHORITATIVE_GROUND_TRUTH. These computed facts are based on all included sheets in the input dataset and override sample rows.",
        "sheet_reports": sheet_reports,
        "sheet_totals": sheet_totals,
        "included_sheet_count": sum(1 for r in sheet_reports if r.get("status") == "included"),
        "row_count": int(len(data)),
        "total_payments": total,
        "total_payments_formatted": fmt(total),
        "years": years,
        "year_range": f"{years[0]}-{years[-1]}" if years else "unknown",
        "vendor_count": int(data["vendor"].nunique()),
        "agency_count": int(data["agency"].nunique()),
        "top_vendor": top_vendor,
        "top_agency": top_agency,
        "top_fund": fund_breakdown[0] if fund_breakdown else {},
        "totals_by_year": totals_by_year,
        "top_vendors": group(data, "vendor", total, 30),
        "top_agencies": group(data, "agency", total, 20),
        "fund_breakdown": fund_breakdown,
        "fastest_vendor_growth": growth[:20],
        "largest_vendor_decreases": sorted(growth, key=lambda x: x["absolute_change"])[:15]
    }

    sample_rows = data.head(200).to_dict(orient="records")

    return {
        "AI_CONTEXT": {
            "instruction": "Use VERIFIED_FACTS as authoritative ground truth. Use summarized_context and sample_rows only as secondary context. Never recompute full-dataset totals from sample_rows.",
            "VERIFIED_FACTS": verified,
            "summarized_context": {
                "sheet_totals": verified["sheet_totals"],
                "top_vendors": verified["top_vendors"][:15],
                "top_agencies": verified["top_agencies"][:10],
                "fund_breakdown": verified["fund_breakdown"],
                "totals_by_year": verified["totals_by_year"],
                "fastest_vendor_growth": verified["fastest_vendor_growth"][:10]
            },
            "sample_rows_limit": 200,
            "sample_rows": sample_rows
        }
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    parser.add_argument("--sheets", default=None, help='Optional comma-separated sheet names to include, e.g. "2021,2022"')
    args = parser.parse_args()

    input_path = Path(args.input_file)
    output_path = Path(args.output_file)

    sheets = read_sheets(input_path, args.sheets)

    normalized = []
    reports = []

    for sheet_name, df in sheets.items():
        rows, report = normalize_sheet(df, sheet_name)
        reports.append(report)
        if len(rows):
            normalized.append(rows)

    if not normalized:
        raise ValueError(f"No valid payment rows found in any sheet. Sheet reports: {reports}")

    data = pd.concat(normalized, ignore_index=True)

    summary = build_summary(data, input_path, reports)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    vf = summary["AI_CONTEXT"]["VERIFIED_FACTS"]
    print(f"Wrote {output_path}")
    print(f"Included sheets: {vf['included_sheet_count']} / {len(reports)}")
    for s in vf["sheet_totals"]:
        print(f"  - {s['sheet']}: {s['valid_rows']:,} rows, {s['amount_formatted']}")
    print(f"Combined rows: {vf['row_count']:,}")
    print(f"Combined total: {vf['total_payments_formatted']}")

if __name__ == "__main__":
    main()
