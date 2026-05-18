#!/usr/bin/env python3
"""
Precompute a small summary.json from a large Excel/CSV file.

Usage:
  python tools/precompute_summary.py Vendor-Payments.xlsx summary.json
  python tools/precompute_summary.py vendor_payments.csv summary.json
"""

import sys, json, re
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
    return round((a/b)*100) if b else 0

def clean_col(c):
    return re.sub(r"[^a-z0-9 ]", "", str(c).lower())

def find_col(cols, keywords):
    clean = {c: clean_col(c) for c in cols}
    for c, cc in clean.items():
        if any(k in cc for k in keywords):
            return c
    return None

def read_file(path):
    suffix = path.suffix.lower()
    if suffix in [".xlsx", ".xls"]:
        return pd.read_excel(path, sheet_name=0, engine=None)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError("Use .xlsx, .xls, or .csv")

def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/precompute_summary.py input.xlsx summary.json")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    df = read_file(input_path)
    cols = list(df.columns)

    vendor_col = find_col(cols, ["vendor","payee","supplier","company","name"])
    agency_col = find_col(cols, ["agency","department","dept","organization"])
    amount_col = find_col(cols, ["amount","payment","paid","total","sum","dollar","value"])
    fund_col = find_col(cols, ["fund","funding","source","type","category"])
    year_col = find_col(cols, ["year","fiscal","fy","period","date"])

    if not vendor_col or not amount_col:
        raise ValueError(f"Could not detect vendor/amount columns. Columns found: {cols[:20]}")

    data = pd.DataFrame()
    data["vendor"] = df[vendor_col].astype(str).str.strip()
    data["agency"] = df[agency_col].astype(str).str.strip() if agency_col else "Unknown"
    data["fund"] = df[fund_col].astype(str).str.strip() if fund_col else "Unknown"
    data["amount"] = (
        df[amount_col].astype(str)
        .str.replace(r"[$,\s]", "", regex=True)
        .replace({"": "0", "nan": "0", "None": "0"})
        .astype(float)
    )

    if year_col:
        yr = df[year_col].astype(str).str.extract(r"(\d{4})", expand=False)
        data["fy"] = pd.to_numeric(yr, errors="coerce").fillna(0).astype(int)
    else:
        data["fy"] = 0

    data = data[(data["vendor"].ne("")) & (data["vendor"].ne("nan")) & (data["amount"] > 0)].copy()

    total = float(data["amount"].sum())
    years = sorted([int(y) for y in data["fy"].unique() if int(y) > 1900])

    def group(field, limit=None):
        g = data.groupby(field, dropna=False)["amount"].sum().sort_values(ascending=False)
        if limit:
            g = g.head(limit)
        return [
            {"name": str(k), "amount": float(v), "amount_formatted": fmt(v), "share_percent": pct(v,total)}
            for k,v in g.items()
        ]

    totals_by_year = []
    for y in years:
        amt = float(data.loc[data["fy"].eq(y), "amount"].sum())
        totals_by_year.append({"year": y, "amount": amt, "amount_formatted": fmt(amt), "share_percent": pct(amt,total)})

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

    top_vendor = group("vendor", 1)[0] if len(data) else {}
    top_agency = group("agency", 1)[0] if len(data) else {}
    fund_breakdown = group("fund")

    verified = {
        "computed_at_source_file": input_path.name,
        "rule": "AUTHORITATIVE_GROUND_TRUTH. These computed facts are based on the full input dataset and override sample rows.",
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
        "top_vendors": group("vendor", 30),
        "top_agencies": group("agency", 20),
        "fund_breakdown": fund_breakdown,
        "fastest_vendor_growth": growth[:20],
        "largest_vendor_decreases": sorted(growth, key=lambda x: x["absolute_change"])[:15]
    }

    sample_rows = data.head(200).to_dict(orient="records")

    summary = {
        "AI_CONTEXT": {
            "instruction": "Use VERIFIED_FACTS as authoritative ground truth. Use summarized_context and sample_rows only as secondary context. Never recompute full-dataset totals from sample_rows.",
            "VERIFIED_FACTS": verified,
            "summarized_context": {
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

    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} from {len(data):,} rows")
    print(f"Total: {fmt(total)}")

if __name__ == "__main__":
    main()
