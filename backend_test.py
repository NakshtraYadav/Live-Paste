"""
Comprehensive backend regression test for LivePaste after storage-layer refactor.
Tests MongoDB mode against the public URL.
"""

import asyncio
import json
import io
from datetime import datetime, timezone
import httpx
import websockets

BASE_URL = "https://command-hub-119.preview.emergentagent.com"
API_URL = f"{BASE_URL}/api"
WS_URL = "wss://command-hub-119.preview.emergentagent.com/api/ws"

# Test results tracking
test_results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

def log_pass(test_name):
    print(f"✅ PASS: {test_name}")
    test_results["passed"].append(test_name)

def log_fail(test_name, reason):
    print(f"❌ FAIL: {test_name} - {reason}")
    test_results["failed"].append({"test": test_name, "reason": reason})

def log_warning(test_name, reason):
    print(f"⚠️  WARNING: {test_name} - {reason}")
    test_results["warnings"].append({"test": test_name, "reason": reason})

def is_iso_timestamp(value):
    """Check if value is a valid ISO timestamp string."""
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except (ValueError, TypeError):
        return False

def check_no_objectid(data, path=""):
    """Recursively check for MongoDB ObjectId leakage in JSON."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "_id":
                return f"Found _id field at {path}.{key}"
            if isinstance(value, str) and len(value) == 24:
                # Could be ObjectId hex string, but we allow 24-char image IDs
                if key != "id":  # image IDs are 24-hex, that's OK
                    pass
            result = check_no_objectid(value, f"{path}.{key}")
            if result:
                return result
    elif isinstance(data, list):
        for i, item in enumerate(data):
            result = check_no_objectid(item, f"{path}[{i}]")
            if result:
                return result
    return None

async def test_health():
    """Test 1: GET /api/health → 200 {status: ok}"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{API_URL}/health")
            if resp.status_code != 200:
                log_fail("Health endpoint", f"Expected 200, got {resp.status_code}")
                return
            data = resp.json()
            if data.get("status") != "ok":
                log_fail("Health endpoint", f"Expected status='ok', got {data}")
                return
            if "time" in data and not is_iso_timestamp(data["time"]):
                log_warning("Health endpoint", f"time field is not ISO timestamp: {data['time']}")
            log_pass("Health endpoint")
        except Exception as e:
            log_fail("Health endpoint", str(e))

async def test_create_paste_random():
    """Test 2: POST /api/paste with {} → random 7-char slug, rev 0, views 0"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={})
            if resp.status_code != 200:
                log_fail("Create paste (random slug)", f"Expected 200, got {resp.status_code}: {resp.text}")
                return None
            data = resp.json()
            
            # Check slug
            slug = data.get("slug")
            if not slug or len(slug) != 7:
                log_fail("Create paste (random slug)", f"Expected 7-char slug, got: {slug}")
                return None
            
            # Check fields
            if data.get("rev") != 0:
                log_fail("Create paste (random slug)", f"Expected rev=0, got {data.get('rev')}")
                return None
            if data.get("views") != 0:
                log_fail("Create paste (random slug)", f"Expected views=0, got {data.get('views')}")
                return None
            
            # Check timestamps
            for field in ["createdAt", "updatedAt"]:
                if not is_iso_timestamp(data.get(field)):
                    log_warning("Create paste (random slug)", f"{field} is not ISO timestamp: {data.get(field)}")
            
            # Check for ObjectId leakage
            objectid_issue = check_no_objectid(data)
            if objectid_issue:
                log_fail("Create paste (random slug)", f"ObjectId leakage: {objectid_issue}")
                return None
            
            log_pass("Create paste (random slug)")
            return slug
        except Exception as e:
            log_fail("Create paste (random slug)", str(e))
            return None

async def test_create_paste_custom():
    """Test 3: POST /api/paste with customSlug → uses it"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            custom_slug = f"test-custom-{int(datetime.now().timestamp())}"
            resp = await client.post(f"{API_URL}/paste", json={"customSlug": custom_slug})
            if resp.status_code != 200:
                log_fail("Create paste (custom slug)", f"Expected 200, got {resp.status_code}: {resp.text}")
                return None
            data = resp.json()
            if data.get("slug") != custom_slug:
                log_fail("Create paste (custom slug)", f"Expected slug={custom_slug}, got {data.get('slug')}")
                return None
            log_pass("Create paste (custom slug)")
            return custom_slug
        except Exception as e:
            log_fail("Create paste (custom slug)", str(e))
            return None

