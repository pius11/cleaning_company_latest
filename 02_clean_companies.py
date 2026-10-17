"""
Script 2: Cleaning Data CSV dari Company yang Sudah Ada di JSON & Duplicate
==========================================================================
Tujuan:
- Membaca daftar company yang sudah pernah didapatkan dari file JSON (companies.json).
- Memfilter file CSV data scraper baru:
  1. Menghapus baris jika perusahaannya SUDAH ADA di dalam JSON.
  2. Menghapus baris DUPLIKAT perusahaan di dalam file CSV itu sendiri (opsional bisa diubah via flag).
  3. Menyisakan HANYA perusahaan baru yang belum pernah tercatat di JSON.
- Menyimpan hasil CSV yang sudah bersih ke folder `output_clean/`.
- PENTING: Script ini HANYA membaca JSON (READ-ONLY) dan TIDAK AKAN menginput / mengubah file JSON sama sekali.
"""

import os
import sys
import csv
import json
import glob
import argparse
from typing import List, Set, Tuple, Optional

# Tingkatkan limit ukuran field CSV agar tidak error pada deskripsi job yang panjang
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2147483647)

DEFAULT_JSON_PATH = "companies.json"
DEFAULT_OUTPUT_DIR = "output_clean"
TARGET_COLUMN = "employer_company_name"


