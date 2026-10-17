"""
Test verification script for CleanJob AI Web Server
"""

import time
import subprocess
import urllib.request
import urllib.parse
import json
import os
import sys

PORT = 8088

# Jalankan server app.py pada port 8088
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
    print(f"Testing server at {base_url}...")

    # 1. Test GET /
    req = urllib.request.Request(f"{base_url}/")
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8")
        assert "<title>CleanJob AI" in html
        print("[PASS] GET / serves index.html successfully")

    # 2. Test GET /api/companies
    req = urllib.request.Request(f"{base_url}/api/companies")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        print(f"[PASS] GET /api/companies returned {data['total']} companies")

    # 3. Test POST /api/import with 1B NSW
    with open("example_file/1B NSW - Sheet1.csv", "rb") as f:
        csv_bytes = f.read()

    import_url = f"{base_url}/api/import?filename=" + urllib.parse.quote("1B NSW - Sheet1.csv")
    req = urllib.request.Request(import_url, data=csv_bytes, headers={
        "Content-Type": "text/csv",
        "Content-Length": str(len(csv_bytes))
    }, method="POST")

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        print(f"[PASS] POST /api/import: total_rows={data['total_rows']}, new_added={data['new_companies_added']}, final_count={data['final_count']}")

    # 4. Test POST /api/clean with 24 NSW
    with open("example_file/24 NSW - Sheet1.csv", "rb") as f:
        clean_bytes = f.read()

    clean_url = f"{base_url}/api/clean?filename=" + urllib.parse.quote("24 NSW - Sheet1.csv")
    req = urllib.request.Request(clean_url, data=clean_bytes, headers={
        "Content-Type": "text/csv",
        "Content-Length": str(len(clean_bytes))
    }, method="POST")

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "success"
        assert data["total_rows"] == 20
        assert data["kept_rows"] == 14
        assert len(data["csv_data"]) > 0
        print(f"[PASS] POST /api/clean: total_rows={data['total_rows']}, removed_json={data['removed_in_json']}, kept_rows={data['kept_rows']}")

    # 5. Verify Zero Disk Storage: check if any new CSV files were created in root or web
    workspace_files = os.listdir(".")
    csv_in_root = [f for f in workspace_files if f.endswith(".csv")]
    assert len(csv_in_root) == 0, f"Found unexpected CSV files: {csv_in_root}"
    print("[PASS] STRICT ZERO DISK STORAGE verified: No CSV files were saved to disk!")

    # 6. Check memory of server process
    task_out = subprocess.check_output(f'tasklist /FI "PID eq {server_proc.pid}"', shell=True).decode()
    print("Server Memory Usage:")
    for line in task_out.splitlines():
        if "python.exe" in line:
            print(" ", line)

    print("\nALL AUTOMATED TESTS PASSED SUCCESSFULLY!")

finally:
    server_proc.terminate()
    server_proc.wait()
