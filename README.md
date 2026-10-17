# Panduan CleanJob AI — Scraper Cleaner & Web UI

CleanJob AI adalah solusi terpadu untuk pengolahan dan pembersihan data hasil scraper lowongan pekerjaan dari duplikasi perusahaan (*company duplicates*).

Aplikasi ini dirancang **ekstrem ringan (RAM < 25 MB)**, aman untuk multi-user bersamaan, menerapkan kebijakan **STRICT ZERO DISK STORAGE** (file CSV input dan output tidak disimpan ke hard disk server), serta **dilindungi gerbang token otorisasi resmi**.

---

## 🔐 Sistem Akses & Token Gate

Untuk menjaga keamanan, Web UI dilindungi oleh sistem token otorisasi:
* **Token Akses Resmi:** **`INT206`** (6 Karakter).
* **Masa Aktif Sesi (Expired):** **2 Hari (48 Jam / 172.800 detik)**.
* **Cara Kerja:**
  1. Saat pertama kali membuka web, pengguna akan disambut oleh layar **Token Gate**.
  2. Masukkan kode **`INT206`** lalu klik **"Buka Akses"**.
  3. Setelah terverifikasi, seluruh fitur (Import, Cleaning, dan Company DB) akan terbuka penuh dan sesi akan bertahan aktif selama **2 hari** di browser tersebut tanpa perlu mengetik ulang token.
  4. Pengguna juga dapat mengklik tombol **"Keluar"** di sudut kanan atas jika ingin mengunci kembali sesi lebih awal.
  5. Seluruh API server memvalidasi tanda tangan kriptografis (HMAC-SHA256). Pengguna tanpa token yang sah tidak dapat mengakses data maupun fitur server (HTTP 401 Unauthorized).

---

## 🌟 Cara Menjalankan Web UI

Cukup jalankan satu perintah:
```bash
python app.py
```

Buka browser Anda dan akses:
👉 **`http://localhost:8000`** *(atau `http://IP-SERVER:8000` jika diakses dari jaringan/komputer lain)*.

---

## 📱 Fitur Utama Web UI:

1. **Tab 1: 📥 Import to JSON (Page 1)**
   - Area **Drag & Drop** file CSV scraper riwayat lama.
   - Menekan tombol **"Mulai Import Company"**.
   - Menampilkan jendela **Live Terminal / CMD Log** secara real-time.
   - Memunculkan pop-up modal **"Import Selesai"** beserta statistik ringkasan.
   - File CSV yang diunggah **tidak disimpan di server** (in-memory processing).

2. **Tab 2: ✨ Cleaning Scraper (Page 2)**
   - Area **Drag & Drop** file scraper baru yang ingin dibersihkan.
   - Menekan tombol **"Clean Now"**.
   - Menampilkan **Live Terminal / CMD Log** proses pembersihan baris demi baris.
   - Setelah selesai, muncul ringkasan hasil dan **2 tombol tindakan**:
     - **"Download Clean File"**: Mengunduh file hasil cleaning langsung dari memori browser (`cleaned_<nama_file>.csv`).
     - **"Clean Another File"**: Me-reset halaman secara mulus untuk langsung memproses file baru berikutnya.
   - Bersifat **Strictly Read-Only** terhadap `companies.json` dan file tidak disimpan di hard disk server.

3. **Tab 3: 🏢 Database Company (Page 3)**
   - Menampilkan total jumlah perusahaan unik yang terdaftar di `companies.json`.
   - Kolom pencarian instan (**Live Search**) untuk memeriksa perusahaan dengan cepat.
   - Tampilan grid badge yang bersih dan rapi.

---

## 🛡️ Keamanan Multi-User & Proteksi Server

Aplikasi ini sudah dipersenjatai proteksi tingkat tinggi:
* **Token Gate & 2-Day Session:** Akses dibatasi hanya untuk pemegang token `INT206`.
* **Bisa Digunakan 2 Orang Bersamaan Tanpa Login/Akun Tambahan:**
  Setiap koneksi browser diproses di thread terpisah. File bersih diunduh via *Client-Side Blob Memory* sehingga data tidak akan pernah tertukar.
* **Thread-Safe & Atomic Write (`os.replace`):**
  Jika dua orang melakukan import di detik yang sama, antrean *Mutex Lock* memastikan data tidak akan tertimpa (*lost update*) dan file JSON tidak akan rusak.
* **Payload Limit (30 MB):**
  Mencegah server *crash* kehabisan RAM jika ada file terlalu besar.
* **Auto-Backup & Self-Healing:**
  Setiap import otomatis membuat cadangan `companies.json.bak` untuk pemulihan mandiri jika terjadi kegagalan listrik.

---

## 💻 Menjalankan via Terminal CLI (Opsional)

Jika Anda ingin menjalankan tanpa browser, script CLI tetap tersedia:

### Script 1: Import Company ke JSON
```bash
python 01_import_companies.py "example_file/1B NSW - Sheet1.csv"
```

### Script 2: Cleaning Data Baru (Fokus Cleaning, Read-Only)
```bash
python 02_clean_companies.py "example_file/24 NSW - Sheet1.csv"
```

---

## 📊 Hasil Uji Konsumsi RAM

| Komponen | Total Penggunaan RAM di OS | Keterangan |
| :--- | :---: | :--- |
| **Web UI Server (`app.py`)** | **~24 MB – 26 MB** | Termasuk verifikasi token & interpreter Python runtime |
| **Saat Digunakan 2 User Bersamaan** | **~28 MB – 33 MB** | Sangat aman untuk server dengan sisa RAM 365 MB |
| **Dependensi Eksternal** | **0 (Nol)** | 100% Pustaka Standar Python, tanpa perlu `pip install` |