async def test_duplicate_slug(existing_slug):
    """Test 3b: duplicate customSlug → 409"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"customSlug": existing_slug})
            if resp.status_code != 409:
                log_fail("Duplicate slug validation", f"Expected 409, got {resp.status_code}")
                return
            log_pass("Duplicate slug validation")
        except Exception as e:
            log_fail("Duplicate slug validation", str(e))

async def test_reserved_slug():
    """Test 3c: reserved slug like 'api' → 400"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"customSlug": "api"})
            if resp.status_code != 400:
                log_fail("Reserved slug validation", f"Expected 400, got {resp.status_code}")
                return
            log_pass("Reserved slug validation")
        except Exception as e:
            log_fail("Reserved slug validation", str(e))

async def test_invalid_slug_short():
    """Test 3d: invalid slug like 'a' → 400"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"customSlug": "a"})
            if resp.status_code != 400:
                log_fail("Invalid slug (too short)", f"Expected 400, got {resp.status_code}")
                return
            log_pass("Invalid slug (too short)")
        except Exception as e:
            log_fail("Invalid slug (too short)", str(e))

async def test_invalid_slug_chars():
    """Test 3e: invalid slug like 'bad slug!' → 400"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"customSlug": "bad slug!"})
            if resp.status_code != 400:
                log_fail("Invalid slug (bad chars)", f"Expected 400, got {resp.status_code}")
                return
            log_pass("Invalid slug (bad chars)")
        except Exception as e:
            log_fail("Invalid slug (bad chars)", str(e))

async def test_invalid_expiry():
    """Test 3f: invalid expiry → 400"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"expiry": "invalid"})
            if resp.status_code != 400:
                log_fail("Invalid expiry validation", f"Expected 400, got {resp.status_code}")
                return
            log_pass("Invalid expiry validation")
        except Exception as e:
            log_fail("Invalid expiry validation", str(e))

async def test_expiry_1h():
    """Test 4: POST /api/paste with expiry '1h' → expiresAt set ~1h in future"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"expiry": "1h"})
            if resp.status_code != 200:
                log_fail("Expiry 1h", f"Expected 200, got {resp.status_code}: {resp.text}")
                return
            data = resp.json()
            expires_at = data.get("expiresAt")
            if not expires_at:
                log_fail("Expiry 1h", "expiresAt is missing")
                return
            if not is_iso_timestamp(expires_at):
                log_fail("Expiry 1h", f"expiresAt is not ISO timestamp: {expires_at}")
                return
            
            # Check it's roughly 1 hour in the future
            exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            diff = (exp_dt - now).total_seconds()
            if not (3500 < diff < 3700):  # ~1 hour ± 100 seconds
                log_warning("Expiry 1h", f"expiresAt is {diff}s in future, expected ~3600s")
            
            log_pass("Expiry 1h")
        except Exception as e:
            log_fail("Expiry 1h", str(e))

async def test_expiry_never():
    """Test 4b: expiry 'never' → expiresAt null"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{API_URL}/paste", json={"expiry": "never"})
            if resp.status_code != 200:
                log_fail("Expiry never", f"Expected 200, got {resp.status_code}: {resp.text}")
                return
            data = resp.json()
            if data.get("expiresAt") is not None:
                log_fail("Expiry never", f"Expected expiresAt=null, got {data.get('expiresAt')}")
                return
            log_pass("Expiry never")
        except Exception as e:
            log_fail("Expiry never", str(e))

async def test_content_size_limit():
    """Test 5: content > 400000 chars → 413"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            large_content = "x" * 400001
            resp = await client.post(f"{API_URL}/paste", json={"content": large_content})
            if resp.status_code != 413:
                log_fail("Content size limit", f"Expected 413, got {resp.status_code}")
                return
            log_pass("Content size limit")
        except Exception as e:
            log_fail("Content size limit", str(e))

