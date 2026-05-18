import Anthropic from "@anthropic-ai/sdk";

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

const ALLOWED_ORIGINS = [
  "https://zhaxinge.github.io",
  "http://localhost:3000",
  "http://localhost:5173",
  "http://127.0.0.1:5500"
];

function setCors(req, res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.includes(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
  } else {
    res.setHeader("Access-Control-Allow-Origin", "https://zhaxinge.github.io");
  }

  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
}

function safeStringify(value, maxChars = 12000) {
  const text = JSON.stringify(value ?? {}, null, 2);
  return text.length > maxChars ? text.slice(0, maxChars) + "\n...[truncated]" : text;
}

export default async function handler(req, res) {
  setCors(req, res);

  if (req.method === "OPTIONS") {
    return res.status(204).end();
  }

  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed. Use POST." });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: "Missing ANTHROPIC_API_KEY on server." });
  }

  try {
    const { question, verifiedFacts } = req.body || {};

    if (!question || typeof question !== "string") {
      return res.status(400).json({ error: "Missing question." });
    }

    if (question.length > 500) {
      return res.status(400).json({ error: "Question is too long. Please keep it under 500 characters." });
    }

    if (!verifiedFacts || typeof verifiedFacts !== "object") {
      return res.status(400).json({ error: "Missing verifiedFacts object." });
    }

    const systemPrompt = `
You are a careful public-budget data analyst.

Rules:
1. Answer only from the verifiedFacts JSON provided by the app.
2. Do not invent vendors, agencies, amounts, years, or explanations.
3. If the verified facts do not support the question, say the uploaded data does not provide enough detail.
4. Use plain English for journalists, policy staff, and the public.
5. Keep the answer concise but useful.
6. When relevant, mention that figures are based on the uploaded/loaded dataset.

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
      model: "claude-sonnet-4-5",
      max_tokens: 700,
      temperature: 0.2,
      system: systemPrompt,
      messages: [
        {
          role: "user",
          content:
            `Question:\n${question}\n\n` +
            `Verified facts from the loaded dataset:\n${safeStringify(verifiedFacts)}`
        }
      ]
    });

    const text = message.content?.[0]?.text || "";

    return res.status(200).json({
      answer: text,
      usage: message.usage || null
    });
  } catch (error) {
    console.error("Claude request failed:", error);
    return res.status(500).json({
      error: "Claude request failed.",
      detail: error?.message || "Unknown error"
    });
  }
}
