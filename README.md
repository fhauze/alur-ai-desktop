# AI Customer Service Agent

AI Customer Service Agent adalah solusi **AI Agent berbasis Langflow** yang membantu menjawab pertanyaan customer menggunakan data aktual dari database aplikasi. Model AI menggunakan **Gemini Flash**, sedangkan Langflow berperan sebagai orkestrator antara customer, model AI, dan database perusahaan.

## 1. Arsitektur

```text
Customer
   │
   ▼
Aplikasi / Chat UI
   │
   ▼
Langflow
   │
   ├── Gemini Flash
   │
   └── Database Tool
          │
          ▼
    Application Database
```

**Prinsip utama:** database aplikasi menjadi sumber informasi utama. AI tidak mengarang harga, stok, pesanan, atau informasi perusahaan yang tidak tersedia di database.

---

## 2. Teknologi

* **Langflow** — AI Agent & workflow orchestration
* **Gemini Flash** — LLM/reasoning engine
* **PostgreSQL/MySQL** — database aplikasi
* **REST API** — integrasi aplikasi dengan Langflow
* **RAG/Vector Database** — opsional untuk FAQ dan dokumen perusahaan

---

## 3. Prasyarat

Pastikan sudah tersedia:

```text
Docker
Database aplikasi
Gemini API Key
Langflow
```

Jika menggunakan Docker, jalankan Langflow:

```bash
docker run -p 7860:7860 langflowai/langflow:latest
```

Kemudian buka:

```text
http://localhost:7860
```

---

## 4. Siapkan Database

Buat user database khusus untuk AI dengan hak akses **read-only**.

Contoh PostgreSQL:

```sql
CREATE USER ai_readonly WITH PASSWORD 'PASSWORD_KUAT';

GRANT CONNECT ON DATABASE nama_database TO ai_readonly;
GRANT USAGE ON SCHEMA public TO ai_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ai_readonly;
```

Disarankan membuat database view khusus AI:

```sql
CREATE VIEW ai_products AS
SELECT
    id,
    name,
    description,
    price,
    stock,
    status
FROM products
WHERE status = 'active';
```

Dengan demikian AI hanya membaca data yang memang diperbolehkan.

---

## 5. Hubungkan Database ke Langflow

Buat Flow baru di Langflow.

Tambahkan:

```text
Chat Input
    │
    ▼
Agent
    │
    ▼
Chat Output
```

Kemudian tambahkan **SQL Database** sebagai Tool.

Contoh PostgreSQL:

```text
postgresql://ai_readonly:PASSWORD@localhost:5432/nama_database
```

Jika Langflow berjalan di Docker sedangkan database berada di host:

```text
postgresql://ai_readonly:PASSWORD@host.docker.internal:5432/nama_database
```

Aktifkan **Tool Mode** pada SQL Database dan hubungkan ke Agent.

---

## 6. Hubungkan Gemini Flash

Pada Agent pilih model Gemini dan masukkan Gemini API Key.

Struktur:

```text
Gemini Flash
     │
     ▼
   Agent
     │
     │ Tools
     ▼
SQL Database
```

Gemini berfungsi sebagai otak/reasoning. Gemini tidak diberikan akses langsung ke database. Agent menggunakan SQL Database Tool untuk mengambil data.

---

## 7. System Prompt

Gunakan aturan dasar berikut pada Agent:

```text
Anda adalah AI Customer Service perusahaan.

Tugas Anda adalah membantu customer menjawab pertanyaan
mengenai produk, harga, stok, pesanan, promosi, dan informasi
perusahaan.

ATURAN:
1. Gunakan database sebagai sumber utama untuk data perusahaan.
2. Jangan mengarang harga, stok, produk, atau status pesanan.
3. Gunakan database tool jika pertanyaan membutuhkan data aktual.
4. Jika data tidak ditemukan, katakan bahwa data tidak tersedia.
5. Jangan menampilkan SQL kepada customer.
6. Jangan melakukan INSERT, UPDATE, DELETE, atau DROP.
7. Hanya gunakan operasi READ/SELECT.
8. Jangan memberikan data customer lain.
9. Jawab menggunakan Bahasa Indonesia yang ramah dan profesional.
10. Gunakan knowledge base perusahaan jika tersedia.
```