async def test_get_paste(slug):
    """Test 6: GET /api/paste/{slug} → returns saved content/language"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{API_URL}/paste/{slug}")
            if resp.status_code != 200:
                log_fail("Get paste", f"Expected 200, got {resp.status_code}: {resp.text}")
                return False
            data = resp.json()
            if data.get("slug") != slug:
                log_fail("Get paste", f"Expected slug={slug}, got {data.get('slug')}")
                return False
            
            # Check serialization
            objectid_issue = check_no_objectid(data)
            if objectid_issue:
                log_fail("Get paste", f"ObjectId leakage: {objectid_issue}")
                return False
            
            log_pass("Get paste")
            return True
        except Exception as e:
            log_fail("Get paste", str(e))
            return False

async def test_get_paste_count_view(slug):
    """Test 6b: GET /api/paste/{slug}?count_view=true increments views"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Get initial views
            resp1 = await client.get(f"{API_URL}/paste/{slug}")
            if resp1.status_code != 200:
                log_fail("Get paste count_view", f"Initial get failed: {resp1.status_code}")
                return
            initial_views = resp1.json().get("views", 0)
            
            # Get with count_view=true
            resp2 = await client.get(f"{API_URL}/paste/{slug}?count_view=true")
            if resp2.status_code != 200:
                log_fail("Get paste count_view", f"count_view get failed: {resp2.status_code}")
                return
            new_views = resp2.json().get("views", 0)
            
            if new_views != initial_views + 1:
                log_fail("Get paste count_view", f"Expected views={initial_views + 1}, got {new_views}")
                return
            
            log_pass("Get paste count_view")
        except Exception as e:
            log_fail("Get paste count_view", str(e))

async def test_get_paste_unknown():
    """Test 6c: unknown slug → 404"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{API_URL}/paste/nonexistent-slug-12345")
            if resp.status_code != 404:
                log_fail("Get paste (unknown slug)", f"Expected 404, got {resp.status_code}")
                return
            log_pass("Get paste (unknown slug)")
        except Exception as e:
            log_fail("Get paste (unknown slug)", str(e))

async def test_image_upload(slug):
    """Test 7: POST /api/paste/{slug}/image with PNG → returns id, url, name, size"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Create a minimal PNG (1x1 transparent pixel)
            png_data = bytes.fromhex(
                '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
                '89000000017352474200aece1ce90000000467414d410000b18f0bfc61050000'
                '000970485973000000ec000000ec01787d5cb30000000a49444154185763000001'
                '00010d0a2db40000000049454e44ae426082'
            )
            
            files = {"file": ("test.png", io.BytesIO(png_data), "image/png")}
            resp = await client.post(f"{API_URL}/paste/{slug}/image", files=files)
            
            if resp.status_code != 200:
                log_fail("Image upload", f"Expected 200, got {resp.status_code}: {resp.text}")
                return None
            
            data = resp.json()
            
            # Check required fields
            if "id" not in data:
                log_fail("Image upload", "Missing 'id' field")
                return None
            if "url" not in data:
                log_fail("Image upload", "Missing 'url' field")
                return None
            if "name" not in data:
                log_fail("Image upload", "Missing 'name' field")
                return None
            if "size" not in data:
                log_fail("Image upload", "Missing 'size' field")
                return None
            
            # Check id is 24-hex
            image_id = data["id"]
            if not (isinstance(image_id, str) and len(image_id) == 24):
                log_fail("Image upload", f"Expected 24-char hex id, got: {image_id}")
                return None
            
            # Check serialization
            objectid_issue = check_no_objectid(data)
            if objectid_issue:
                log_fail("Image upload", f"ObjectId leakage: {objectid_issue}")
                return None
            
            log_pass("Image upload")
            return image_id
        except Exception as e:
            log_fail("Image upload", str(e))
            return None

