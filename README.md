# WA Budget Lens — Vendor Payment Explorer

**Submission for Golden Analytics Take-Home Challenge**
Washington State Vendor Payments 2021–2023

---

## 1. The problem I set out to solve

Government spending data is public but not legible. A journalist, councilmember, or policy analyst faces the same friction: the data exists as a spreadsheet, and the spreadsheet requires expertise to interrogate.

The specific pain I targeted: **the moment of first contact with a dataset.** Before a user can ask a smart question, they need orientation — a sense of scale, shape, and what's surprising. Without that, even a well-built AI chat interface fails, because the user doesn't know what to ask.

**Why this approach over alternatives:**

A pure AI chatbot front-loads the burden of question-forming onto the user — exactly the wrong design for someone who has never looked at a government budget. A traditional filter/pivot UI still requires data literacy. I chose a two-layer model:

- **Layer 1 — Automatic insight dashboard**: Four pre-computed questions answered the moment data loads, computed directly from the data with no AI involvement. These give any user an immediate foothold: how did spending trend, how is it funded, who are the biggest agencies, who are the biggest vendors.
- **Layer 2 — Natural language Q&A**: Once oriented, users can ask their own questions in plain English and get narrative answers with auto-generated charts.

The pre-built layer is also the fallback. If the AI is unavailable, the dashboard still works. If the user never asks a question, they still leave with four meaningful findings.

---

## 2. Tech and architectural choices

### Stack

Single self-contained HTML file. No build step, no backend, no server dependency beyond two CDN libraries:

- **SheetJS** (`xlsx.full.min.js`) — parses Excel entirely in the browser; no data leaves the user's machine
- **Chart.js** — renders all charts (pre-built and AI-generated)

An AI-powered version adds a call to the **Anthropic Messages API** (`claude-sonnet-4-20250514`). The exported HTML has this section cleanly stripped — the dashboard runs fully without it.

### How it works

```
User pastes URL or drops .xlsx
        ↓
SheetJS parses file in-browser (no upload, no server)
        ↓
Column auto-detection → named terminal state if failed
        ↓
computeVF() → VERIFIED_FACTS ground truth computed from data
        ↓
Data quality bar rendered (rows, columns, years, verified total)
        ↓
Four insight cards + charts rendered from VERIFIED_FACTS
        ↓
[Optional] User asks plain-English question
        ↓
buildSystemPrompt(VF) → VERIFIED_FACTS injected as ground truth
        ↓
API call → claude-sonnet-4-20250514
        ↓
validateResponse() → accuracy check against VERIFIED_FACTS
        ↓
Structured JSON → narrative + highlights + chart rendered
        ↓
All events logged via typed auditLog(AUDIT_EVENT_TYPE, payload)
```

### Data loading

Three input paths:
1. **File drag-and-drop / browse** — most reliable; reads locally in browser
2. **URL input** — auto-converts Google Drive share links to download URLs; fails gracefully on CORS/auth blocks with a named terminal state
3. **Sample data** — embedded representative dataset; clearly flagged throughout the UI

### Verification-first architecture

The most important structural decision: **the AI never operates on unverified data.**

Before every AI query, `computeVF()` computes VERIFIED_FACTS directly from the loaded dataset — total spend, top vendor, top agency, fund breakdown, year-by-year trend. These are injected verbatim into the system prompt as authoritative ground truth:

```
VERIFIED GROUND TRUTH — computed directly from the dataset.
These are authoritative. Do not contradict them:
  Total vendor payments: $28.4B
  Top vendor: Molina Healthcare of WA ($6.5B)
  Top agency: Health Care Authority ($16.1B)
  ...
```

The AI is instructed to defer to these figures and say "I don't have that detail" rather than estimate for anything outside the verified set. A post-response validator then checks whether any dollar figure cited in the AI's narrative deviates more than 20% from the computed total (for total-spend questions), flagging the response with a visible warning and an audit log entry if so.

### Named terminal states

Every failure path terminates in a named state with a user-visible message and a machine-readable label for monitoring:

| State | Trigger | User action |
|-------|---------|-------------|
| `URL_BLOCKED` | CORS / auth failure on URL fetch | Download and drag-drop instead |
| `COLS_UNDETECTED` | No vendor or amount column found | Shows detected headers |
| `NO_VALID_ROWS` | File parsed but 0 valid rows | Shows row count and filter criteria |
| `AI_UNAVAILABLE` | API timeout or network error | Dashboard remains; retry option shown |
| `AI_FORMAT_ERROR` | AI returned unparseable JSON | Shows raw narrative; suppresses chart |

### Audit logging

All events use a typed enum rather than freeform strings, making logs queryable without schema drift:

```javascript
const AUDIT = {
  DATA_LOAD_ATTEMPT, DATA_LOAD_SUCCESS, DATA_LOAD_ERROR,
  TERMINAL_STATE,
  AI_QUERY_INPUT, AI_QUERY_OUTPUT, AI_QUERY_ERROR,
  AI_FORMAT_ERROR, AI_ACCURACY_FLAG,
};
```

Every entry includes: `ts`, `session`, `env`, `type`, and event-specific payload (question text, row count, token usage, verified total, flagged figures).

In production: `auditLog()` POSTs to `/api/v1/audit` → SIEM or data warehouse. Six monitoring metrics with defined review/pause thresholds and owner assignments are documented in `QA-REVIEW.md`.

### Explicit trade-offs

**Trade-off 1: Browser-only XLSX parsing vs. server-side ingestion**
SheetJS in the browser avoids any data-in-transit risk and keeps the POC dependency-free. It breaks above ~50MB and cannot handle password-protected files. Production fix: server-side ETL with schema validation and a column mapping UI for non-standard headers.