---

## 8. Pengujian

Jalankan Flow dan coba pertanyaan:

```text
Apa saja produk yang tersedia?
```

```text
Berapa harga Kopi Arabika 250g?
```

```text
Apakah produk X masih tersedia?
```

```text
Bagaimana status pesanan saya?
```

Agent seharusnya:

```text
Customer
   ↓
Gemini
   ↓
Memahami pertanyaan
   ↓
Memanggil SQL Tool
   ↓
Database
   ↓
Data aktual
   ↓
Gemini
   ↓
Jawaban customer
```

---

## 9. Integrasi dengan Aplikasi

Untuk production, jangan expose Langflow langsung ke customer.

Gunakan backend aplikasi sebagai gateway:

```text
Customer
   │
   ▼
Frontend / Mobile
   │
   ▼
Backend API
   │
   ▼
Langflow API
   │
   ▼
AI Agent
   │
   ├── Gemini Flash
   └── Database Tool
```

Contoh request:

```http
POST /api/ai/chat
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "message": "Apakah Kopi Arabika 250g masih tersedia?"
}
```

Backend kemudian meneruskan request ke Flow Langflow.

---

## 10. Customer Context

Untuk pertanyaan mengenai pesanan, customer harus diidentifikasi melalui authentication aplikasi.

```text
JWT
 │
 ▼
Backend
 │
 └── customer_id
        │
        ▼
     Langflow
        │
        ▼
 Database
```

Jangan meminta customer mengirim `customer_id` secara bebas.

Contoh query:

```sql
SELECT *
FROM ai_orders
WHERE customer_id = :customer_id;
```

Dengan demikian customer hanya dapat memperoleh data miliknya.

---

## 11. Knowledge Base (Opsional)

Untuk informasi yang tidak perlu diambil secara real-time, gunakan RAG.

Contoh:

```text
FAQ
Company Profile
Kebijakan Retur
Kebijakan Pengiriman
Panduan Produk
       │
       ▼
Vector Database
       │
       ▼
Langflow Agent
```

Sedangkan:

```text
Harga
Stok
Pesanan
Transaksi
Promosi aktif
```

tetap mengambil data langsung dari database aplikasi.

---

## 12. Production Checklist

Sebelum digunakan secara luas:

* [ ] Database menggunakan user `read-only`
* [ ] Data sensitif tidak tersedia untuk Agent
* [ ] Database view khusus AI sudah dibuat
* [ ] Gemini API Key disimpan sebagai secret/environment variable
* [ ] Langflow tidak diekspos langsung ke publik
* [ ] Backend melakukan authentication customer
* [ ] Customer hanya dapat mengakses datanya sendiri
* [ ] Query database dibatasi
* [ ] Logging dan monitoring tersedia
* [ ] Human handoff tersedia untuk kasus kompleks

---

## 13. Hasil Akhir

Dengan implementasi ini, sistem dapat:

```text
Customer
   │
   │ "Berapa harga produk X?"
   ▼
AI Customer Service
   │
   ▼
Gemini Flash
   │
   ▼
Langflow Tool
   │
   ▼
Application Database
   │
   ▼
Harga aktual
   │
   ▼
AI Customer Service
   │
   ▼
"Produk X tersedia dengan harga Rp85.000."
```

Solusi dapat dikembangkan lebih lanjut untuk **multi-user, multi-channel, RAG, rekomendasi produk, pengecekan pesanan, human handoff, CRM/ERP integration, dan multi-tenant enterprise deployment**.