async def test_image_get(image_id):
    """Test 7b: GET /api/image/{id} → 200 image/png with Content-Length"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{API_URL}/image/{image_id}")
            if resp.status_code != 200:
                log_fail("Image get", f"Expected 200, got {resp.status_code}")
                return False
            
            content_type = resp.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                log_fail("Image get", f"Expected image/* content-type, got: {content_type}")
                return False
            
            if "content-length" not in resp.headers:
                log_warning("Image get", "Missing Content-Length header")
            
            log_pass("Image get")
            return True
        except Exception as e:
            log_fail("Image get", str(e))
            return False

async def test_image_delete(image_id):
    """Test 7c: DELETE /api/image/{id} → {ok:true}"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.delete(f"{API_URL}/image/{image_id}")
            if resp.status_code != 200:
                log_fail("Image delete", f"Expected 200, got {resp.status_code}: {resp.text}")
                return False
            
            data = resp.json()
            if data.get("ok") != True:
                log_fail("Image delete", f"Expected ok=true, got: {data}")
                return False
            
            log_pass("Image delete")
            return True
        except Exception as e:
            log_fail("Image delete", str(e))
            return False

async def test_image_get_after_delete(image_id):
    """Test 7d: GET after delete → 404"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{API_URL}/image/{image_id}")
            if resp.status_code != 404:
                log_fail("Image get after delete", f"Expected 404, got {resp.status_code}")
                return
            log_pass("Image get after delete")
        except Exception as e:
            log_fail("Image get after delete", str(e))

async def test_image_upload_non_image(slug):
    """Test 7e: /image endpoint rejects non-image content types"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            files = {"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")}
            resp = await client.post(f"{API_URL}/paste/{slug}/image", files=files)
            if resp.status_code != 400:
                log_fail("Image upload (non-image)", f"Expected 400, got {resp.status_code}")
                return
            log_pass("Image upload (non-image)")
        except Exception as e:
            log_fail("Image upload (non-image)", str(e))

async def test_image_upload_unknown_slug():
    """Test 7f: image upload to unknown slug → 404"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            png_data = bytes.fromhex(
                '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
                '89000000017352474200aece1ce90000000467414d410000b18f0bfc61050000'
                '000970485973000000ec000000ec01787d5cb30000000a49444154185763000001'
                '00010d0a2db40000000049454e44ae426082'
            )
            files = {"file": ("test.png", io.BytesIO(png_data), "image/png")}
            resp = await client.post(f"{API_URL}/paste/nonexistent-slug-99999/image", files=files)
            if resp.status_code != 404:
                log_fail("Image upload (unknown slug)", f"Expected 404, got {resp.status_code}")
                return
            log_pass("Image upload (unknown slug)")
        except Exception as e:
            log_fail("Image upload (unknown slug)", str(e))

async def test_file_upload_any_type(slug):
    """Test 7g: POST /api/paste/{slug}/file with a non-image → any type allowed"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            files = {"file": ("notes.txt", io.BytesIO(b"hello file world"), "text/plain")}
            resp = await client.post(f"{API_URL}/paste/{slug}/file", files=files)
            if resp.status_code != 200:
                log_fail("File upload (text file)", f"Expected 200, got {resp.status_code}: {resp.text}")
                return None
            data = resp.json()
            for field in ["id", "url", "name", "size", "contentType"]:
                if field not in data:
                    log_fail("File upload (text file)", f"Missing '{field}' field")
                    return None
            if not data["url"].startswith("/api/file/"):
                log_fail("File upload (text file)", f"Unexpected url: {data['url']}")
                return None
            if not (isinstance(data["id"], str) and len(data["id"]) == 24):
                log_fail("File upload (text file)", f"Expected 24-char hex id, got: {data['id']}")
                return None
            log_pass("File upload (text file)")
            return data["id"]
        except Exception as e:
            log_fail("File upload (text file)", str(e))
            return None

