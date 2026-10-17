"""
Test verification script for Token Gate Authentication (INT206, 2-Day Session)
"""

import time
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import json
import os
import sys

PORT = 8089

env = os.environ.copy()
env["PORT"] = str(PORT)
server_proc = subprocess.Popen(
    [sys.executable, "app.py"],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

time.sleep(1.5)

try:
    base_url = f"http://127.0.0.1:{PORT}"
    print(f"Testing Token Gate at {base_url}...")

    # 1. Test GET /api/companies without token -> MUST BE 401
    try:
        req = urllib.request.Request(f"{base_url}/api/companies")
        urllib.request.urlopen(req)
        print("[FAIL] Should have been 401 Unauthorized!")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        assert e.code == 401
        print("[PASS] Unauthenticated access to /api/companies correctly rejected with 401 Unauthorized")

    # 2. Test Login with WRONG token -> MUST BE 401
    login_data = json.dumps({"token": "WRONG1"}).encode("utf-8")
    req = urllib.request.Request(f"{base_url}/api/login", data=login_data, headers={
        "Content-Type": "application/json"
    }, method="POST")
    try:
        urllib.request.urlopen(req)
        print("[FAIL] Wrong token should have been rejected!")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        assert e.code == 401
        print("[PASS] Wrong token correctly rejected with 401 Unauthorized")

    # 3. Test Login with CORRECT token 'INT206' -> MUST BE 200 + Cookie Set
    login_data = json.dumps({"token": "INT206"}).encode("utf-8")
    req = urllib.request.Request(f"{base_url}/api/login", data=login_data, headers={
        "Content-Type": "application/json"
    }, method="POST")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        cookie = resp.headers.get("Set-Cookie")
        assert resp.status == 200
        assert data["status"] == "success"
        assert "cleanjob_session" in cookie
        assert "Max-Age=172800" in cookie  # 48 hours = 2 days
        session_token = data["session_token"]
        print(f"[PASS] Token 'INT206' accepted! Cookie set with 2-day expiry (Max-Age=172800): {cookie[:40]}...")

    # 4. Test GET /api/companies WITH Cookie -> MUST BE 200
    req = urllib.request.Request(f"{base_url}/api/companies", headers={
        "Cookie": cookie.split(";")[0]
    })
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert data["status"] == "success"
        print(f"[PASS] Authenticated request to /api/companies succeeded ({data['total']} companies)")

    # 5. Test POST /api/clean WITH Cookie -> MUST BE 200
    with open("example_file/24 NSW - Sheet1.csv", "rb") as f:
        clean_bytes = f.read()

    clean_url = f"{base_url}/api/clean?filename=" + urllib.parse.quote("24 NSW - Sheet1.csv")
    req = urllib.request.Request(clean_url, data=clean_bytes, headers={
        "Content-Type": "text/csv",
        "Content-Length": str(len(clean_bytes)),
        "Cookie": cookie.split(";")[0]
    }, method="POST")

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert data["status"] == "success"
        print(f"[PASS] Authenticated POST /api/clean succeeded (cleaned {data['kept_rows']} rows)")

    print("\nALL TOKEN GATE & 2-DAY SESSION TESTS PASSED 100%!")

finally:
    server_proc.terminate()
    server_proc.wait()
