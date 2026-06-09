#!/usr/bin/env node
/**
 * Patches Camoufox server.js to use the DEFAULT browser context
 * (contexts[0]) instead of creating a new isolated context per session.
 * This makes API sessions share cookies/localStorage with the VNC-displayed browser.
 */
const fs = require('fs');
const path = '/usr/local/lib/node_modules/@askjo/camofox-browser/server.js';

let content = fs.readFileSync(path, 'utf8');

// Replace: b.newContext({...}) with: b.contexts()[0] || await b.newContext({...})
// This reuses the FIRST context (the one visible in VNC) instead of creating an isolated one.
const original = `context = await candidateBrowser.newContext({`;
const replacement = `context = (candidateBrowser.contexts()[0]) ? candidateBrowser.contexts()[0] : await candidateBrowser.newContext({`;

if (content.includes(original)) {
  content = content.replace(original, replacement);
  fs.writeFileSync(path, content);
  console.log('PATCHED: using browser.contexts()[0] instead of newContext()');
  console.log('Match count:', content.split(replacement).length - 1);
} else {
  console.log('FAILED: could not find target code');
}