async def test_file_upload_binary(slug):
    """Test 7h: upload a binary blob (application/octet-stream) → 200"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            blob = bytes(range(256)) * 4
            files = {"file": ("blob.bin", io.BytesIO(blob), "application/octet-stream")}
            resp = await client.post(f"{API_URL}/paste/{slug}/file", files=files)
            if resp.status_code != 200:
                log_fail("File upload (binary)", f"Expected 200, got {resp.status_code}: {resp.text}")
                return None
            log_pass("File upload (binary)")
            return resp.json()["id"]
        except Exception as e:
            log_fail("File upload (binary)", str(e))
            return None

async def test_file_get_roundtrip(file_id, expected_bytes):
    """Test 7i: GET /api/file/{id} returns exact uploaded bytes"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{API_URL}/file/{file_id}")
            if resp.status_code != 200:
                log_fail("File get roundtrip", f"Expected 200, got {resp.status_code}")
                return False
            if resp.content != expected_bytes:
                log_fail("File get roundtrip", "Downloaded bytes do not match uploaded bytes")
                return False
            log_pass("File get roundtrip")
            return True
        except Exception as e:
            log_fail("File get roundtrip", str(e))
            return False

async def test_file_delete(file_id):
    """Test 7j: DELETE /api/file/{id} → {ok:true}, then GET → 404"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.delete(f"{API_URL}/file/{file_id}")
            if resp.status_code != 200 or resp.json().get("ok") is not True:
                log_fail("File delete", f"Unexpected response: {resp.status_code} {resp.text}")
                return False
            resp2 = await client.get(f"{API_URL}/file/{file_id}")
            if resp2.status_code != 404:
                log_fail("File delete", f"Expected 404 after delete, got {resp2.status_code}")
                return False
            log_pass("File delete")
            return True
        except Exception as e:
            log_fail("File delete", str(e))
            return False

async def test_file_upload_unknown_slug():
    """Test 7k: file upload to unknown slug → 404"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            files = {"file": ("test.txt", io.BytesIO(b"x"), "text/plain")}
            resp = await client.post(f"{API_URL}/paste/nonexistent-slug-99999/file", files=files)
            if resp.status_code != 404:
                log_fail("File upload (unknown slug)", f"Expected 404, got {resp.status_code}")
                return
            log_pass("File upload (unknown slug)")
        except Exception as e:
            log_fail("File upload (unknown slug)", str(e))

async def test_websocket_existing_slug(slug):
    """Test 8: WebSocket connect to existing slug → receives {type:init, paste:{...}, viewers}"""
    try:
        async with websockets.connect(f"{WS_URL}/{slug}") as ws:
            # Receive init message
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            
            if data.get("type") != "init":
                log_fail("WebSocket init", f"Expected type='init', got: {data.get('type')}")
                return False
            
            if "paste" not in data:
                log_fail("WebSocket init", "Missing 'paste' field")
                return False
            
            if "viewers" not in data:
                log_fail("WebSocket init", "Missing 'viewers' field")
                return False
            
            # Check serialization
            objectid_issue = check_no_objectid(data)
            if objectid_issue:
                log_fail("WebSocket init", f"ObjectId leakage: {objectid_issue}")
                return False
            
            log_pass("WebSocket init")
            return True
    except Exception as e:
        log_fail("WebSocket init", str(e))
        return False

async def test_websocket_edit(slug):
    """Test 8b: Two clients - client A sends edit → client B receives it with incremented rev"""
    try:
        # Connect two clients
        async with websockets.connect(f"{WS_URL}/{slug}") as ws1, \
                   websockets.connect(f"{WS_URL}/{slug}") as ws2:
            
            # Consume init messages
            await ws1.recv()
            init2 = json.loads(await ws2.recv())
            
            # ws1 should receive presence message when ws2 joins
            presence = json.loads(await asyncio.wait_for(ws1.recv(), timeout=2.0))
            if presence.get("type") != "presence":
                log_warning("WebSocket edit", f"Expected presence message, got: {presence.get('type')}")
            
            # Get initial rev
            initial_rev = init2["paste"]["rev"]
            
            # Client 1 sends edit
            test_content = f"Test edit at {datetime.now().isoformat()}"
            await ws1.send(json.dumps({"type": "edit", "content": test_content}))
            
            # Client 2 should receive the edit
            msg = await asyncio.wait_for(ws2.recv(), timeout=5.0)
            data = json.loads(msg)
            
            if data.get("type") != "edit":
                log_fail("WebSocket edit", f"Expected type='edit', got: {data.get('type')}")
                return False
            
            if data.get("content") != test_content:
                log_fail("WebSocket edit", f"Content mismatch: expected '{test_content}', got '{data.get('content')}'")
                return False
            
            if data.get("rev") != initial_rev + 1:
                log_fail("WebSocket edit", f"Expected rev={initial_rev + 1}, got {data.get('rev')}")
                return False
            
            # Verify persistence via GET
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{API_URL}/paste/{slug}")
                if resp.status_code == 200:
                    paste_data = resp.json()
                    if paste_data.get("content") != test_content:
                        log_fail("WebSocket edit", f"Content not persisted: expected '{test_content}', got '{paste_data.get('content')}'")
                        return False
                else:
                    log_warning("WebSocket edit", f"Could not verify persistence: GET returned {resp.status_code}")
            
            log_pass("WebSocket edit")
            return True
    except Exception as e:
        log_fail("WebSocket edit", str(e))
        return False

