import Anthropic from "@anthropic-ai/sdk";
import { setCors } from "./cors.js";

const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

function safeStringify(value, maxChars = 18000) {
  const text = JSON.stringify(value ?? {}, null, 2);
  return text.length > maxChars ? text.slice(0, maxChars) + "\n...[truncated]" : text;
}

function extractJsonObject(text) {
  const start = text.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

function parseAIResponse(text) {
  const raw = String(text || "").trim();
  if (!raw) {
    return { narrative: "No response.", highlights: [], chartType: null, chartTitle: null, chartData: [] };
  }

  const fenceMatch = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const jsonText = fenceMatch ? fenceMatch[1].trim() : extractJsonObject(raw);
  const tail = fenceMatch ? raw.slice(fenceMatch.index + fenceMatch[0].length).trim() : "";

  if (jsonText) {
    try {
      const parsed = JSON.parse(jsonText);
      if (tail) {
        const extra = tail.replace(/\*\*([^*]+)\*\*/g, "$1").trim();
        if (extra) parsed.narrative = [parsed.narrative, extra].filter(Boolean).join("\n\n");
      }
      return parsed;
    } catch {}
  }

  return { narrative: raw, highlights: [], chartType: null, chartTitle: null, chartData: [] };
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

    const model = process.env.CLAUDE_MODEL;

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

Return ONLY a single JSON object. No markdown fences, no prose before or after the JSON.
chartData values must be in millions of dollars (e.g. 471 for $471M).

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

    const answerText = message.content?.[0]?.text || "";
    const parsed = parseAIResponse(answerText);

    return res.status(200).json({
      ...parsed,
      answer: answerText,
      usage: message.usage || null,
      model
    });
  } catch (error) {
    console.error("Claude request failed:", error);
    return res.status(500).json({ error: "Claude request failed.", detail: error?.message || "Unknown error" });
  }
}
