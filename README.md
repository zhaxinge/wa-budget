# Budget Lens - Agentic BI Demo for Public Vendor Payment Data

Budget Lens is a browser-based BI prototype that turns public-style Washington vendor payment data into verified KPIs, stakeholder-specific lenses, guided questions, and grounded AI follow-up answers.

The demo is designed around a simple principle: data quality first, AI second. Instead of asking users to begin with a blank chatbot, Budget Lens first provides computed metrics and guided analysis. The AI layer then answers follow-up questions from a constrained context bundle built from those verified facts.

## Why this project matters

Budget Lens demonstrates an agentic BI workflow for decision-making:

1. Precompute full-dataset facts from a large Excel or CSV source.
2. Orient users with verified KPIs and stakeholder-specific lenses.
3. Offer guided questions before open-ended AI analysis.
4. Ground AI answers in an auditable, compact context bundle.

This approach makes the experience easier to audit, safer for non-technical users, and more reliable than asking a model to infer totals from a small sample of raw rows.

## Responsible AI design

- `VERIFIED_FACTS` are treated as the authoritative source of truth.
- Sample rows provide secondary context and cannot override computed metrics.
- The model is instructed not to invent vendors, agencies, amounts, years, causes, or policy explanations.
- Large source files are summarized before AI analysis to improve reliability and browser performance.
- The provider API key is stored only in the server environment; the public UI never requests or exposes it.

## Demo features

- Overview, journalist, and transportation-investor lenses
- Full-dataset KPIs and transportation-specific metrics
- Guided stakeholder questions and plain-English follow-up Q&A
- Precomputed summaries for large workbook support
- Server-side AI endpoint with constrained prompting

The included workbook and embedded sample are representative/public demo data and are not internal operational data.

## Trust architecture

```text
Public vendor payment data
        |
        v
Precompute and validate full-dataset metrics
        |
        v
VERIFIED_FACTS + compact summaries + limited sample rows
        |
        v
Stakeholder lenses and constrained AI Q&A
```

The backend prompt explicitly treats `VERIFIED_FACTS` as authoritative and prevents incomplete `sample_rows` from overriding them. The transportation lens also reads its metrics from full-dataset precomputed facts when `summary.json` is available.

## Run locally

Serve the repository with any local static server, then open `index.html`. The app loads the precomputed `summary.json` demo automatically and can also accept Excel or CSV files.

To regenerate the summary:

```powershell
py -3.11 tools/precompute_summary.py Vendor-Payments_2021-23.xlsx summary.json
```

This writes both `summary.json` (verified facts for KPIs and AI) and `vendor-payments.json` (~193 MB, all 934k+ rows for the browser demo). The rows file is gitignored; generate it locally after cloning.

For AI Q&A, deploy `api/ask.js` as a serverless endpoint and set the provider API key and model name in the server environment. The browser calls the backend endpoint; it does not receive the provider key.

## Repository structure

```text
wa-budget/
|-- index.html
|-- summary.json
|-- vendor-payments.json
|-- package.json
|-- api/
|   |-- ask.js
|   `-- process-data.js
`-- tools/
    `-- precompute_summary.py
```

## Scope

Budget Lens is a portfolio prototype, not an official Washington State reporting product. The transportation classification uses documented keyword and vendor-pattern rules and should be reviewed before use in production analysis.
