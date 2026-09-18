#!/usr/bin/env python3
"""Live security probes against a running LivePaste server (port 8090). v2"""
import json
import sys
import urllib.request
import urllib.error

import os
BASE = os.environ.get("LIVEPASTE_BASE_URL", "http://127.0.0.1:8090")
PASS, FAIL, WARN = [], [], []

def req(method, path, body=None, headers=None, raw=False):
    url = BASE + path
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        code = resp.status
        rh = dict(resp.headers)
        payload = resp.read() if raw else resp.read()[:300]
        return code, rh, payload
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()[:2000]
    except Exception as e:
        return None, {}, str(e).encode()

def create_paste(content="probe", slug=None, **kw):
    body = {"content": content, "language": "plaintext", "expiry": "never"}
    if slug: body["customSlug"] = slug
    body.update(kw)
    code, _, payload = req("POST", "/api/paste", body)
    assert code == 200, f"create failed: {code} {payload[:150]}"
    return json.loads(payload)

def check(name, ok, detail="", warn=False):
    bucket = WARN if warn else (PASS if ok else FAIL)
    bucket.append(f"{name} :: {detail}")
    print(("PASS " if ok else ("WARN " if warn else "FAIL ")) + name + (f" :: {detail}" if detail else ""))

print("=" * 70)
print("SECTION 1: Path traversal & static containment")
print("=" * 70)
for path in [
    "/api/file/..%2f..%2f..%2fetc%2fpasswd",
    "/api/file/../../../../etc/passwd",
    "/api/paste/..%2f..%2fetc%2fpasswd",
    "/assets/..%2f..%2f..%2fpyproject.toml",
    "/static/..%2f..%2f..%2f..%2fpyproject.toml",
    "/..%2f..%2fpyproject.toml",
]:
    code, hdrs, body = req("GET", path, raw=True)
    leaked = (b"root:" in body or b"[build-system]" in body
              or b"fastapi" in body.lower() or b"editToken" in body)
    served_html = b"<div id=\"root\">" in body or b"text/html" in hdrs.get("content-type", "").encode()
    if code == 200 and leaked:
        check(f"traversal {path[:52]}", False, "LEAKED FILE CONTENT")
    elif code == 200 and served_html:
        check(f"traversal {path[:52]}", True, "200 but SPA-fallback HTML, not file")
    else:
        check(f"traversal {path[:52]}", True, f"-> {code}")

print()
print("=" * 70)
print("SECTION 2: Secret redaction & header hardening")
print("=" * 70)
create_paste("redaction probe", slug="sec-redact-1")
code, hdrs, body = req("GET", "/api/paste/sec-redact-1", raw=True)
doc = json.loads(body)
leaked = [k for k in ("editToken", "passwordHash", "burnedBy", "editors") if k in doc]
check("paste read redacts secrets", not leaked, f"leaked={leaked}")

code, hdrs, _ = req("GET", "/api/health")
csp = hdrs.get("content-security-policy", "")
for h, exp in [
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "sameorigin"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
]:
    check(f"header {h}", hdrs.get(h, "").lower() == exp, f"= {hdrs.get(h)!r}")
check("CSP frame-ancestors 'self'", "frame-ancestors 'self'" in csp)
check("CSP allows github api (fix verified)", "api.github.com" in csp)

print()
print("=" * 70)
print("SECTION 3: Password-locked paste enforcement")
print("=" * 70)
create_paste("locked probe", slug="sec-locked-1", password="hunter2-pass")
code, _, _ = req("GET", "/api/paste/sec-locked-1")
check("locked paste read without pw -> 401", code == 401, f"-> {code}")
code, _, _ = req("GET", "/api/paste/sec-locked-1?pw=wrong-guess")
check("locked paste wrong pw -> 401", code == 401, f"-> {code}")
code, hdrs, body = req("GET", "/api/paste/sec-locked-1", headers={"X-View-Password": "hunter2-pass"}, raw=True)
check("correct pw via header -> 200", code == 200, f"-> {code}")
if code == 200:
    check("correct pw read redacts token", "editToken" not in json.loads(body))
results = []
for i in range(10):
    code, _, _ = req("POST", "/api/paste/sec-locked-1/password", {"password": f"wrong{i}"})
    results.append(code)
check("brute-force lockout engages (429)", 429 in results, f"codes={results}")

