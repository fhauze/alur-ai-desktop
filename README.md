# ServiceIQ — AI-Powered Enterprise Service Intelligence Platform

Platform kecerdasan layanan berbasis AI untuk metrologi laboratorium.  
Agent AI dapat menjawab pertanyaan tentang status order, inspeksi, SLA, dan laboratorium berdasarkan data nyata dari database.

---

## Arsitektur Singkat

```
Pengguna
   │
   ▼
Langflow (http://localhost:7860)        ← antarmuka percakapan AI
   │  Agent: gemini-3.6-flash
   │  Tools: 7 ServiceIQ tools
   ▼
Backend API (http://localhost:8000)     ← autentikasi & otorisasi
   │  GET /api/ai/service-orders/{order_number}
   ▼
PostgreSQL — database siks_n_prd        ← data nyata
   │  VIEW: ai_service_order_summary
   └─ service_orders, users_customers, master_laboratory, ...
```

---

## Prasyarat

| Kebutuhan | Versi minimal | Cara cek |
|-----------|---------------|----------|
| Python | 3.11+ | `python3 --version` |
| PostgreSQL | 14+ | `psql --version` |
| `uv` (package manager) | terbaru | `uv --version` |
| Langflow | 1.12+ | sudah berjalan di `localhost:7860` |
| Google API Key | — | [ai.google.dev](https://ai.google.dev/) |

---

## Langkah Persiapan

### 1. Clone / masuk ke direktori project

```bash
cd /Users/fauzgabriel/development/alur-ai-desktop
```

---

### 2. Buat virtual environment & install dependensi

#### A. Root `.venv` (digunakan saat menjalankan backend langsung)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install starlette asyncpg uvicorn
```

#### B. Backend `.venv` (digunakan untuk tests)

```bash
cd backend
uv sync
cd ..
```

---

### 3. Konfigurasi environment database

Buat file `.env` di root project:

```bash
cp .env.example .env
```

Isi `.env` sesuai konfigurasi PostgreSQL lokal:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=siks_n_prd
DB_USER=fauzgabriel
DB_PASSWORD=
```

> **Catatan:** `DB_PASSWORD` boleh kosong jika user PostgreSQL tidak memiliki password (konfigurasi lokal default).

---

### 4. Terapkan semantic view ke database

View ini adalah satu-satunya jalur baca data yang digunakan AI layer.

```bash
psql -h localhost -p 5432 -U fauzgabriel -d siks_n_prd \
  -f database/views/ai_service_order_summary.sql
```

Verifikasi view berhasil dibuat:

```bash
psql -h localhost -p 5432 -U fauzgabriel -d siks_n_prd \
  -c "SELECT order_number, order_status, customer_name FROM ai_service_order_summary LIMIT 3;"
```

---

### 5. Konfigurasi Langflow Global Variables

Buka Langflow UI → **Settings → Global Variables**, lalu tambahkan dua variabel berikut:

| Nama | Tipe | Nilai |
|------|------|-------|
| `GOOGLE_API_KEY` | Credential | API key Google Generative AI Anda |
| `SERVICEIQ_BEARER_TOKEN` | Credential | Token dari langkah di bawah |

**Generate `SERVICEIQ_BEARER_TOKEN`:**

```bash
python3 -c "
import base64, json
d = {'user_id': 1, 'role': 'manager', 'lab_scope': list(range(1, 25))}
print(base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode())
"
```

Salin output tersebut sebagai nilai `SERVICEIQ_BEARER_TOKEN`.

> ⚠️ Token ini adalah **stub development** — tidak menggunakan kriptografi nyata.  
> Ganti dengan JWT yang sesungguhnya sebelum deploy ke production.

---

### 6. Pastikan flow ServiceIQ sudah ada di Langflow

Flow sudah terkonfigurasi dengan ID:

```
975f52f6-7883-4543-803c-45bfb9860e72
```

Jika flow belum ada atau perlu diperbarui, jalankan script patch:

```bash
# Ganti LLM dari Ollama ke Gemini dan fix tool endpoints
python3 langflow/patch_flow_gemini_v2.py

# Fix endpoint semua tool ke /api/ai/service-orders/{order_number}
python3 langflow/fix_tool_endpoints.py
```

---

## Menjalankan Backend

```bash
cd backend/api
DB_HOST=localhost DB_PORT=5432 DB_NAME=siks_n_prd DB_USER=fauzgabriel \
  ../../.venv/bin/uvicorn app:app --reload
```

Verifikasi berjalan:

```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok"}
```

Backend berjalan di: **http://127.0.0.1:8000**

---

## Menjalankan Tes

```bash
cd backend
DB_HOST=localhost DB_PORT=5432 DB_NAME=siks_n_prd DB_USER=fauzgabriel \
  uv run pytest tests/ -q
# → 35 passed
```

---

## Uji Backend Secara Langsung

Generate token manager terlebih dahulu:

```bash
TOKEN=$(python3 -c "
import base64, json
d = {'user_id': 1, 'role': 'manager', 'lab_scope': list(range(1, 25))}
print(base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode())
")
```

Uji endpoint:

```bash
# Order yang ada → 200
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/ai/service-orders/V-6747-09-000

# Order tidak ada → 404
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/ai/service-orders/ORD-TIDAK-ADA

# Tanpa token → 401
curl http://127.0.0.1:8000/api/ai/service-orders/V-6747-09-000
```

Contoh respons sukses:

```json
{
  "order_number": "V-6747-09-000",
  "customer": { "id": 61, "name": "Reza Hendrawan" },
  "service_type": "Verifikasi",
  "laboratory": { "id": 2, "name": "VOLUME" },
  "order_status": "new",
  "inspection_status": "no_inspection",
  "sla_status": "overdue"
}
```

---

## Uji End-to-End via Langflow API

Pastikan **backend sudah berjalan** di port 8000, kemudian:

```bash
curl -s -X POST \
  "http://127.0.0.1:7860/api/v1/run/975f52f6-7883-4543-803c-45bfb9860e72" \
  -H "x-api-key: sk-ryhzLF-hhKDu23hrKwa_hZ0T0UtjlRdu7m6yUrfXEaM" \
  -H "Content-Type: application/json" \
  -d '{
    "input_value": "Bagaimana status order V-6747-09-000?",
    "output_type": "chat",
    "input_type": "chat",
    "tweaks": {}
  }'
```

Atau melalui Langflow Playground:

1. Buka **http://localhost:7860**
2. Pilih flow **"ServiceIQ Customer Agent"**
3. Klik **Playground**
4. Ketik pertanyaan, contoh:

```
Bagaimana status order V-6747-09-000?
```

Jawaban yang dihasilkan agent berdasarkan data nyata:

```
Berikut adalah rincian status untuk order V-6747-09-000:

• Nomor Order    : V-6747-09-000
• Nama Pelanggan : Reza Hendrawan
• Jenis Layanan  : Verifikasi
• Laboratorium   : VOLUME
• Status Order   : Baru (New)
• Status Inspeksi: Belum Ada Inspeksi (No Inspection)
• Status SLA     : Melewati Batas Waktu (Overdue)
```

---

## Contoh Nomor Order di Database

| Nomor Order | Status | Pelanggan | Laboratorium | SLA |
|-------------|--------|-----------|--------------|-----|
| `V-6747-09-000` | new | Reza Hendrawan | VOLUME | overdue |
| `V-6739-09-000` | new | PT. Inscal Service Indonesia | SUHU | overdue |
| `V-6745-09-000` | new | Aldila Fadjar Ramadhan | VOLUME (MASTER METER) | overdue |
| `V-6737-09-000` | new | PT. Inscal Service Indonesia | GAYA DAN TEKANAN | overdue |
| `V-22-0051-000` | certified | UPTD Metrologi Kota Tangerang Selatan | MASSA (AT) | overdue |

> Format nomor order: `V-XXXX-XX-XXX` (UUT) atau `DL-25-XXX` (UTTP).  
> Prefix `ORD-` **tidak ada** di database ini.

---

## Ringkasan Perintah Restart

```bash
# 1. Backend
cd /Users/fauzgabriel/development/alur-ai-desktop/backend/api
DB_HOST=localhost DB_PORT=5432 DB_NAME=siks_n_prd DB_USER=fauzgabriel \
  ../../.venv/bin/uvicorn app:app --reload

# 2. Langflow (jika belum berjalan)
cd /Users/fauzgabriel/langflow
.venv/bin/python -m langflow run

# 3. Verifikasi
curl http://127.0.0.1:8000/health
# → {"status":"ok"}
```

---

## Struktur Direktori Penting

```
alur-ai-desktop/
├── .env.example                          # template environment variables
├── .venv/                                # root virtual environment
│
├── backend/
│   ├── api/
│   │   ├── app.py                        # entry point: uvicorn app:app
│   │   └── service_orders.py             # GET /api/ai/service-orders/{order_number}
│   ├── auth/
│   │   ├── principal.py                  # Principal + Role
│   │   └── authorization.py             # IDOR-safe access guard
│   ├── db/connection.py                  # asyncpg pool (env vars only)
│   ├── domain/AIServiceOrder.py          # typed domain model
│   ├── repositories/AIServiceOrderRepository.py  # query layer
│   ├── tests/                            # 35 unit tests
│   └── pyproject.toml                    # dependencies
│
├── database/
│   └── views/ai_service_order_summary.sql  # semantic AI view (apply once)
│
├── langflow/
│   ├── flow_id.txt                       # 975f52f6-7883-4543-803c-45bfb9860e72
│   ├── patch_flow_gemini_v2.py           # setup/fix script: switch LLM ke Gemini
│   └── fix_tool_endpoints.py             # setup/fix script: fix tool URL endpoints
│
└── docs/
    ├── database/service-order-domain-analysis.md
    ├── database/service-order-erd.md
    └── debug/end-to-end-analysis.md      # dokumentasi teknis lengkap
```

---

## Catatan Keamanan

| # | Catatan |
|---|---------|
| ⚠️ | `_decode_token()` di `backend/api/app.py` adalah **stub** — ganti dengan JWT verification nyata sebelum production |
| ⚠️ | `SERVICEIQ_BEARER_TOKEN` adalah token development — tidak kriptografis |
| ✅ | Bearer token **tidak pernah** menjadi argumen LLM — disimpan sebagai Credential di Langflow |
| ✅ | Semua query menggunakan parameterised SQL — tidak ada SQL injection |
| ✅ | Field sensitif (`password`, `token`, `ktp`, dll.) tidak pernah dikembalikan API |
| ✅ | IDOR dicegah: otorisasi berdasarkan data record, bukan URL parameter |
