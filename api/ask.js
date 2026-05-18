// Vercel-style serverless endpoint for WA Budget Lens AI Q&A.
// Put this file at api/ask.js and set ANTHROPIC_API_KEY in your hosting environment.
// The browser calls /api/ask; your Claude key stays on the server.

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      return res.status(500).json({ error: 'Missing ANTHROPIC_API_KEY environment variable.' });
    }

    const body = req.body || {};
    const system = String(body.system || '').slice(0, 12000);
    const userPrompt = String(body.user_prompt || body.question || '').slice(0, 16000);
    const model = body.model || 'claude-sonnet-4-20250514';
    const maxTokens = Math.min(Number(body.max_tokens || 700), 1000);

    if (!system || !userPrompt) {
      return res.status(400).json({ error: 'Missing system or user_prompt.' });
    }

    const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model,
        max_tokens: maxTokens,
        system,
        messages: [{ role: 'user', content: userPrompt }]
      })
    });

    const data = await anthropicRes.json();
    if (!anthropicRes.ok) {
      return res.status(anthropicRes.status).json({ error: data.error || data });
    }

    return res.status(200).json({
      answer: data.content?.[0]?.text || '',
      usage: data.usage || null,
      model: data.model || model
    });
  } catch (err) {
    return res.status(500).json({ error: err.message || 'Server error' });
  }
}