**Trade-off 2: AI decides chart type vs. hardcoded views**
The AI returns `chartType: "bar" | "line" | "pie" | null` based on the question. Flexible, but non-deterministic. The VERIFIED_FACTS injection reduces poor choices by giving the AI a clear sense of available data. Production fix: constrain chart config to a validated schema with a fallback renderer.

**Trade-off 3: Text summary context vs. row-level SQL**
The AI reasons over pre-aggregated VERIFIED_FACTS plus up to 200 sample rows. Cannot accurately answer row-level filter questions. Production fix: in-browser DuckDB or a backend query layer where the AI generates SQL and executes it against the actual data.

**Trade-off 4: console.log audit vs. persistent store**
The POC logs to console with a structured, typed schema. No one is reading these logs in real time. Production fix: POST to an audit endpoint on every event; feed a monitoring dashboard with the six metrics defined in the QA review.

### What I explicitly deferred

- Server-side XLSX ingestion and schema validation
- Column mapping UI for non-standard headers
- Persistent query history and saved views
- Drill-down from pre-built charts (click agency → filter all views)
- PDF export, shareable links
- Automated regression test suite (30-case manual battery documented in QA-REVIEW.md)
- Production API key management and per-org rate limiting

---

## 3. What would change before shipping

| Area | POC | Production |
|------|-----|------------|
| API key | Sandbox proxy | Backend-managed, per-org rotation |
| Audit log | `console.log` | POST to endpoint → SIEM/warehouse |
| Monitoring | None | 6 metrics with thresholds and owner assignments |
| Data ingestion | Browser SheetJS | Server-side ETL with validation |
| Column detection | Auto-detect or named error | Auto-detect + manual mapping UI fallback |
| Auth | None | SSO via org identity provider |
| File size | ~20MB browser limit | Server-side streaming parse |
| AI accuracy check | Total-spend heuristic | Full figure extraction + verified facts cross-check |
| Test coverage | Manual only | 30-case battery across 5 dimensions (QA-REVIEW.md) |

---

## 4. AI usage log

### Interaction 1 — Initial interaction model
**Asked:** What's the right first-screen design for a non-technical government data explorer?

**Got:** Lead with a chat input; let the user ask their first question immediately.

**Kept / changed / rejected:** Rejected. Non-technical users don't know what to ask until they've seen something. A blank chat box is paralyzing. I redirected to a two-layer model: pre-built orientation first (computed from data, no AI), then open-ended AI Q&A. This became the core product decision and means the dashboard works even if the AI is unavailable.

---

### Interaction 2 — Data context strategy
**Asked:** How should I pass Excel data to the AI? Should I send all rows?

**Got:** Send all rows as a CSV string in the user message.

**Kept / changed / rejected:** Changed. Sending all raw rows bloats the context and fails on large files. I changed to pre-compute `VERIFIED_FACTS` from the data and inject them as authoritative ground truth in the system prompt, then send a summarized context plus up to 200 sample rows. This also solves a correctness problem: the AI defers to computed figures rather than reasoning from raw text.

---

### Interaction 3 — AI response schema
**Asked:** What JSON structure should the AI return for narrative + highlights + chart in one response?

**Got:** A nested schema with a `data` array and `visualization` sub-object with many optional fields.

**Kept / changed / rejected:** Simplified. Nested optional fields create more `AI_FORMAT_ERROR` failure modes. I flattened to four top-level fields: `narrative`, `highlights`, `chartType`, `chartData`. Tighter schema means more reliable parsing and fewer format errors.

---

### Interaction 4 — QA framework review
**Asked:** Evaluate the build against a structured AI QA framework: multi-dimensional test battery, executable criteria, verification-first architecture, post-deployment monitoring, governance loops.

**Got:** Gap analysis identifying three structural problems — no AI output verification, undefined failure states, and audit logging that existed in form only.

**Kept / changed / rejected:** Kept all three findings. Implemented: `computeVF()` + system prompt injection (verification-first architecture), named terminal state constants with typed handlers (eliminates ambiguous failure paths), typed `AUDIT_EVENTS` enum (queryable logs), and a post-response accuracy validator. The QA review also produced `QA-REVIEW.md` with the full 30-case test battery, six monitoring metrics with thresholds and owner assignments, and a manual review protocol.

---

## Files

| File | Purpose |
|------|---------|
| `wa-budget-lens.html` | Full export — data loader, data quality bar, pre-built dashboard, named terminal states, typed audit logging. AI Q&A stripped; dashboard works without it. |
| `README.md` | This document |
| `QA-REVIEW.md` | Full QA gap analysis: 30-case test battery, monitoring metrics with thresholds, governance protocols, priority order |

> **Restoring AI Q&A:** Integrate `claude-sonnet-4-20250514`, inject `computeVF()` output into the system prompt as ground truth, implement the `auditLog()` POST endpoint, and apply the accuracy validator before rendering any AI response.

---

## What I'd build next

1. **Column mapping UI** — when auto-detection fails, show a simple dropdown rather than a hard stop
2. **Drill-down from pre-built charts** — click any bar to filter the full dashboard to that agency or vendor
3. **Year-over-year anomaly flagging** — surface vendors whose payments changed by more than 2× automatically, without the user having to ask
4. **In-browser DuckDB** — replace text-summary AI context with real SQL execution; the AI generates the query, DuckDB runs it, accuracy improves dramatically
5. **Saved question library** — bookmark useful queries shared across the org, building institutional knowledge over time