print()
print("=" * 70)
print("SECTION 4: Edit-token authorization (REST)")
print("=" * 70)
p2 = create_paste("token probe", slug="sec-token-1")
token = p2["editToken"]
# Proper multipart WITH a file part (no file -> 422 validation error pre-auth)
boundary = "----probeboundary123"
mp = (
    f"--{boundary}\r\n"
    "Content-Disposition: form-data; name=\"editToken\"\r\n\r\n\r\n"
    f"--{boundary}\r\n"
    "Content-Disposition: form-data; name=\"file\"; filename=\"x.txt\"\r\n"
    "Content-Type: text/plain\r\n\r\n"
    "hello\r\n"
    f"--{boundary}--\r\n"
).encode()
code, _, _ = req("POST", "/api/paste/sec-token-1/file", None,
                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, raw=False)
check("file upload without token -> 403", code == 403, f"-> {code}")
code, _, _ = req("POST", "/api/paste/sec-token-1/file", None,
                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}; x=y"})
check("malformed multipart -> 4xx", code in (400, 403, 422), f"-> {code}")
code, _, body = req("POST", "/api/paste/sec-token-1/verify", {"editToken": "wrong"})
check("wrong token verify -> canEdit false", json.loads(body).get("canEdit") is False)
code, _, body = req("POST", "/api/paste/sec-token-1/verify", {"editToken": token})
check("right token verify -> canEdit true", json.loads(body).get("canEdit") is True)
code, _, _ = req("POST", "/api/paste/sec-token-1/restore", {"editToken": "wrong", "content": "hijack"})
check("restore wrong token -> 403", code == 403, f"-> {code}")
code, _, _ = req("DELETE", "/api/file/nonexistent-file-id-xyz")
check("delete unknown file -> 404", code == 404, f"-> {code}")

print()
print("=" * 70)
print("SECTION 5: XSS storage & content types")
print("=" * 70)
xss = '<script>alert(1)</script><img src=x onerror=alert(2)>'
create_paste(xss, slug="sec-xss-1")
code, hdrs, body = req("GET", "/api/paste/sec-xss-1", raw=True)
check("XSS payload stored as JSON data only", "application/json" in hdrs.get("content-type", ""),
      hdrs.get("content-type", "")[:40])

print()
print("=" * 70)
print("SECTION 6: Burn-after-read")
print("=" * 70)
try:
    create_paste("burn probe", slug="sec-burn-1", burnAfterViews=1)
    code, _, _ = req("GET", "/api/paste/sec-burn-1?count_view=true&clientId=burner-a")
    first = code
    code2, _, _ = req("GET", "/api/paste/sec-burn-1?count_view=true&clientId=burner-b")
    check("burn: first reader 200, next 404", first == 200 and code2 == 404, f"first={first} second={code2}")
except AssertionError as e:
    check("burn flow", False, str(e)[:80])

print()
print("=" * 70)
print("SECTION 7: Enumeration & input validation")
print("=" * 70)
code, _, _ = req("POST", "/api/paste", {"content": "x", "customSlug": "api"})
check("reserved slug rejected", code == 400, f"-> {code}")
code, _, _ = req("POST", "/api/paste", {"content": "x", "customSlug": "sec-redact-1"})
check("duplicate slug -> 409", code == 409, f"-> {code}")
code, _, _ = req("POST", "/api/paste", {"content": "x", "customSlug": "has space!"})
check("invalid slug chars rejected", code == 400, f"-> {code}")
code, _, _ = req("POST", "/api/paste", {"content": "x" * 500000})
check("oversize content -> 413", code == 413, f"-> {code}")
code, _, _ = req("POST", "/api/paste", {"content": "x", "expiry": "banana"})
check("invalid expiry -> 400", code == 400, f"-> {code}")
code, _, body = req("GET", "/api/paste/no-such-slug-xyz-999", raw=True)
check("unknown slug -> generic 404", code == 404, body.decode()[:60])

print()
print("=" * 70)
print("SECTION 8: Rate limiting (paste creation, 30/hour) — run LAST")
print("=" * 70)
codes = []
for i in range(40):
    code, _, _ = req("POST", "/api/paste", {"content": f"rate probe {i}"})
    codes.append(code)
    if code == 429:
        break
check("creation rate limit engages", 429 in codes, f"attempts={len(codes)} (budget shared with earlier probes)")

print()
print(f"RESULTS: {len(PASS)} pass, {len(FAIL)} fail, {len(WARN)} warn")
for f in FAIL:
    print("  FAILED:", f)
for w in WARN:
    print("  WARN:", w)
