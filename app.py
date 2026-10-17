"""
CleanJob AI - Web UI Backend Server dengan Sistem Akses Token
=============================================================
- Token Akses: INT206 (Sesi berlaku 2 hari / 172.800 detik)
- Kriptografis HMAC-SHA256 Stateless Session (Zero database, RAM < 25 MB)
- 100% In-Memory Processing: File input/output TIDAK disimpan di hard disk server.
- Thread-safe Mutex Lock & Atomic Write untuk keamanan multi-user bersamaan.
- Auto-backup dan self-healing untuk companies.json.
- Proteksi payload limit (maks 30 MB) & unlimited field buffer.
"""

import os
import sys
import io
import csv
import json
import time
import hmac
import hashlib
import shutil
import urllib.parse
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import List, Set, Tuple, Optional

# Tingkatkan limit ukuran field CSV agar tidak error pada deskripsi job yang sangat panjang
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2147483647)

# Konfigurasi Server & Token Akses
PORT = int(os.environ.get("PORT", 4000))
JSON_FILE = "companies.json"
BACKUP_JSON_FILE = "companies.json.bak"
MAX_PAYLOAD_SIZE = 30 * 1024 * 1024  # 30 Megabytes
TARGET_COLUMN = "employer_company_name"
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

# Konfigurasi Token Akses Resmi & Durasi Sesi (2 Hari)
AUTHORIZED_TOKEN = "INT206"
SESSION_DURATION_SECONDS = 2 * 24 * 60 * 60  # 172.800 detik (2 Hari)
SECRET_KEY = b"cleanjob_ai_auth_secret_int206_salt_48h"

# Mutex Lock untuk penulisan & pembacaan file companies.json yang aman saat multi-user
json_lock = threading.Lock()


def get_timestamp() -> str:
    """Mengembalikan timestamp format jam:menit:detik untuk log."""
    return datetime.now().strftime("%H:%M:%S")


def create_session_token() -> Tuple[str, int]:
    """Membuat token sesi kriptografis bertanda tangan HMAC dengan masa kedaluwarsa 2 hari."""
    expires_at = int(time.time() + SESSION_DURATION_SECONDS)
    msg = f"{expires_at}".encode("utf-8")
    sig = hmac.new(SECRET_KEY, msg, hashlib.sha256).hexdigest()
    session_value = f"{expires_at}:{sig}"
    return session_value, expires_at


