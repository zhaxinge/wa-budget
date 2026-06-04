import * as XLSX from "xlsx";

export const config = { api: { bodyParser: false } };

const ALLOWED_ORIGINS = [
  "https://zhaxinge.github.io"
];

function isAllowedOrigin(origin) {
  if (ALLOWED_ORIGINS.includes(origin)) return true;
  return /^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?$/.test(origin || "");
}

function setCors(req, res) {
  const origin = req.headers.origin;
  if (isAllowedOrigin(origin)) res.setHeader("Access-Control-Allow-Origin", origin);
  else res.setHeader("Access-Control-Allow-Origin", "https://zhaxinge.github.io");
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-File-Name");
}

async function readRawBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  return Buffer.concat(chunks);
}

function fmt(n) {
  n = Number(n || 0);
  if (n >= 1e9) return "$" + (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return "$" + Math.round(n / 1e6).toLocaleString() + "M";
  return "$" + Math.round(n).toLocaleString();
}

function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }
function cleanCol(c) { return String(c || "").toLowerCase().replace(/[^a-z0-9 ]/g, ""); }
function findCol(headers, keywords) { return headers.find(h => keywords.some(kw => cleanCol(h).includes(kw))) || null; }
function parseAmount(v) {
  const n = parseFloat(String(v ?? "0").replace(/[$,\s]/g, ""));
  return Number.isFinite(n) ? n : 0;
}
function parseYear(v) {
  const m = String(v ?? "").match(/\d{4}/);
  return m ? parseInt(m[0], 10) : 0;
}
function inferYearFromSheetName(name) {
  const m = String(name || "").match(/(20\d{2}|19\d{2})/);
  return m ? parseInt(m[1], 10) : 0;
}

function normalizeRows(json, sheetName) {
  if (!json.length) {
    return { rows: [], report: { sheet: sheetName, status: "skipped", reason: "empty sheet" } };
  }

  const headers = Object.keys(json[0]);
  const vendorCol = findCol(headers, ["vendor", "payee", "supplier", "company", "name"]);
  const agencyCol = findCol(headers, ["agency", "department", "dept", "organization"]);
  const amountCol = findCol(headers, ["amount", "payment", "paid", "total", "sum", "dollar", "value"]);
  const fundCol = findCol(headers, ["fund", "funding", "source", "type", "category"]);
  const yearCol = findCol(headers, ["year", "fiscal", "fy", "period", "date"]);

  if (!vendorCol || !amountCol) {
    return {
      rows: [],
      report: {
        sheet: sheetName,
        status: "skipped",
        reason: "missing vendor or amount column",
        detected_columns: { vendor: vendorCol, agency: agencyCol, amount: amountCol, fund: fundCol, year: yearCol },
        available_columns: headers.slice(0, 25)
      }
    };
  }

  const inferredYear = inferYearFromSheetName(sheetName);

  const rows = json.map(r => ({
    vendor: String(r[vendorCol] ?? "").trim(),
    agency: agencyCol ? String(r[agencyCol] ?? "Unknown").trim() : "Unknown",
    fund: fundCol ? String(r[fundCol] ?? "Unknown").trim() : "Unknown",
    fy: yearCol ? parseYear(r[yearCol]) : inferredYear,
    amount: parseAmount(r[amountCol]),
    source_sheet: String(sheetName)
  })).filter(r => r.vendor && r.vendor !== "Unknown" && r.vendor.toLowerCase() !== "nan" && r.amount > 0);

  return {
    rows,
    report: {
      sheet: sheetName,
      status: "included",
      raw_rows: json.length,
      valid_rows: rows.length,
      detected_columns: { vendor: vendorCol, agency: agencyCol, amount: amountCol, fund: fundCol, year: yearCol }
    }
  };
}

function group(rows, field, total, limit = null) {
  const m = new Map();
  rows.forEach(r => m.set(r[field] || "Unknown", (m.get(r[field] || "Unknown") || 0) + r.amount));
  let arr = [...m.entries()].sort((a, b) => b[1] - a[1]);
  if (limit) arr = arr.slice(0, limit);
  return arr.map(([name, amount]) => ({ name: String(name), amount, amount_formatted: fmt(amount), share_percent: pct(amount, total) }));
}

