import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const ALLOWED_ORIGINS = [
  "https://zhaxinge.github.io",
  "http://localhost:3000",
  "http://localhost:5173",
  "http://127.0.0.1:5500"
];

function setCors(req, res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.includes(origin)) res.setHeader("Access-Control-Allow-Origin", origin);
  else res.setHeader("Access-Control-Allow-Origin", "https://zhaxinge.github.io");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
}

function safeStringify(value, maxChars = 18000) {
  const text = JSON.stringify(value ?? {}, null, 2);
  return text.length > maxChars ? text.slice(0, maxChars) + "\n...[truncated]" : text;
}

export default async function handler(req, res) {
  setCors(req, res);
  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed. Use POST." });
  if (!process.env.ANTHROPIC_API_KEY) return res.status(500).json({ error: "Missing ANTHROPIC_API_KEY on server." });

  try {
    const { question, verifiedFacts } = req.body || {};
    if (!question || typeof question !== "string") return res.status(400).json({ error: "Missing question." });
    if (question.length > 500) return res.status(400).json({ error: "Question is too long." });
    if (!verifiedFacts || typeof verifiedFacts !== "object") return res.status(400).json({ error: "Missing verifiedFacts object." });

    const model = process.env.CLAUDE_MODEL || "claude-3-5-haiku-20241022";

    const systemPrompt = `
You are a careful public-budget data analyst.

The user provided an AI context bundle:
1. VERIFIED_FACTS: authoritative full-dataset computed facts.
2. summarized_context: compact grouped summaries.
3. sample_rows: up to 200 rows for reference only.

Rules:
- VERIFIED_FACTS are the source of truth.
- Never recompute totals, rankings, shares, or growth from sample_rows.
- sample_rows are incomplete and must never override VERIFIED_FACTS.
- Do not invent vendors, agencies, amounts, years, causes, or policy explanations.
- If the facts do not support the question, say the uploaded data does not provide enough detail.
- Use plain English and keep the answer concise.

Return JSON only:
{
  "narrative": "2-4 sentences",
  "highlights": [
    {"label": "short label", "value": "number or text", "context": "brief explanation"}
  ],
  "chartType": "bar" | "line" | "pie" | null,
  "chartTitle": "string or null",
  "chartData": [{"name": "label", "value": number}]
}
`;

    const message = await anthropic.messages.create({
      model,
      max_tokens: 700,
      temperature: 0.1,
      system: systemPrompt,
      messages: [{
        role: "user",
        content: `Question:\n${question}\n\nAI context bundle:\n${safeStringify(verifiedFacts)}`
      }]
    });

    return res.status(200).json({
      answer: message.content?.[0]?.text || "",
      usage: message.usage || null,
      model
    });
  } catch (error) {
    console.error("Claude request failed:", error);
    return res.status(500).json({ error: "Claude request failed.", detail: error?.message || "Unknown error" });
  }
}
