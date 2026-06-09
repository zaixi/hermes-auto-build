#!/usr/bin/env node
/**
 * Patches Camoufox server.js to add:
 * - GET /debug/cookies — returns cookies from ALL browser contexts (not just the current session's)
 *   This allows reading cookies from the VNC-displayed context where the user logged in.
 */
const fs = require('fs');
const path = '/usr/local/lib/node_modules/@askjo/camofox-browser/server.js';

let content = fs.readFileSync(path, 'utf8');

// Find the auth import and add our endpoint
const authImport = "import { requireAuth, accessKeyMiddleware, timingSafeCompare as _timingSafeCompare, isLoopbackAddress as _isLoopbackAddress } from './lib/auth.js';";

const debugEndpoint = `

// [camofox-patch] Debug: get cookies from ALL browser contexts
app.get('/debug/cookies', async (req, res) => {
  try {
    const allCookies = [];
    for (const ctx of (candidateBrowser?.contexts() || [])) {
      try {
        const cookies = await ctx.cookies();
        allCookies.push(...cookies);
      } catch (_) {}
    }
    res.json({ ok: true, contexts: (candidateBrowser?.contexts() || []).length, cookies: allCookies });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});
`;

content = content.replace(authImport, authImport + debugEndpoint);

fs.writeFileSync(path, content);
console.log('PATCHED: server.js with /debug/cookies endpoint');
