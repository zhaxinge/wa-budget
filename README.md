# WA Budget Lens Ask Question Hosting Package

This package gives you the JavaScript files needed to host the Ask Question feature safely.

## Files

```text
api/ask.js          -> Vercel backend API proxy
ask-client.js       -> frontend helper used by index.html
package.json        -> dependency for Vercel
```

## Repo structure

```text
wa-budget/
├── index.html
├── ask-client.js
├── package.json
└── api/
    └── ask.js
```

## In index.html

Add this before `</body>`:

```html
<script src="./ask-client.js"></script>
```

Your page should call:

```js
const result = await askBudgetQuestion(userQuestion);
```

## In Vercel

Add this Environment Variable:

```text
ANTHROPIC_API_KEY = sk-ant-...
```

Then redeploy.

## In ask-client.js

Replace:

```js
https://YOUR-VERCEL-PROJECT.vercel.app/api/ask
```

with your real Vercel endpoint.

## Important

Do not put your Anthropic API key in index.html or ask-client.js.
The key should only live in Vercel Environment Variables.