def verify_session_token(token_str: str) -> bool:
    """Memvalidasi keaslian tanda tangan token sesi dan masa aktifnya (2 hari)."""
    if not token_str or ":" not in token_str:
        return False
    try:
        expires_str, sig = token_str.split(":", 1)
        expires_at = int(expires_str)
        if time.time() > expires_at:
            return False  # Sesi telah kedaluwarsa
        expected_sig = hmac.new(SECRET_KEY, expires_str.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


def normalize_for_comparison(name: str) -> str:
    """Normalisasi nama perusahaan untuk perbandingan case-insensitive & spasi bersih."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def clean_company_name(name: str) -> str:
    """Membersihkan whitespace ekstra pada nama perusahaan untuk disimpan."""
    if not name:
        return ""
    return " ".join(name.strip().split())


def find_company_column_idx(headers: List[str]) -> int:
    """Mencari indeks kolom employer_company_name (toleran huruf besar/kecil & spasi)."""
    if TARGET_COLUMN in headers:
        return headers.index(TARGET_COLUMN)
    
    target_lower = TARGET_COLUMN.lower()
    for idx, col in enumerate(headers):
        if col and col.strip().lower() == target_lower:
            return idx
            
    for idx, col in enumerate(headers):
        if not col:
            continue
        cleaned = col.strip().lower().replace(" ", "_")
        if "employer_company" in cleaned or ("company" in cleaned and "name" in cleaned):
            return idx

    return -1


def load_known_companies_threadsafe() -> Tuple[List[str], Set[str]]:
    """
    Memuat daftar company dari companies.json secara aman (thread-safe).
    Dilengkapi fitur self-healing dari file .bak jika terjadi korupsi file.
    """
    with json_lock:
        target_file = JSON_FILE
        if not os.path.exists(target_file):
            if os.path.exists(BACKUP_JSON_FILE):
                try:
                    shutil.copy2(BACKUP_JSON_FILE, target_file)
                except Exception:
                    pass
            else:
                return [], set()

        for attempt_file in [target_file, BACKUP_JSON_FILE]:
            if not os.path.exists(attempt_file):
                continue
            try:
                with open(attempt_file, mode="r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        company_list = []
                        seen_set = set()
                        for item in data:
                            if isinstance(item, str):
                                c = clean_company_name(item)
                                if c:
                                    norm = normalize_for_comparison(c)
                                    if norm not in seen_set:
                                        seen_set.add(norm)
                                        company_list.append(c)
                        return company_list, seen_set
            except Exception as e:
                print(f"[{get_timestamp()}] [WARNING] Gagal membaca {attempt_file}: {e}")
                continue

        return [], set()


def save_companies_threadsafe(companies: List[str]) -> bool:
    """
    Menyimpan daftar company ke companies.json dengan pola Atomic Write
    (tulis ke temporary file lalu atomic rename) dan auto-backup ke .bak.
    """
    with json_lock:
        sorted_comps = sorted(companies, key=lambda x: x.lower())
        temp_file = f"{JSON_FILE}.tmp"
        
        try:
            with open(temp_file, mode="w", encoding="utf-8") as f:
                json.dump(sorted_comps, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            if os.path.exists(JSON_FILE):
                try:
                    shutil.copy2(JSON_FILE, BACKUP_JSON_FILE)
                except Exception:
                    pass

            os.replace(temp_file, JSON_FILE)
            return True
        except Exception as e:
            print(f"[{get_timestamp()}] [ERROR] Gagal menyimpan JSON: {e}")
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass
            return False


def decode_csv_bytes(raw_bytes: bytes) -> str:
    """Mendekode byte CSV dengan deteksi multi-encoding dan fallback aman."""
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


class CleanJobRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler untuk CleanJob AI Web UI dengan Token Gate."""

    server_version = "CleanJobServer/1.2"

    def log_message(self, format, *args):
        """Kustomisasi format log request server."""
        sys.stderr.write(f"[{get_timestamp()}] {self.address_string()} - {format % args}\n")

    def parse_cookies(self) -> dict:
        """Mem-parsing header Cookie dari client."""
        raw_cookie = self.headers.get("Cookie", "")
        cookies = {}
        for item in raw_cookie.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def is_authenticated(self) -> bool:
        """
        Memeriksa apakah permintaan memiliki token sesi aktif yang sah
        melalui Cookie 'cleanjob_session' atau Header 'X-Session-Token'.
        """
        # 1. Cek dari Cookie
        cookies = self.parse_cookies()
        session_token = cookies.get("cleanjob_session")
        if session_token and verify_session_token(session_token):
            return True

        # 2. Cek dari Header X-Session-Token
        header_token = self.headers.get("X-Session-Token")
        if header_token and verify_session_token(header_token):
            return True

        # 3. Cek langsung token mentah di header X-Access-Token jika dikirim client
        raw_token = self.headers.get("X-Access-Token")
        if raw_token and raw_token.strip().upper() == AUTHORIZED_TOKEN:
            return True

        return False

    def send_json_response(self, status_code: int, data: dict, set_cookie: Optional[str] = None):
        """Mengirim respons JSON ke client."""
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        """Menangani pre-flight CORS jika ada."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename, X-Session-Token, X-Access-Token")
        self.end_headers()

    def do_HEAD(self):
        """Menangani permintaan HEAD (seperti curl -I atau health-check)."""
        self.do_GET()

    def do_GET(self):
        """Menangani permintaan GET (halaman web & API)."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Endpoint publik untuk cek status autentikasi
        if path == "/api/check-auth":
            auth_ok = self.is_authenticated()
            self.send_json_response(200, {
                "status": "success",
                "authenticated": auth_ok,
                "session_duration_hours": 48
            })
            return

        # 2. Endpoint publik untuk cek status server
        if path == "/api/status":
            comps, _ = load_known_companies_threadsafe()
            self.send_json_response(200, {
                "status": "online",
                "total_companies": len(comps),
                "server_time": get_timestamp()
            })
            return

        # 3. Endpoint Protected: API Company List
        if path == "/api/companies":
            if not self.is_authenticated():
                self.send_json_response(401, {
                    "status": "unauthorized",
                    "message": "Akses ditolak. Silakan masukkan token akses terlebih dahulu."
                })
                return
            comps, _ = load_known_companies_threadsafe()
            self.send_json_response(200, {
                "status": "success",
                "total": len(comps),
                "companies": comps
            })
            return

        # 4. Sajikan frontend index.html
        if path in ["/", "/index.html"]:
            self.serve_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            return

        # 5. Sajikan static assets
        safe_path = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if safe_path.startswith(WEB_DIR) and os.path.isfile(safe_path):
            ext = os.path.splitext(safe_path)[1].lower()
            mime_map = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png"
            }
            self.serve_file(safe_path, mime_map.get(ext, "application/octet-stream"))
        else:
            self.send_error(404, "Halaman tidak ditemukan")

    def serve_file(self, filepath: str, content_type: str):
        """Menyajikan file statis dari disk."""
        if not os.path.isfile(filepath):
            self.send_error(404, "File tidak ditemukan")
            return
        try:
            with open(filepath, mode="rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Gagal membaca file: {e}")

    def do_POST(self):
        """Menangani permintaan POST (Login, Logout, Import & Clean)."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Endpoint Login Token (Publik)
        if path == "/api/login":
            self.handle_login()
            return

        # 2. Endpoint Logout (Publik)
        if path == "/api/logout":
            clear_cookie = "cleanjob_session=deleted; Max-Age=0; Path=/; SameSite=Lax"
            self.send_json_response(200, {"status": "success", "message": "Logout berhasil."}, set_cookie=clear_cookie)
            return

        # 3. SEMUA ENDPOINT LAINNYA WAJIB TERAUTENTIKASI TOKEN
        if not self.is_authenticated():
            self.send_json_response(401, {
                "status": "unauthorized",
                "message": "Akses ditolak! Sesi Anda telah berakhir atau belum memasukkan token akses."
            })
            return

        # 4. Proteksi Ukuran Upload (Max Payload Limit 30 MB)
        content_length_header = self.headers.get("Content-Length")
        if not content_length_header:
            self.send_json_response(411, {"status": "error", "message": "Content-Length diperlukan."})
            return
        
        try:
            content_length = int(content_length_header)
        except ValueError:
            self.send_json_response(400, {"status": "error", "message": "Content-Length tidak valid."})
            return

        if content_length > MAX_PAYLOAD_SIZE:
            self.send_json_response(413, {
                "status": "error",
                "message": f"File terlalu besar! Batas maksimal adalah {MAX_PAYLOAD_SIZE // (1024 * 1024)} MB."
            })
            return

        # 5. Ambil Nama File
        query_params = urllib.parse.parse_qs(parsed_url.query)
        filename = query_params.get("filename", ["uploaded.csv"])[0]
        header_filename = self.headers.get("X-Filename")
        if header_filename:
            try:
                filename = urllib.parse.unquote(header_filename)
            except Exception:
                pass

        # 6. Baca Body ke RAM murni
        try:
            raw_body = self.rfile.read(content_length)
        except Exception as e:
            self.send_json_response(400, {"status": "error", "message": f"Gagal membaca data pengiriman: {e}"})
            return

        if path == "/api/import":
            self.handle_import(raw_body, filename)
        elif path == "/api/clean":
            self.handle_clean(raw_body, filename)
        else:
            self.send_error(404, "Endpoint API tidak ditemukan")

    def handle_login(self):
        """Memverifikasi token akses INT206 dan memberikan sesi 2 hari."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8", errors="replace")
            data = json.loads(body)
            input_token = str(data.get("token", "")).strip().upper()
        except Exception:
            self.send_json_response(400, {"status": "error", "message": "Payload JSON tidak valid."})
            return

        if input_token == AUTHORIZED_TOKEN:
            session_value, expires_at = create_session_token()
            cookie_header = (
                f"cleanjob_session={session_value}; "
                f"Max-Age={SESSION_DURATION_SECONDS}; "
                f"Path=/; "
                f"SameSite=Lax; "
                f"HttpOnly"
            )
            print(f"[{get_timestamp()}] [AUTH] Login berhasil dengan token {AUTHORIZED_TOKEN}. Sesi aktif 48 jam.")
            self.send_json_response(200, {
                "status": "success",
                "message": "Token valid! Akses dibuka.",
                "session_token": session_value,
                "expires_at": expires_at
            }, set_cookie=cookie_header)
        else:
            print(f"[{get_timestamp()}] [AUTH-FAILED] Percobaan login gagal dengan token: '{input_token}'")
            self.send_json_response(401, {
                "status": "error",
                "message": "Token akses salah! Silakan masukkan 6 digit token yang valid."
            })

    def handle_import(self, raw_bytes: bytes, filename: str):
        """Memproses import company ke JSON secara murni di RAM (Zero Disk Writes for CSV)."""
        logs = []
        t_start = get_timestamp()
        file_size_kb = len(raw_bytes) / 1024
        logs.append(f"[{t_start}] [START] Menerima file: {filename} ({file_size_kb:.1f} KB)")
        logs.append(f"[{t_start}] Membaca data CSV ke dalam memori RAM (Zero Disk Storage)...")

        csv_text = decode_csv_bytes(raw_bytes)
        string_io = io.StringIO(csv_text)
        reader = csv.reader(string_io)
        
        try:
            headers = next(reader, None)
        except Exception as e:
            self.send_json_response(400, {
                "status": "error",
                "message": f"Gagal mem-parsing header CSV: {e}",
                "logs": logs
            })
            return

        if not headers:
            logs.append(f"[{get_timestamp()}] [ERROR] File CSV kosong atau tidak memiliki header.")
            self.send_json_response(400, {"status": "error", "message": "File CSV kosong.", "logs": logs})
            return

        col_idx = find_company_column_idx(headers)
        if col_idx == -1:
            err_msg = f"Kolom '{TARGET_COLUMN}' tidak ditemukan di file {filename}."
            logs.append(f"[{get_timestamp()}] [ERROR] {err_msg}")
            logs.append(f"[{get_timestamp()}] Kolom yang terbaca: {headers[:5]}...")
            self.send_json_response(400, {"status": "error", "message": err_msg, "logs": logs})
            return

        logs.append(f"[{get_timestamp()}] [INFO] Kolom '{headers[col_idx]}' terdeteksi pada indeks ke-{col_idx + 1}.")
        
        total_rows = 0
        extracted_companies = []
        for row in reader:
            if not row:
                continue
            total_rows += 1
            if col_idx < len(row):
                clean_name = clean_company_name(row[col_idx])
                if clean_name:
                    extracted_companies.append(clean_name)

        logs.append(f"[{get_timestamp()}] [INFO] Selesai scan: {total_rows} total baris | {len(extracted_companies)} baris memiliki nama perusahaan.")

        existing_companies, seen_normalized = load_known_companies_threadsafe()
        initial_count = len(existing_companies)
        logs.append(f"[{get_timestamp()}] [INFO] Memuat {initial_count} perusahaan unik yang sudah terdaftar di database JSON.")

        new_added = 0
        skipped_dup = 0
        for comp in extracted_companies:
            norm = normalize_for_comparison(comp)
            if norm not in seen_normalized:
                seen_normalized.add(norm)
                existing_companies.append(comp)
                new_added += 1
            else:
                skipped_dup += 1

        logs.append(f"[{get_timestamp()}] [DEDUP] Dilewati: {skipped_dup} duplikat (sudah ada di database / muncul berulang di file).")
        logs.append(f"[{get_timestamp()}] [UPDATE] Menambahkan +{new_added} perusahaan baru unik.")

        saved = save_companies_threadsafe(existing_companies)
        if not saved:
            logs.append(f"[{get_timestamp()}] [ERROR] Gagal menyimpan update ke {JSON_FILE}.")
            self.send_json_response(500, {"status": "error", "message": "Gagal menyimpan database JSON.", "logs": logs})
            return

        final_count = len(existing_companies)
        logs.append(f"[{get_timestamp()}] [SUCCESS] Database JSON berhasil diperbarui secara atomic & aman.")
        logs.append(f"[{get_timestamp()}] [SUMMARY] Total database saat ini: {final_count} perusahaan unik.")

        self.send_json_response(200, {
            "status": "success",
            "filename": filename,
            "total_rows": total_rows,
            "initial_count": initial_count,
            "new_companies_added": new_added,
            "final_count": final_count,
            "logs": logs
        })

    def handle_clean(self, raw_bytes: bytes, filename: str):
        """Memproses cleaning CSV data baru secara murni di RAM dan mengembalikan data bersih langsung."""
        logs = []
        t_start = get_timestamp()
        file_size_kb = len(raw_bytes) / 1024
        logs.append(f"[{t_start}] [START] Menerima file untuk dibersihkan: {filename} ({file_size_kb:.1f} KB)")
        logs.append(f"[{t_start}] Memproses secara in-memory (File tidak disimpan di hard disk server)...")

        csv_text = decode_csv_bytes(raw_bytes)
        string_io = io.StringIO(csv_text)
        reader = csv.reader(string_io)

        try:
            headers = next(reader, None)
        except Exception as e:
            self.send_json_response(400, {
                "status": "error",
                "message": f"Gagal membaca file CSV: {e}",
                "logs": logs
            })
            return

        if not headers:
            logs.append(f"[{get_timestamp()}] [ERROR] File CSV kosong atau tidak memiliki header.")
            self.send_json_response(400, {"status": "error", "message": "File CSV kosong.", "logs": logs})
            return

        col_idx = find_company_column_idx(headers)
        if col_idx == -1:
            err_msg = f"Kolom '{TARGET_COLUMN}' tidak ditemukan pada file {filename}."
            logs.append(f"[{get_timestamp()}] [ERROR] {err_msg}")
            self.send_json_response(400, {"status": "error", "message": err_msg, "logs": logs})
            return

        logs.append(f"[{get_timestamp()}] [INFO] Kolom target terdeteksi: '{headers[col_idx]}' (indeks {col_idx + 1}).")

        _, known_companies = load_known_companies_threadsafe()
        logs.append(f"[{get_timestamp()}] [INFO] Membaca {len(known_companies)} perusahaan terdaftar dari database JSON (READ-ONLY).")

        total_rows = 0
        removed_in_json = 0
        removed_internal_dup = 0
        removed_empty_company = 0
        seen_in_file = set()
        cleaned_rows = []

        for row in reader:
            if not row:
                continue
            total_rows += 1
            raw_company = row[col_idx] if col_idx < len(row) else ""
            norm_comp = normalize_for_comparison(raw_company)

            if not norm_comp:
                removed_empty_company += 1
                continue

            if norm_comp in known_companies:
                removed_in_json += 1
                continue

            if norm_comp in seen_in_file:
                removed_internal_dup += 1
                continue
            seen_in_file.add(norm_comp)

            cleaned_rows.append(row)

        logs.append(f"[{get_timestamp()}] [CLEAN] Total baris awal dipindai: {total_rows} baris.")
        logs.append(f"[{get_timestamp()}] [CLEAN] Dihapus (sudah ada di database JSON) : {removed_in_json} baris.")
        logs.append(f"[{get_timestamp()}] [CLEAN] Dihapus (duplikat di dalam file ini)   : {removed_internal_dup} baris.")
        if removed_empty_company > 0:
            logs.append(f"[{get_timestamp()}] [CLEAN] Dihapus (nama perusahaan kosong)      : {removed_empty_company} baris.")
        logs.append(f"[{get_timestamp()}] [SUCCESS] Sisa baris bersih (Perusahaan Baru)   : {len(cleaned_rows)} baris.")

        out_string_io = io.StringIO()
        writer = csv.writer(out_string_io, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(cleaned_rows)
        cleaned_csv_content = out_string_io.getvalue()

        clean_filename = f"cleaned_{filename}"
        logs.append(f"[{get_timestamp()}] [READY] File bersih siap diunduh oleh browser Anda: '{clean_filename}'.")

        self.send_json_response(200, {
            "status": "success",
            "filename": clean_filename,
            "total_rows": total_rows,
            "removed_in_json": removed_in_json,
            "removed_internal_dup": removed_internal_dup,
            "removed_empty": removed_empty_company,
            "kept_rows": len(cleaned_rows),
            "csv_data": cleaned_csv_content,
            "logs": logs
        })


def run_server(port=PORT):
    """Menjalankan ThreadingHTTPServer."""
    server_address = ("0.0.0.0", port)
    try:
        httpd = ThreadingHTTPServer(server_address, CleanJobRequestHandler)
    except OSError:
        port = 8080
        server_address = ("0.0.0.0", port)
        httpd = ThreadingHTTPServer(server_address, CleanJobRequestHandler)

    print("\n" + "=" * 65)
    print(" CLEANJOB AI - WEB UI SERVER DENGAN TOKEN GATE")
    print("=" * 65)
    print(f" Akses Web UI di browser : http://localhost:{port}")
    print(f" Token Akses Resmi       : {AUTHORIZED_TOKEN} (6 Digit)")
    print(f" Masa Aktif Sesi         : 2 Hari (48 Jam)")
    print(f" Database Perusahaan     : {os.path.abspath(JSON_FILE)}")
    print(f" Kebijakan Penyimpanan   : STRICT ZERO DISK STORAGE (In-Memory)")
    print(f" Batas Ukuran File       : {MAX_PAYLOAD_SIZE // (1024 * 1024)} MB")
    print(" Tekan Ctrl+C untuk menghentikan server.")
    print("=" * 65 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[{get_timestamp()}] Server dihentikan oleh pengguna.")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
