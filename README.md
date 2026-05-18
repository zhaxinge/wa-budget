# WA Budget Lens AI-enabled version

## Files
- `index.html` — improved frontend with Excel upload, computed dashboard, and AI question box.
- `api/ask.js` — Vercel-style backend proxy. It keeps your Anthropic key off the browser.

## Recommended deployment
1. Deploy this folder to Vercel.
2. Add an environment variable named `ANTHROPIC_API_KEY` with your Claude API key.
3. Keep the frontend endpoint as `/api/ask`.

## Important
Do not hardcode your Claude API key into the frontend for public users. If users ask questions through your key, the usage is billed to you. Add login/rate limits for production.
