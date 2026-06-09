#!/usr/bin/env python3
"""
CloakBrowser 控制工具 — 通过 CDP 连接到 CloakBrowser 容器中的 Chromium
"""
import asyncio, json, urllib.request, subprocess, sys

CLOAK_CONTAINER = "cloakbrowser"
CDP_HOST = "localhost"
CDP_PORT = 5100

def get_ws_url():
    """从 cloakbrowser 容器获取 CDP WebSocket URL"""
    r = subprocess.run(
        ["docker", "exec", CLOAK_CONTAINER, "curl", "-s",
         f"http://{CDP_HOST}:{CDP_PORT}/json/version"],
        capture_output=True, text=True, timeout=10
    )
    info = json.loads(r.stdout)
    return info["webSocketDebuggerUrl"]

async def navigate(url: str):
    """在浏览器中导航到 URL"""
    ws_url = get_ws_url()
    import websockets
    async with websockets.connect(ws_url) as ws:
        target = json.dumps({"id": 1, "method": "Target.createTarget", "params": {"url": url}})
        await ws.send(target)
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        return resp.get("result", {}).get("targetId", "")

async def get_cookies(domain_filter: str = None):
    """获取所有 cookie，可选按域名过滤"""
    ws_url = get_ws_url()
    import websockets
    async with websockets.connect(ws_url) as ws:
        targets = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if domain_filter:
            return [c for c in all_cookies if domain_filter in c.get("domain", "")]
        return all_cookies

async def screenshot(tab_id: str = None):
    """截取指定标签页的截图"""
    ws_url = get_ws_url()
    import websockets
    async with websockets.connect(ws_url) as ws:
        if not tab_id:
            targets = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        return None

def list_tabs():
    """列出所有打开的标签页"""
    r = subprocess.run(
        ["docker", "exec", CLOAK_CONTAINER, "curl", "-s",
         f"http://{CDP_HOST}:{CDP_PORT}/json"],
        capture_output=True, text=True, timeout=10
    )
    pages = json.loads(r.stdout)
    for p in pages:
        print(f"  [{p['id'][:12]}] {p.get('title','')[:50]} | {p.get('url','')[:60]}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        list_tabs()
    elif cmd == "navigate":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://www.smzdm.com"
        result = asyncio.run(navigate(url))
        print(f"Navigated: {result}")
