#!/usr/bin/env python3
"""
LivePaste Backend API & WebSocket Tests
Tests all REST endpoints and WebSocket real-time sync functionality
"""
import requests
import json
import time
import asyncio
import websockets
from datetime import datetime
from io import BytesIO
from PIL import Image

BASE_URL = "https://command-hub-119.preview.emergentagent.com"
WS_URL = "wss://livepaste.preview.emergentagent.com"

class TestResults:
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def record_pass(self, test_name):
        self.total += 1
        self.passed += 1
        print(f"✅ PASS: {test_name}")
    
    def record_fail(self, test_name, reason):
        self.total += 1
        self.failed += 1
        error_msg = f"❌ FAIL: {test_name} - {reason}"
        print(error_msg)
        self.errors.append(error_msg)
    
    def summary(self):
        print("\n" + "="*60)
        print(f"TEST SUMMARY: {self.passed}/{self.total} passed")
        print("="*60)
        if self.errors:
            print("\nFailed tests:")
            for err in self.errors:
                print(f"  {err}")
        return self.passed == self.total

results = TestResults()

def test_create_paste_random_slug():
    """Test POST /api/paste with random slug generation"""
    try:
        payload = {
            "content": "Test content for random slug",
            "language": "python",
            "expiry": "1d"
        }
        resp = requests.post(f"{BASE_URL}/api/paste", json=payload, timeout=10)
        
        if resp.status_code != 200:
            results.record_fail("Create paste (random slug)", f"Expected 200, got {resp.status_code}")
            return None
        
        data = resp.json()
        required_fields = ["slug", "content", "language", "expiresAt"]
        missing = [f for f in required_fields if f not in data]
        
        if missing:
            results.record_fail("Create paste (random slug)", f"Missing fields: {missing}")
            return None
        
        if not data["slug"] or len(data["slug"]) < 3:
            results.record_fail("Create paste (random slug)", f"Invalid slug: {data['slug']}")
            return None
        
        results.record_pass("Create paste (random slug)")
        return data["slug"]
    except Exception as e:
        results.record_fail("Create paste (random slug)", str(e))
        return None

def test_create_paste_custom_slug():
    """Test POST /api/paste with valid custom slug"""
    try:
        custom_slug = f"test-custom-{int(time.time())}"
        payload = {
            "content": "Test content with custom slug",
            "customSlug": custom_slug,
            "language": "javascript",
            "expiry": "never"
        }
        resp = requests.post(f"{BASE_URL}/api/paste", json=payload, timeout=10)
        
        if resp.status_code != 200:
            results.record_fail("Create paste (custom slug)", f"Expected 200, got {resp.status_code}")
            return None
        
        data = resp.json()
        if data["slug"] != custom_slug:
            results.record_fail("Create paste (custom slug)", f"Expected slug '{custom_slug}', got '{data['slug']}'")
            return None
        
        results.record_pass("Create paste (custom slug)")
        return custom_slug
    except Exception as e:
        results.record_fail("Create paste (custom slug)", str(e))
        return None

def test_duplicate_custom_slug(existing_slug):
    """Test POST /api/paste with duplicate custom slug (should return 409)"""
    try:
        payload = {
            "content": "Duplicate slug test",
            "customSlug": existing_slug,
            "language": "plaintext",
            "expiry": "never"
        }
        resp = requests.post(f"{BASE_URL}/api/paste", json=payload, timeout=10)
        
        if resp.status_code == 409:
            results.record_pass("Duplicate custom slug (409)")
        else:
            results.record_fail("Duplicate custom slug (409)", f"Expected 409, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Duplicate custom slug (409)", str(e))

def test_invalid_custom_slug():
    """Test POST /api/paste with invalid custom slug (spaces/special chars, should return 400)"""
    try:
        payload = {
            "content": "Invalid slug test",
            "customSlug": "invalid slug with spaces!",
            "language": "plaintext",
            "expiry": "never"
        }
        resp = requests.post(f"{BASE_URL}/api/paste", json=payload, timeout=10)
        
        if resp.status_code == 400:
            results.record_pass("Invalid custom slug (400)")
        else:
            results.record_fail("Invalid custom slug (400)", f"Expected 400, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Invalid custom slug (400)", str(e))

def test_reserved_slug():
    """Test POST /api/paste with reserved slug like 'api' (should return 400)"""
    try:
        payload = {
            "content": "Reserved slug test",
            "customSlug": "api",
            "language": "plaintext",
            "expiry": "never"
        }
        resp = requests.post(f"{BASE_URL}/api/paste", json=payload, timeout=10)
        
        if resp.status_code == 400:
            results.record_pass("Reserved slug 'api' (400)")
        else:
            results.record_fail("Reserved slug 'api' (400)", f"Expected 400, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Reserved slug 'api' (400)", str(e))