def normalize_for_comparison(name: str) -> str:
    """Normalisasi nama perusahaan untuk perbandingan unik (case-insensitive & spasi seragam)."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def find_company_column_idx(headers: List[str]) -> int:
    """Mencari indeks kolom employer_company_name (toleran huruf besar/kecil & spasi)."""
    # 1. Cek kecocokan persis
    if TARGET_COLUMN in headers:
        return headers.index(TARGET_COLUMN)
    
    # 2. Cek case-insensitive
    target_lower = TARGET_COLUMN.lower()
    for idx, col in enumerate(headers):
        if col and col.strip().lower() == target_lower:
            return idx
            
    # 3. Cek variasi kata kunci
    for idx, col in enumerate(headers):
        if not col:
            continue
        cleaned = col.strip().lower().replace(" ", "_")
        if "employer_company" in cleaned or ("company" in cleaned and "name" in cleaned):
            return idx

    return -1


def load_known_companies(json_path: str) -> Set[str]:
    """
    Memuat daftar nama company dari file JSON ke dalam set ter-normalisasi (READ ONLY).
    Tidak ada proses penulisan ke file JSON di script ini.
    """
    if not os.path.exists(json_path):
        print(f"[ERROR] File JSON tidak ditemukan: {os.path.abspath(json_path)}")
        print("        Silakan jalankan '01_import_companies.py' terlebih dahulu untuk membuat daftar company.")
        sys.exit(1)

    try:
        with open(json_path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                print(f"[ERROR] Format isi {json_path} harus berupa list nama company.")
                sys.exit(1)
            
            known_set = set()
            for item in data:
                if isinstance(item, str):
                    norm = normalize_for_comparison(item)
                    if norm:
                        known_set.add(norm)
            return known_set
    except Exception as e:
        print(f"[ERROR] Gagal membaca {json_path}: {e}")
        sys.exit(1)


def clean_single_csv(
    input_file: str,
    output_dir: str,
    known_companies: Set[str],
    dedup_within_file: bool = True,
    drop_empty_company: bool = True
) -> dict:
    """
    Membersihkan 1 file CSV berdasarkan known_companies dari JSON.
    Mengembalikan dictionary statistik hasil cleaning.
    """
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    
    headers = None
    rows = []
    used_encoding = "utf-8-sig"

    for enc in encodings:
        try:
            with open(input_file, mode="r", encoding=enc, errors="replace") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                if headers is None:
                    return {"status": "empty_file", "filename": os.path.basename(input_file)}
                rows = list(reader)
                used_encoding = enc
                break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return {"status": "error", "error": str(e), "filename": os.path.basename(input_file)}

    if headers is None:
        return {"status": "read_failed", "filename": os.path.basename(input_file)}

    col_idx = find_company_column_idx(headers)
    if col_idx == -1:
        return {
            "status": "column_not_found",
            "filename": os.path.basename(input_file),
            "headers": headers[:5]
        }

    total_rows = len(rows)
    removed_in_json = 0
    removed_internal_dup = 0
    removed_empty_company = 0
    
    seen_in_this_file = set()
    cleaned_rows = []

    for row in rows:
        if not row:
            continue

        raw_company = row[col_idx] if col_idx < len(row) else ""
        norm_company = normalize_for_comparison(raw_company)

        # Cek jika kolom company kosong
        if not norm_company:
            if drop_empty_company:
                removed_empty_company += 1
                continue
            else:
                # Tetap simpan jika tidak ingin drop empty
                cleaned_rows.append(row)
                continue

        # Cek 1: Apakah company sudah pernah ada di JSON?
        if norm_company in known_companies:
            removed_in_json += 1
            continue

        # Cek 2: Apakah company ini duplikat di dalam file CSV ini sendiri?
        if dedup_within_file:
            if norm_company in seen_in_this_file:
                removed_internal_dup += 1
                continue
            seen_in_this_file.add(norm_company)

        # Jika lolos semua filter, simpan baris
        cleaned_rows.append(row)

    # Simpan hasil cleaning ke output_dir
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.basename(input_file)
    output_filename = f"cleaned_{base_name}"
    output_path = os.path.join(output_dir, output_filename)

    with open(output_path, mode="w", encoding="utf-8", newline="") as out_f:
        writer = csv.writer(out_f, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(cleaned_rows)

    return {
        "status": "success",
        "filename": base_name,
        "output_path": output_path,
        "total_rows": total_rows,
        "removed_in_json": removed_in_json,
        "removed_internal_dup": removed_internal_dup,
        "removed_empty_company": removed_empty_company,
        "kept_rows": len(cleaned_rows)
    }


def get_files_interactively() -> List[str]:
    """Menu interaktif jika script dijalankan tanpa argumen."""
    print("=" * 60)
    print(" 02_CLEAN_COMPANIES - PILIH FILE YANG INGIN DICLEANING")
    print("=" * 60)
    
    # Cari file CSV
    found_files = []
    if os.path.exists("example_file"):
        found_files.extend(glob.glob("example_file/*.csv"))
    found_files.extend(glob.glob("*.csv"))
    
    unique_found = []
    seen = set()
    for f in found_files:
        norm = os.path.normpath(f)
        if norm not in seen:
            seen.add(norm)
            unique_found.append(f)
            
    if unique_found:
        print("Ditemukan file CSV:")
        for idx, f in enumerate(unique_found, 1):
            print(f"  [{idx}] {f}")
        print("  [A] Bersihkan SEMUA file di atas")
        print("  [M] Masukkan path file secara manual")
        print("-" * 60)
        
        choice = input("Pilih nomor (1-{0} / A / M) [default 1]: ".format(len(unique_found))).strip().upper()
        if not choice or choice == "1":
            return [unique_found[0]]
        elif choice == "A":
            return unique_found
        elif choice == "M":
            custom_path = input("Masukkan path file CSV (contoh: example_file/24 NSW - Sheet1.csv): ").strip()
            if custom_path:
                matched = glob.glob(custom_path)
                return matched if matched else [custom_path]
            return []
        else:
            try:
                selected_idx = int(choice) - 1
                if 0 <= selected_idx < len(unique_found):
                    return [unique_found[selected_idx]]
                else:
                    print("Pilihan tidak valid.")
                    return []
            except ValueError:
                print("Input tidak valid.")
                return []
    else:
        custom_path = input("Masukkan path file CSV yang ingin dibersihkan: ").strip()
        if custom_path:
            matched = glob.glob(custom_path)
            return matched if matched else [custom_path]
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Script 2: Membersihkan CSV data baru dari company yang sudah ada di JSON & company duplicate."
    )
    parser.add_argument(
        "input_files",
        nargs="*",
        help="Satu atau lebih file CSV baru untuk dicleaning (contoh: 'example_file/24 NSW - Sheet1.csv')."
    )
    parser.add_argument(
        "--json-file", "-j",
        default=DEFAULT_JSON_PATH,
        help=f"Path ke file JSON referensi company lama (default: {DEFAULT_JSON_PATH})."
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder tujuan hasil cleaning (default: {DEFAULT_OUTPUT_DIR})."
    )
    parser.add_argument(
        "--keep-internal-duplicates",
        action="store_true",
        help="Jangan hapus duplikat company di dalam file itu sendiri (tetap simpan semua job posting dari company baru yang sama)."
    )
    parser.add_argument(
        "--keep-empty-company",
        action="store_true",
        help="Jangan hapus baris yang kolom employer_company_name-nya kosong."
    )

    args = parser.parse_args()

    # Tentukan input files
    target_files = []
    if args.input_files:
        for pattern in args.input_files:
            matched = glob.glob(pattern)
            if matched:
                target_files.extend(matched)
            elif os.path.exists(pattern):
                target_files.append(pattern)
            else:
                print(f"[PERINGATAN] File/pola tidak ditemukan: {pattern}")
    else:
        target_files = get_files_interactively()

    if not target_files:
        print("[INFO] Tidak ada file yang dipilih untuk dibersihkan.")
        sys.exit(0)

    # Muat company dari JSON (Strictly Read-Only)
    known_companies = load_known_companies(args.json_file)

    print("\n" + "=" * 60)
    print(" SCRIPT 2: CLEANING DATA SCRAPER BARU")
    print("=" * 60)
    print(f"Referensi JSON     : {os.path.abspath(args.json_file)}")
    print(f"Total Company JSON : {len(known_companies)} company terdaftar (READ-ONLY)")
    print(f"Folder Output      : {os.path.abspath(args.output_dir)}")
    print(f"Deduplikasi File   : {'TIDAK (keep all)' if args.keep_internal_duplicates else 'YA (1 baris per company)'}")
    print(f"Total File Input   : {len(target_files)}")
    print("-" * 60)

    dedup_file = not args.keep_internal_duplicates
    drop_empty = not args.keep_empty_company

    total_scanned_all = 0
    total_kept_all = 0
    total_in_json_all = 0
    total_internal_dup_all = 0

    for file_path in target_files:
        if not os.path.isfile(file_path):
            print(f"Lewati: '{file_path}' (bukan file)")
            continue

        result = clean_single_csv(
            input_file=file_path,
            output_dir=args.output_dir,
            known_companies=known_companies,
            dedup_within_file=dedup_file,
            drop_empty_company=drop_empty
        )

        status = result.get("status")
        fname = result.get("filename")

        if status == "success":
            total_scanned_all += result["total_rows"]
            total_kept_all += result["kept_rows"]
            total_in_json_all += result["removed_in_json"]
            total_internal_dup_all += result["removed_internal_dup"]

            print(f"\n[HASIL CLEANING] {fname}")
            print(f"  * Total Baris Awal               : {result['total_rows']:>4}")
            print(f"  - Dihapus (Sudah ada di JSON)    : {result['removed_in_json']:>4}")
            if dedup_file:
                print(f"  - Dihapus (Duplikat dlm file)    : {result['removed_internal_dup']:>4}")
            if result['removed_empty_company'] > 0:
                print(f"  - Dihapus (Company kosong)       : {result['removed_empty_company']:>4}")
            print(f"  = Sisa Baris Bersih (Fresh Data) : {result['kept_rows']:>4}")
            print(f"  -> File Tersimpan di             : {result['output_path']}")

        elif status == "column_not_found":
            print(f"\n[GAGAL] {fname}: Kolom '{TARGET_COLUMN}' tidak ditemukan.")
        else:
            print(f"\n[GAGAL] {fname}: {result.get('error', 'Format tidak sesuai / file kosong')}")

    print("\n" + "=" * 60)
    print("RINGKASAN AKHIR KESELURUHAN:")
    print(f"  - Total baris awal diproses        : {total_scanned_all}")
    print(f"  - Total dibuang (Sudah ada di JSON): {total_in_json_all}")
    if dedup_file:
        print(f"  - Total dibuang (Duplikat internal): {total_internal_dup_all}")
    print(f"  - TOTAL BARIS BERSIH TERSISA       : {total_kept_all}")
    print(f"  - Catatan: File JSON ({os.path.basename(args.json_file)}) TIDAK mengalami perubahan.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