async def test_websocket_language(slug):
    """Test 8c: {type:'language', language:'python'} broadcasts to other client"""
    try:
        async with websockets.connect(f"{WS_URL}/{slug}") as ws1, \
                   websockets.connect(f"{WS_URL}/{slug}") as ws2:
            
            # Consume init messages
            await ws1.recv()
            await ws2.recv()
            
            # Consume presence message
            await asyncio.wait_for(ws1.recv(), timeout=2.0)
            
            # Client 1 sends language change
            await ws1.send(json.dumps({"type": "language", "language": "python"}))
            
            # Client 2 should receive it
            msg = await asyncio.wait_for(ws2.recv(), timeout=5.0)
            data = json.loads(msg)
            
            if data.get("type") != "language":
                log_fail("WebSocket language", f"Expected type='language', got: {data.get('type')}")
                return False
            
            if data.get("language") != "python":
                log_fail("WebSocket language", f"Expected language='python', got: {data.get('language')}")
                return False
            
            log_pass("WebSocket language")
            return True
    except Exception as e:
        log_fail("WebSocket language", str(e))
        return False

async def test_websocket_ping():
    """Test 8d: {type:'ping'} → {type:'pong'}"""
    # Create a temporary paste for this test
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{API_URL}/paste", json={})
        if resp.status_code != 200:
            log_fail("WebSocket ping", "Could not create test paste")
            return False
        slug = resp.json()["slug"]
    
    try:
        async with websockets.connect(f"{WS_URL}/{slug}") as ws:
            # Consume init message
            await ws.recv()
            
            # Send ping
            await ws.send(json.dumps({"type": "ping"}))
            
            # Receive pong
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            
            if data.get("type") != "pong":
                log_fail("WebSocket ping", f"Expected type='pong', got: {data.get('type')}")
                return False
            
            log_pass("WebSocket ping")
            return True
    except Exception as e:
        log_fail("WebSocket ping", str(e))
        return False

async def test_websocket_not_found():
    """Test 8e: connect to non-existent slug → {type:error, code:not_found} then close"""
    try:
        async with websockets.connect(f"{WS_URL}/nonexistent-slug-99999") as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(msg)
            
            if data.get("type") != "error":
                log_fail("WebSocket not_found", f"Expected type='error', got: {data.get('type')}")
                return False
            
            if data.get("code") != "not_found":
                log_fail("WebSocket not_found", f"Expected code='not_found', got: {data.get('code')}")
                return False
            
            # Connection should close
            try:
                await asyncio.wait_for(ws.recv(), timeout=2.0)
                log_fail("WebSocket not_found", "Connection did not close after error")
                return False
            except websockets.exceptions.ConnectionClosed:
                pass  # Expected
            
            log_pass("WebSocket not_found")
            return True
    except websockets.exceptions.ConnectionClosed:
        # Connection closed immediately, which is also acceptable
        log_pass("WebSocket not_found")
        return True
    except Exception as e:
        log_fail("WebSocket not_found", str(e))
        return False