def test_get_paste(slug):
    """Test GET /api/paste/{slug}"""
    try:
        resp = requests.get(f"{BASE_URL}/api/paste/{slug}", timeout=10)
        
        if resp.status_code != 200:
            results.record_fail("Get paste", f"Expected 200, got {resp.status_code}")
            return False
        
        data = resp.json()
        if data["slug"] != slug:
            results.record_fail("Get paste", f"Slug mismatch: expected '{slug}', got '{data['slug']}'")
            return False
        
        results.record_pass("Get paste")
        return True
    except Exception as e:
        results.record_fail("Get paste", str(e))
        return False

def test_get_paste_with_view_count(slug):
    """Test GET /api/paste/{slug}?count_view=true (should increment views)"""
    try:
        # Get initial view count
        resp1 = requests.get(f"{BASE_URL}/api/paste/{slug}", timeout=10)
        if resp1.status_code != 200:
            results.record_fail("Get paste with view count", f"Initial GET failed: {resp1.status_code}")
            return
        
        initial_views = resp1.json().get("views", 0)
        
        # Get with count_view=true
        resp2 = requests.get(f"{BASE_URL}/api/paste/{slug}?count_view=true", timeout=10)
        if resp2.status_code != 200:
            results.record_fail("Get paste with view count", f"count_view GET failed: {resp2.status_code}")
            return
        
        new_views = resp2.json().get("views", 0)
        
        if new_views == initial_views + 1:
            results.record_pass("Get paste with view count increment")
        else:
            results.record_fail("Get paste with view count increment", f"Expected views {initial_views + 1}, got {new_views}")
    except Exception as e:
        results.record_fail("Get paste with view count increment", str(e))

def test_get_nonexistent_paste():
    """Test GET /api/paste/{slug} for non-existent slug (should return 404)"""
    try:
        resp = requests.get(f"{BASE_URL}/api/paste/doesnotexist999", timeout=10)
        
        if resp.status_code == 404:
            results.record_pass("Get non-existent paste (404)")
        else:
            results.record_fail("Get non-existent paste (404)", f"Expected 404, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Get non-existent paste (404)", str(e))

async def test_websocket_connection(slug):
    """Test WebSocket connection and initial state"""
    try:
        uri = f"{WS_URL}/api/ws/{slug}"
        async with websockets.connect(uri, open_timeout=10) as ws:
            # Should receive init message
            msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(msg_raw)
            
            if msg.get("type") != "init":
                results.record_fail("WebSocket init message", f"Expected type 'init', got '{msg.get('type')}'")
                return False
            
            if "paste" not in msg or "viewers" not in msg:
                results.record_fail("WebSocket init message", f"Missing fields in init message")
                return False
            
            results.record_pass("WebSocket connection & init message")
            return True
    except Exception as e:
        results.record_fail("WebSocket connection & init message", str(e))
        return False

async def test_websocket_realtime_sync(slug):
    """Test WebSocket real-time sync between 2 clients"""
    try:
        uri = f"{WS_URL}/api/ws/{slug}"
        
        # Connect client A
        ws_a = await websockets.connect(uri, open_timeout=10)
        init_a = await asyncio.wait_for(ws_a.recv(), timeout=5)
        
        # Connect client B
        ws_b = await websockets.connect(uri, open_timeout=10)
        init_b = await asyncio.wait_for(ws_b.recv(), timeout=5)
        
        # Client A should receive presence update (2 viewers now)
        try:
            presence_msg = await asyncio.wait_for(ws_a.recv(), timeout=3)
            presence = json.loads(presence_msg)
            if presence.get("type") == "presence" and presence.get("viewers") == 2:
                results.record_pass("WebSocket presence update (2 viewers)")
            else:
                results.record_fail("WebSocket presence update (2 viewers)", f"Unexpected message: {presence}")
        except asyncio.TimeoutError:
            results.record_fail("WebSocket presence update (2 viewers)", "No presence message received")
        
        # Client A sends edit
        test_content = f"Real-time edit test at {datetime.now().isoformat()}"
        await ws_a.send(json.dumps({"type": "edit", "content": test_content}))
        
        # Client B should receive the edit
        try:
            edit_msg = await asyncio.wait_for(ws_b.recv(), timeout=5)
            edit = json.loads(edit_msg)
            
            if edit.get("type") == "edit" and edit.get("content") == test_content:
                results.record_pass("WebSocket real-time edit broadcast")
            else:
                results.record_fail("WebSocket real-time edit broadcast", f"Expected edit with content, got: {edit}")
        except asyncio.TimeoutError:
            results.record_fail("WebSocket real-time edit broadcast", "Client B did not receive edit")
        
        # Verify content persisted to DB
        await asyncio.sleep(0.5)  # Give DB time to update
        resp = requests.get(f"{BASE_URL}/api/paste/{slug}", timeout=10)
        if resp.status_code == 200:
            db_content = resp.json().get("content", "")
            if db_content == test_content:
                results.record_pass("WebSocket edit persists to DB")
            else:
                results.record_fail("WebSocket edit persists to DB", f"DB content mismatch: '{db_content}' != '{test_content}'")
        else:
            results.record_fail("WebSocket edit persists to DB", f"GET failed: {resp.status_code}")
        
        # Test language change broadcast
        await ws_a.send(json.dumps({"type": "language", "language": "python"}))
        try:
            lang_msg = await asyncio.wait_for(ws_b.recv(), timeout=5)
            lang = json.loads(lang_msg)
            
            if lang.get("type") == "language" and lang.get("language") == "python":
                results.record_pass("WebSocket language change broadcast")
            else:
                results.record_fail("WebSocket language change broadcast", f"Unexpected message: {lang}")
        except asyncio.TimeoutError:
            results.record_fail("WebSocket language change broadcast", "Client B did not receive language change")
        
        await ws_a.close()
        await ws_b.close()
        
    except Exception as e:
        results.record_fail("WebSocket real-time sync", str(e))

