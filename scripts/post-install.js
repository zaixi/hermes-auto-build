#!/usr/bin/env node
/**
 * Post-install patch for Camoufox server.js
 * - Adds window resize after browser launch so VNC shows the browser
 * - Fixes the 10x10 invisible window issue
 */
const fs = require('fs');
const path = '/usr/local/lib/node_modules/@askjo/camofox-browser/server.js';

let content = fs.readFileSync(path, 'utf8');

const patch = `
      // [camofox-patch] Resize browser window for VNC visibility
      setTimeout(async () => {
        try {
          const { execSync } = require("child_process");
          execSync("xdotool search --name Camoufox windowmove 0 0 windowsize 1920 1080 || true", {
            env: { DISPLAY: vdDisplay || ":0" }, stdio: "ignore",
          });
        } catch (_) {}
        try {
          for (const ctx of candidateBrowser.contexts()) {
            for (const page of ctx.pages()) {
              await page.setViewportSize({ width: 1920, height: 1080 }).catch(() => {});
            }
          }
        } catch (_) {}
      }, 8000);
`;

content = content.replace(
  'await pluginEvents.emitAsync(\'browser:launching\', { options });',
  'await pluginEvents.emitAsync(\'browser:launching\', { options });\n' + patch
);

fs.writeFileSync(path, content);
console.log('PATCHED: server.js with VNC window resize');