function buildSummary(rows, sourceFile, sheetReports) {
  const total = rows.reduce((s, r) => s + r.amount, 0);
  const years = [...new Set(rows.map(r => r.fy).filter(y => y > 1900))].sort((a, b) => a - b);

  const topVendors = group(rows, "vendor", total, 30);
  const topAgencies = group(rows, "agency", total, 20);
  const fundBreakdown = group(rows, "fund", total, null);

  const totalsByYear = years.map(year => {
    const amount = rows.filter(r => r.fy === year).reduce((s, r) => s + r.amount, 0);
    return { year, amount, amount_formatted: fmt(amount), share_percent: pct(amount, total) };
  });

  const sheetMap = new Map();
  rows.forEach(r => sheetMap.set(r.source_sheet, (sheetMap.get(r.source_sheet) || 0) + r.amount));
  const sheetTotals = [...sheetMap.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([sheet, amount]) => ({
      sheet,
      amount,
      amount_formatted: fmt(amount),
      share_percent: pct(amount, total),
      valid_rows: rows.filter(r => r.source_sheet === sheet).length
    }));

  const vendorMap = new Map();
  rows.forEach(r => {
    if (!vendorMap.has(r.vendor)) vendorMap.set(r.vendor, new Map());
    const ymap = vendorMap.get(r.vendor);
    ymap.set(r.fy, (ymap.get(r.fy) || 0) + r.amount);
  });

  let growth = [];
  if (years.length >= 2) {
    const firstYear = years[0], lastYear = years[years.length - 1];
    for (const [vendor, ymap] of vendorMap.entries()) {
      const firstAmount = ymap.get(firstYear) || 0;
      const lastAmount = ymap.get(lastYear) || 0;
      const change = lastAmount - firstAmount;
      growth.push({
        vendor,
        first_year: firstYear,
        first_amount: firstAmount,
        first_amount_formatted: fmt(firstAmount),
        last_year: lastYear,
        last_amount: lastAmount,
        last_amount_formatted: fmt(lastAmount),
        absolute_change: change,
        absolute_change_formatted: fmt(Math.abs(change)),
        direction: change >= 0 ? "increase" : "decrease",
        pct_change: firstAmount ? Math.round((change / firstAmount) * 100) : null
      });
    }
    growth.sort((a, b) => b.absolute_change - a.absolute_change);
  }

  const verified = {
    computed_at: new Date().toISOString(),
    computed_at_source_file: sourceFile,
    rule: "AUTHORITATIVE_GROUND_TRUTH. These computed facts are based on all included sheets in the uploaded workbook and override sample rows.",
    sheet_reports: sheetReports,
    sheet_totals: sheetTotals,
    included_sheet_count: sheetReports.filter(r => r.status === "included").length,
    row_count: rows.length,
    total_payments: total,
    total_payments_formatted: fmt(total),
    years,
    year_range: years.length ? `${years[0]}-${years[years.length - 1]}` : "unknown",
    vendor_count: new Set(rows.map(r => r.vendor)).size,
    agency_count: new Set(rows.map(r => r.agency)).size,
    top_vendor: topVendors[0] || {},
    top_agency: topAgencies[0] || {},
    top_fund: fundBreakdown[0] || {},
    totals_by_year: totalsByYear,
    top_vendors: topVendors,
    top_agencies: topAgencies,
    fund_breakdown: fundBreakdown,
    fastest_vendor_growth: growth.slice(0, 20),
    largest_vendor_decreases: [...growth].sort((a, b) => a.absolute_change - b.absolute_change).slice(0, 15)
  };

  return {
    AI_CONTEXT: {
      instruction: "Use VERIFIED_FACTS as authoritative ground truth. Use summarized_context and sample_rows only as secondary context. Never recompute full-dataset totals from sample_rows.",
      VERIFIED_FACTS: verified,
      summarized_context: {
        sheet_totals: verified.sheet_totals,
        top_vendors: verified.top_vendors.slice(0, 15),
        top_agencies: verified.top_agencies.slice(0, 10),
        fund_breakdown: verified.fund_breakdown,
        totals_by_year: verified.totals_by_year,
        fastest_vendor_growth: verified.fastest_vendor_growth.slice(0, 10)
      },
      sample_rows_limit: 200,
      sample_rows: rows.slice(0, 200)
    }
  };
}

function parseFile(buffer, filename) {
  const lower = filename.toLowerCase();
  const rows = [];
  const reports = [];

  if (lower.endsWith(".csv")) {
    const text = buffer.toString("utf8");
    const wb = XLSX.read(text, { type: "string" });
    const sheet = wb.Sheets[wb.SheetNames[0]];
    const json = XLSX.utils.sheet_to_json(sheet, { defval: null, raw: false });
    const parsed = normalizeRows(json, "CSV");
    rows.push(...parsed.rows);
    reports.push(parsed.report);
  } else {
    const wb = XLSX.read(buffer, { type: "buffer" });
    for (const sheetName of wb.SheetNames) {
      const sheet = wb.Sheets[sheetName];
      const json = XLSX.utils.sheet_to_json(sheet, { defval: null, raw: false });
      const parsed = normalizeRows(json, sheetName);
      rows.push(...parsed.rows);
      reports.push(parsed.report);
    }
  }

  if (!rows.length) throw new Error(`No valid payment rows found in any sheet. Reports: ${JSON.stringify(reports).slice(0, 1000)}`);
  return { rows, reports };
}

export default async function handler(req, res) {
  setCors(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed. Use POST." });

  try {
    const filename = decodeURIComponent(req.headers["x-file-name"] || "uploaded.xlsx");
    const buffer = await readRawBody(req);
    if (!buffer.length) return res.status(400).json({ error: "Empty upload." });

    const maxBytes = Number(process.env.MAX_UPLOAD_BYTES || 20 * 1024 * 1024);
    if (buffer.length > maxBytes) {
      return res.status(413).json({
        error: `File too large for this deployment. Limit is ${(maxBytes / 1024 / 1024).toFixed(1)} MB.`,
        detail: "Use CSV, reduce the file size, precompute summary.json locally, or move processing to a larger backend."
      });
    }

    const { rows, reports } = parseFile(buffer, filename);
    const summary = buildSummary(rows, filename, reports);
    return res.status(200).json(summary);
  } catch (error) {
    console.error("process-data failed:", error);
    return res.status(500).json({ error: "File processing failed.", detail: error?.message || "Unknown error" });
  }
}