async def test_websocket_nonexistent_slug():
    """Test WebSocket to non-existent slug (should return error and close)"""
    try:
        uri = f"{WS_URL}/api/ws/doesnotexist999"
        ws = await websockets.connect(uri, open_timeout=10)
        
        # Should receive error message
        msg_raw = await asyncio.wait_for(ws.recv(), timeout=5)
        msg = json.loads(msg_raw)
        
        if msg.get("type") == "error" and msg.get("code") == "not_found":
            results.record_pass("WebSocket non-existent slug error")
        else:
            results.record_fail("WebSocket non-existent slug error", f"Expected error with code 'not_found', got: {msg}")
        
        # Connection should close
        try:
            await asyncio.wait_for(ws.wait_closed(), timeout=3)
            results.record_pass("WebSocket closes after not_found error")
        except asyncio.TimeoutError:
            results.record_fail("WebSocket closes after not_found error", "Connection did not close")
        
    except Exception as e:
        results.record_fail("WebSocket non-existent slug", str(e))

def create_test_image():
    """Create a small test PNG image in memory"""
    img = Image.new('RGB', (100, 100), color='red')
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf

def test_upload_image(slug):
    """Test POST /api/paste/{slug}/image with valid PNG"""
    try:
        img_buf = create_test_image()
        files = {'file': ('test.png', img_buf, 'image/png')}
        
        resp = requests.post(f"{BASE_URL}/api/paste/{slug}/image", files=files, timeout=30)
        
        if resp.status_code != 200:
            results.record_fail("Upload image (valid PNG)", f"Expected 200, got {resp.status_code}: {resp.text}")
            return None
        
        data = resp.json()
        required_fields = ["id", "url", "name", "size", "contentType"]
        missing = [f for f in required_fields if f not in data]
        
        if missing:
            results.record_fail("Upload image (valid PNG)", f"Missing fields: {missing}")
            return None
        
        if not data["id"] or len(data["id"]) != 24:
            results.record_fail("Upload image (valid PNG)", f"Invalid image ID: {data['id']}")
            return None
        
        if data["contentType"] != "image/png":
            results.record_fail("Upload image (valid PNG)", f"Wrong content type: {data['contentType']}")
            return None
        
        results.record_pass("Upload image (valid PNG)")
        return data["id"]
    except Exception as e:
        results.record_fail("Upload image (valid PNG)", str(e))
        return None

def test_get_image(image_id):
    """Test GET /api/image/{id}"""
    try:
        resp = requests.get(f"{BASE_URL}/api/image/{image_id}", timeout=10)
        
        if resp.status_code != 200:
            results.record_fail("Get image", f"Expected 200, got {resp.status_code}")
            return False
        
        if not resp.content or len(resp.content) == 0:
            results.record_fail("Get image", "Empty response body")
            return False
        
        content_type = resp.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            results.record_fail("Get image", f"Wrong content type: {content_type}")
            return False
        
        results.record_pass("Get image")
        return True
    except Exception as e:
        results.record_fail("Get image", str(e))
        return False

def test_upload_non_image(slug):
    """Test POST /api/paste/{slug}/image with non-image content (should return 400)"""
    try:
        files = {'file': ('test.txt', BytesIO(b'not an image'), 'text/plain')}
        resp = requests.post(f"{BASE_URL}/api/paste/{slug}/image", files=files, timeout=10)
        
        if resp.status_code == 400:
            results.record_pass("Upload non-image file (400)")
        else:
            results.record_fail("Upload non-image file (400)", f"Expected 400, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Upload non-image file (400)", str(e))