async def test_websocket_presence(slug):
    """Test 8f: second client joining sends {type:presence} with viewers count to first client"""
    try:
        async with websockets.connect(f"{WS_URL}/{slug}") as ws1:
            # Consume init message
            init1 = json.loads(await ws1.recv())
            initial_viewers = init1.get("viewers", 0)
            
            # Connect second client
            async with websockets.connect(f"{WS_URL}/{slug}") as ws2:
                # ws2 gets init
                await ws2.recv()
                
                # ws1 should receive presence update
                msg = await asyncio.wait_for(ws1.recv(), timeout=5.0)
                data = json.loads(msg)
                
                if data.get("type") != "presence":
                    log_fail("WebSocket presence", f"Expected type='presence', got: {data.get('type')}")
                    return False
                
                if data.get("viewers") != initial_viewers + 1:
                    log_fail("WebSocket presence", f"Expected viewers={initial_viewers + 1}, got: {data.get('viewers')}")
                    return False
                
                log_pass("WebSocket presence")
                return True
    except Exception as e:
        log_fail("WebSocket presence", str(e))
        return False

async def run_all_tests():
    """Run all backend tests in sequence."""
    print("=" * 80)
    print("LivePaste Backend Regression Test Suite")
    print("Testing against:", BASE_URL)
    print("=" * 80)
    print()
    
    # Test 1: Health
    await test_health()
    
    # Test 2: Create paste (random slug)
    random_slug = await test_create_paste_random()
    
    # Test 3: Create paste (custom slug)
    custom_slug = await test_create_paste_custom()
    
    # Test 3b-f: Validation tests
    if custom_slug:
        await test_duplicate_slug(custom_slug)
    await test_reserved_slug()
    await test_invalid_slug_short()
    await test_invalid_slug_chars()
    await test_invalid_expiry()
    
    # Test 4: Expiry
    await test_expiry_1h()
    await test_expiry_never()
    
    # Test 5: Content size limit
    await test_content_size_limit()
    
    # Test 6: Get paste
    if random_slug:
        await test_get_paste(random_slug)
        await test_get_paste_count_view(random_slug)
    await test_get_paste_unknown()
    
    # Test 7: Image endpoints
    if random_slug:
        image_id = await test_image_upload(random_slug)
        if image_id:
            await test_image_get(image_id)
            await test_image_delete(image_id)
            await test_image_get_after_delete(image_id)
        await test_image_upload_non_image(random_slug)
    await test_image_upload_unknown_slug()

    # Test 7g-j: Any-file endpoints
    txt_id = None
    bin_id = None
    if random_slug:
        txt_id = await test_file_upload_any_type(random_slug)
        bin_id = await test_file_upload_binary(random_slug)
        if bin_id:
            await test_file_get_roundtrip(bin_id, bytes(range(256)) * 4)
            await test_file_delete(bin_id)
    await test_file_upload_unknown_slug()
    
    # Test 8: WebSocket
    # Create a fresh paste for WebSocket tests
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{API_URL}/paste", json={"content": "WebSocket test paste"})
        if resp.status_code == 200:
            ws_slug = resp.json()["slug"]
            await test_websocket_existing_slug(ws_slug)
            await test_websocket_edit(ws_slug)
            await test_websocket_language(ws_slug)
            await test_websocket_presence(ws_slug)
        else:
            log_fail("WebSocket tests", "Could not create test paste")
    
    await test_websocket_ping()
    await test_websocket_not_found()
    
    # Print summary
    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"✅ Passed: {len(test_results['passed'])}")
    print(f"❌ Failed: {len(test_results['failed'])}")
    print(f"⚠️  Warnings: {len(test_results['warnings'])}")
    print()
    
    if test_results['failed']:
        print("FAILED TESTS:")
        for fail in test_results['failed']:
            print(f"  ❌ {fail['test']}: {fail['reason']}")
        print()
    
    if test_results['warnings']:
        print("WARNINGS:")
        for warn in test_results['warnings']:
            print(f"  ⚠️  {warn['test']}: {warn['reason']}")
        print()
    
    print("=" * 80)
    
    return len(test_results['failed']) == 0

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
