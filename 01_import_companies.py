"""
Script 1: Import Company Name dari CSV ke JSON
==============================================
Tujuan:
- Membaca file CSV hasil scraping sebelumnya.
- Mengambil HANYA kolom `employer_company_name`.
- Membersihkan duplikasi (deduplikasi) dan whitespace.
- Menyimpan daftar company unik ke dalam file JSON (default: companies.json).
- Jika file JSON sudah ada, data baru akan digabungkan (incremental merge) tanpa duplikasi.
"""

import os
import sys
import csv
import json
import glob
import argparse
from typing import List, Set, Tuple

# Tingkatkan limit ukuran field CSV agar tidak error pada deskripsi job yang panjang
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2147483647)

DEFAULT_JSON_PATH = "companies.json"
TARGET_COLUMN = "employer_company_name"


def normalize_for_comparison(name: str) -> str:
    """Normalisasi nama perusahaan untuk perbandingan unik (case-insensitive & spasi seragam)."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def clean_company_name(name: str) -> str:
    """Membersihkan whitespace ekstra pada nama perusahaan untuk disimpan."""
    if not name:
        return ""
    return " ".join(name.strip().split())


def find_company_column(headers: List[str]) -> str:
    """Mencari nama kolom employer_company_name (toleran huruf besar/kecil & spasi)."""
    # 1. Cek kecocokan persis
    if TARGET_COLUMN in headers:
        return TARGET_COLUMN
    
    # 2. Cek case-insensitive
    target_lower = TARGET_COLUMN.lower()
    for col in headers:
        if col and col.strip().lower() == target_lower:
            return col
            
    # 3. Cek variasi kata kunci
    for col in headers:
        if not col:
            continue
        cleaned = col.strip().lower().replace(" ", "_")
        if "employer_company" in cleaned or ("company" in cleaned and "name" in cleaned):
            return col

    return ""


def read_companies_from_csv(file_path: str) -> Tuple[List[str], int]:
    """
    Membaca CSV dan mengambil semua employer_company_name yang valid.
    Mengembalikan (list_company_terformat, total_baris_data).
    """
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_err = None

    for enc in encodings:
        try:
            with open(file_path, mode="r", encoding=enc, errors="replace") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
                if not headers:
                    return [], 0
                
                col_name = find_company_column(headers)
                if not col_name:
                    print(f"  [PERINGATAN] Kolom '{TARGET_COLUMN}' tidak ditemukan di {os.path.basename(file_path)}.")
                    print(f"               Kolom yang tersedia: {headers[:5]}...")
                    return [], 0

                # Cari index kolom
                col_idx = headers.index(col_name)

                companies = []
                total_rows = 0
                for row in reader:
                    if not row:
                        continue
                    total_rows += 1
                    if col_idx < len(row):
                        raw_val = row[col_idx]
                        cleaned_val = clean_company_name(raw_val)
                        if cleaned_val:
                            companies.append(cleaned_val)
                
                return companies, total_rows

        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:
            print(f"  [ERROR] Gagal membaca file {file_path}: {e}")
            return [], 0

    if last_err:
        print(f"  [ERROR] Gagal membuka file dengan berbagai encoding: {last_err}")
    return [], 0


def load_existing_json(json_path: str) -> Tuple[List[str], Set[str]]:
    """
    Memuat data company yang sudah ada di file JSON.
    Mengembalikan: (list_company_asli, set_normalized_untuk_lookup)
    """
    if not os.path.exists(json_path):
        return [], set()

    try:
        with open(json_path, mode="r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                existing_list = []
                seen_normalized = set()
                for item in data:
                    if isinstance(item, str):
                        c = clean_company_name(item)
                        if c:
                            norm = normalize_for_comparison(c)
                            if norm not in seen_normalized:
                                seen_normalized.add(norm)
                                existing_list.append(c)
                return existing_list, seen_normalized
            else:
                print(f"  [PERINGATAN] Format {json_path} bukan list. File akan diabaikan.")
                return [], set()
    except Exception as e:
        print(f"  [PERINGATAN] Gagal membaca file JSON lama ({json_path}): {e}")
        return [], set()


def save_companies_to_json(json_path: str, companies: List[str]):
    """Menyimpan list company unik ke JSON dengan format rapi dan terurut."""
    # Urutkan secara alfabetis (case-insensitive)
    sorted_companies = sorted(companies, key=lambda x: x.lower())
    
    # Buat direktori jika belum ada
    out_dir = os.path.dirname(json_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(json_path, mode="w", encoding="utf-8") as f:
        json.dump(sorted_companies, f, indent=2, ensure_ascii=False)


def get_files_interactively() -> List[str]:
    """Menu interaktif jika script dijalankan tanpa argumen."""
    print("=" * 60)
    print(" 01_IMPORT_COMPANIES - PILIH FILE INPUT")
    print("=" * 60)
    
    # Cari file CSV yang ada di example_file maupun di folder kerja
    found_files = []
    if os.path.exists("example_file"):
        found_files.extend(glob.glob("example_file/*.csv"))
    found_files.extend(glob.glob("*.csv"))
    
    # Hapus duplikat path
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
        print("  [A] Proses SEMUA file di atas")
        print("  [M] Masukkan path file secara manual")
        print("-" * 60)
        
        choice = input("Pilih nomor (1-{0} / A / M) [default A]: ".format(len(unique_found))).strip().upper()
        if not choice or choice == "A":
            return unique_found
        elif choice == "M":
            custom_path = input("Masukkan path file CSV (bisa pakai wildcard, contoh: data/*.csv): ").strip()
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
        custom_path = input("Masukkan path file CSV (contoh: example_file/1B NSW - Sheet1.csv): ").strip()
        if custom_path:
            matched = glob.glob(custom_path)
            return matched if matched else [custom_path]
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Script 1: Import kolom employer_company_name dari file CSV ke JSON."
    )
    parser.add_argument(
        "input_files",
        nargs="*",
        help="Satu atau lebih path file CSV (contoh: example_file/*.csv atau 'example_file/1B NSW - Sheet1.csv')."
    )
    parser.add_argument(
        "--json-file", "-j",
        default=DEFAULT_JSON_PATH,
        help=f"Path file JSON output (default: {DEFAULT_JSON_PATH})."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Timpa file JSON dari awal (tidak menggabungkan dengan company yang sudah ada sebelumnya)."
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
        # Jika dijalankan tanpa parameter, gunakan interactive helper
        target_files = get_files_interactively()

    if not target_files:
        print("[INFO] Tidak ada file yang dipilih untuk diproses.")
        sys.exit(0)

    json_file = args.json_file
    print("\n" + "=" * 60)
    print(" SCRIPT 1: IMPORT COMPANY NAME KE JSON")
    print("=" * 60)
    print(f"Target JSON : {os.path.abspath(json_file)}")
    print(f"Mode        : {'OVERWRITE (Reset baru)' if args.overwrite else 'MERGE (Tambahkan yang belum ada)'}")
    print(f"Total File  : {len(target_files)}")
    print("-" * 60)

    # Muat company yang sudah ada di JSON jika mode merge
    if args.overwrite:
        existing_companies = []
        seen_normalized = set()
    else:
        existing_companies, seen_normalized = load_existing_json(json_file)

    initial_count = len(existing_companies)
    if initial_count > 0:
        print(f"[INFO] Memuat {initial_count} company yang sudah ada di {os.path.basename(json_file)}.")

    new_companies_added = 0
    total_rows_scanned = 0

    for file_path in target_files:
        if not os.path.isfile(file_path):
            print(f"Lewati: '{file_path}' (bukan file)")
            continue

        filename = os.path.basename(file_path)
        companies, rows_count = read_companies_from_csv(file_path)
        total_rows_scanned += rows_count

        added_from_this_file = 0
        for comp in companies:
            norm = normalize_for_comparison(comp)
            if norm not in seen_normalized:
                seen_normalized.add(norm)
                existing_companies.append(comp)
                added_from_this_file += 1
                new_companies_added += 1

        print(f"[PROSES] {filename:<30} -> {rows_count:>4} baris | {len(companies):>4} company | +{added_from_this_file:>3} company baru unik")

    # Simpan kembali ke JSON
    save_companies_to_json(json_file, existing_companies)
    final_count = len(existing_companies)

    print("-" * 60)
    print("RINGKASAN HASIL IMPORT:")
    print(f"  - Total baris CSV diperiksa : {total_rows_scanned}")
    print(f"  - Company awal di JSON       : {initial_count}")
    print(f"  - Company baru ditambahkan   : {new_companies_added}")
    print(f"  - Total company unik di JSON : {final_count}")
    print(f"  - File tersimpan di          : {os.path.abspath(json_file)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