def test_upload_image_nonexistent_slug():
    """Test POST /api/paste/{slug}/image to non-existent slug (should return 404)"""
    try:
        img_buf = create_test_image()
        files = {'file': ('test.png', img_buf, 'image/png')}
        resp = requests.post(f"{BASE_URL}/api/paste/doesnotexist999/image", files=files, timeout=10)
        
        if resp.status_code == 404:
            results.record_pass("Upload image to non-existent slug (404)")
        else:
            results.record_fail("Upload image to non-existent slug (404)", f"Expected 404, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Upload image to non-existent slug (404)", str(e))

def test_delete_image(image_id):
    """Test DELETE /api/image/{id}"""
    try:
        resp = requests.delete(f"{BASE_URL}/api/image/{image_id}", timeout=10)
        
        if resp.status_code != 200:
            results.record_fail("Delete image", f"Expected 200, got {resp.status_code}")
            return False
        
        data = resp.json()
        if not data.get("ok"):
            results.record_fail("Delete image", f"Expected ok:true, got: {data}")
            return False
        
        results.record_pass("Delete image")
        return True
    except Exception as e:
        results.record_fail("Delete image", str(e))
        return False

def test_get_deleted_image(image_id):
    """Test GET /api/image/{id} after deletion (should return 404)"""
    try:
        resp = requests.get(f"{BASE_URL}/api/image/{image_id}", timeout=10)
        
        if resp.status_code == 404:
            results.record_pass("Get deleted image (404)")
        else:
            results.record_fail("Get deleted image (404)", f"Expected 404, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Get deleted image (404)", str(e))

def test_get_invalid_image_id():
    """Test GET /api/image/{invalid-id} (should return 404)"""
    try:
        resp = requests.get(f"{BASE_URL}/api/image/invalidid123", timeout=10)
        
        if resp.status_code == 404:
            results.record_pass("Get invalid image ID (404)")
        else:
            results.record_fail("Get invalid image ID (404)", f"Expected 404, got {resp.status_code}")
    except Exception as e:
        results.record_fail("Get invalid image ID (404)", str(e))

def main():
    print("="*60)
    print("LivePaste Backend API & WebSocket Tests")
    print(f"Testing: {BASE_URL}")
    print("="*60 + "\n")
    
    # REST API Tests
    print("--- REST API Tests ---\n")
    
    # Test 1: Create paste with random slug
    random_slug = test_create_paste_random_slug()
    
    # Test 2: Create paste with custom slug
    custom_slug = test_create_paste_custom_slug()
    
    # Test 3: Duplicate custom slug
    if custom_slug:
        test_duplicate_custom_slug(custom_slug)
    
    # Test 4: Invalid custom slug
    test_invalid_custom_slug()
    
    # Test 5: Reserved slug
    test_reserved_slug()
    
    # Test 6: Get paste
    if random_slug:
        test_get_paste(random_slug)
        test_get_paste_with_view_count(random_slug)
    
    # Test 7: Get non-existent paste
    test_get_nonexistent_paste()
    
    # Image API Tests
    print("\n--- Image API Tests ---\n")
    
    # Create a paste for image tests
    image_test_slug = test_create_paste_custom_slug()
    
    if image_test_slug:
        # Test 8: Upload valid image
        image_id = test_upload_image(image_test_slug)
        
        # Test 9: Get uploaded image
        if image_id:
            test_get_image(image_id)
        
        # Test 10: Upload non-image file (should fail with 400)
        test_upload_non_image(image_test_slug)
        
        # Test 11: Delete image
        if image_id:
            test_delete_image(image_id)
            # Test 12: Get deleted image (should return 404)
            test_get_deleted_image(image_id)
    
    # Test 13: Upload to non-existent slug
    test_upload_image_nonexistent_slug()
    
    # Test 14: Get invalid image ID
    test_get_invalid_image_id()
    
    # WebSocket Tests
    print("\n--- WebSocket Tests ---\n")
    
    # Create a fresh paste for WebSocket tests
    ws_test_slug = test_create_paste_custom_slug()
    
    if ws_test_slug:
        # Test 15: WebSocket connection
        asyncio.run(test_websocket_connection(ws_test_slug))
        
        # Test 16: Real-time sync between 2 clients
        asyncio.run(test_websocket_realtime_sync(ws_test_slug))
    
    # Test 17: WebSocket to non-existent slug
    asyncio.run(test_websocket_nonexistent_slug())
    
    # Print summary
    success = results.summary()
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())
