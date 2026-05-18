/*
ask-client.js
Frontend helper for WA Budget Lens.

Put this next to index.html and include it before </body>:

<script src="./ask-client.js"></script>

Then set your endpoint below after Vercel deploys your backend.
*/

window.WABudgetAskConfig = {
  endpoint: "https://wa-budget.vercel.app/api/ask",
  maxQuestionsPerSession: 20,
  maxQuestionLength: 500
};

window.WABudgetAskState = {
  questionCount: 0
};

function buildVerifiedFactsForAsk() {
  if (!window.DATA || !Array.isArray(window.DATA) || !window.DATA.length) {
    throw new Error("No data loaded yet.");
  }

  const data = window.DATA;
  const fmt = window.fmt || ((n) => String(n));
  const pct = window.pct || ((a, b) => b ? Math.round(a / b * 100) : 0);

  function groupBy(field) {
    const m = {};
    data.forEach((r) => {
      const key = r[field] || "Unknown";
      m[key] = (m[key] || 0) + Number(r.amount || 0);
    });
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }

  const total = data.reduce((s, r) => s + Number(r.amount || 0), 0);
  const years = [...new Set(data.map((r) => r.fy).filter((y) => y > 1900))].sort();

  const byVendor = groupBy("vendor");
  const byAgency = groupBy("agency");
  const byFund = groupBy("fund");

  const yearlyTotals = years.map((year) => ({
    year,
    amount: data
      .filter((r) => r.fy === year)
      .reduce((s, r) => s + Number(r.amount || 0), 0)
  }));

  const vendorGrowth = byVendor.slice(0, 30).map(([vendor]) => {
    const firstYear = years[0];
    const lastYear = years[years.length - 1];

    const first = data
      .filter((r) => r.vendor === vendor && r.fy === firstYear)
      .reduce((s, r) => s + Number(r.amount || 0), 0);

    const last = data
      .filter((r) => r.vendor === vendor && r.fy === lastYear)
      .reduce((s, r) => s + Number(r.amount || 0), 0);

    return {
      vendor,
      firstYear,
      firstAmount: first,
      lastYear,
      lastAmount: last,
      change: last - first,
      pctChange: first ? Math.round(((last - first) / first) * 100) : null
    };
  }).sort((a, b) => b.change - a.change).slice(0, 10);

  return {
    rowCount: data.length,
    totalPayments: total,
    totalPaymentsFormatted: fmt(total),
    years,
    yearlyTotals,
    topVendors: byVendor.slice(0, 10).map(([name, amount]) => ({
      name,
      amount,
      amountFormatted: fmt(amount),
      sharePercent: pct(amount, total)
    })),
    topAgencies: byAgency.slice(0, 10).map(([name, amount]) => ({
      name,
      amount,
      amountFormatted: fmt(amount),
      sharePercent: pct(amount, total)
    })),
    fundBreakdown: byFund.map(([name, amount]) => ({
      name,
      amount,
      amountFormatted: fmt(amount),
      sharePercent: pct(amount, total)
    })),
    fastestVendorGrowth: vendorGrowth
  };
}

async function askBudgetQuestion(question) {
  const cfg = window.WABudgetAskConfig;

  if (!cfg.endpoint || cfg.endpoint.includes("YOUR-VERCEL-PROJECT")) {
    throw new Error("Please set your Vercel /api/ask endpoint in ask-client.js.");
  }

  if (window.WABudgetAskState.questionCount >= cfg.maxQuestionsPerSession) {
    throw new Error("Session question limit reached. Refresh the page or add login/rate limits for production.");
  }

  if (!question || !question.trim()) {
    throw new Error("Please enter a question.");
  }

  if (question.length > cfg.maxQuestionLength) {
    throw new Error(`Question is too long. Please keep it under ${cfg.maxQuestionLength} characters.`);
  }

  const verifiedFacts = buildVerifiedFactsForAsk();

  const response = await fetch(cfg.endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      question,
      verifiedFacts
    })
  });

  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(payload.error || payload.detail || `Request failed: ${response.status}`);
  }

  window.WABudgetAskState.questionCount += 1;
  return payload;
}

window.askBudgetQuestion = askBudgetQuestion;
window.buildVerifiedFactsForAsk = buildVerifiedFactsForAsk;
