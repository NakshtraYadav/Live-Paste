"""
POC test for LivePaste core:
1. REST: create paste (random slug + custom slug + validation)
2. WS: external wss connectivity through ingress
3. WS: broadcast edit from client A -> received by client B
4. Persistence: REST reload returns latest content
5. Presence: viewer counts
"""
import asyncio
import json
import sys
import uuid

import httpx
import websockets

BASE_URL = "https://command-hub-119.preview.emergentagent.com"
WS_BASE = BASE_URL.replace("https://", "wss://")

results = []

def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} - {name} {detail}")


async def main():
    async with httpx.AsyncClient(timeout=20) as http:
        # 1. Health
        r = await http.get(f"{BASE_URL}/api/health")
        record("health", r.status_code == 200, str(r.status_code))

        # 2. Create paste with random slug
        r = await http.post(f"{BASE_URL}/api/paste", json={"content": "hello world", "language": "python", "expiry": "1h"})
        ok = r.status_code == 200
        slug = r.json().get("slug") if ok else None
        record("create_random_slug", ok and slug, f"slug={slug}")

        # 3. Create paste with custom slug
        custom = f"poc-{uuid.uuid4().hex[:8]}"
        r = await http.post(f"{BASE_URL}/api/paste", json={"content": "custom", "customSlug": custom, "expiry": "never"})
        record("create_custom_slug", r.status_code == 200 and r.json().get("slug") == custom)

        # 4. Duplicate custom slug rejected
        r = await http.post(f"{BASE_URL}/api/paste", json={"content": "dup", "customSlug": custom})
        record("duplicate_slug_rejected", r.status_code == 409, str(r.status_code))

        # 5. Invalid slug rejected
        r = await http.post(f"{BASE_URL}/api/paste", json={"content": "x", "customSlug": "a b!"})
        record("invalid_slug_rejected", r.status_code == 400, str(r.status_code))

        # 6. GET paste
        r = await http.get(f"{BASE_URL}/api/paste/{slug}")
        record("get_paste", r.status_code == 200 and r.json()["content"] == "hello world")

        # 7. WS connectivity + broadcast
        ws_url = f"{WS_BASE}/api/ws/{slug}"
        print(f"Connecting WS: {ws_url}")
        try:
            async with websockets.connect(ws_url) as ws_a, websockets.connect(ws_url) as ws_b:
                init_a = json.loads(await asyncio.wait_for(ws_a.recv(), 10))
                record("ws_a_init", init_a.get("type") == "init" and init_a["paste"]["content"] == "hello world")

                init_b = json.loads(await asyncio.wait_for(ws_b.recv(), 10))
                record("ws_b_init", init_b.get("type") == "init" and init_b.get("viewers") == 2, f"viewers={init_b.get('viewers')}")

                # A should receive presence update when B joined
                presence = json.loads(await asyncio.wait_for(ws_a.recv(), 10))
                record("ws_a_presence", presence.get("type") == "presence" and presence.get("viewers") == 2, str(presence))

                # A sends edit -> B receives
                new_content = "updated in realtime!"
                await ws_a.send(json.dumps({"type": "edit", "content": new_content}))
                msg_b = json.loads(await asyncio.wait_for(ws_b.recv(), 10))
                record("ws_broadcast_edit", msg_b.get("type") == "edit" and msg_b.get("content") == new_content, str(msg_b.get("type")))

                # Language change broadcast
                await ws_b.send(json.dumps({"type": "language", "language": "javascript"}))
                msg_a = json.loads(await asyncio.wait_for(ws_a.recv(), 10))
                record("ws_broadcast_language", msg_a.get("type") == "language" and msg_a.get("language") == "javascript")
        except Exception as e:
            record("ws_flow", False, f"{type(e).__name__}: {e}")

        # 8. Persistence check after WS edits
        r = await http.get(f"{BASE_URL}/api/paste/{slug}")
        record("persistence_after_ws", r.status_code == 200 and r.json()["content"] == "updated in realtime!" and r.json()["language"] == "javascript")

        # 9. WS to non-existent slug -> error
        try:
            async with websockets.connect(f"{WS_BASE}/api/ws/does-not-exist-{uuid.uuid4().hex[:6]}") as ws:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
                record("ws_not_found", msg.get("type") == "error" and msg.get("code") == "not_found")
        except Exception as e:
            record("ws_not_found", False, str(e))

    failed = [r for r in results if not r[1]]
    print(f"\n===== {len(results) - len(failed)}/{len(results)} passed =====")
    sys.exit(1 if failed else 0)


asyncio.run(main())
