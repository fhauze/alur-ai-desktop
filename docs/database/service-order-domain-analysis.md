# Service Order Domain Analysis

> **Project:** ServiceIQ — AI-Powered Enterprise Service Intelligence Platform
> **Source:** `dump-siks_n_prd-202610031054.sql` (PostgreSQL 17.8, db: `siks_n_prd`)
> **Method:** DDL extracted via `pg_restore --schema-only`. No data was read. Relationships derived from column names, FK constraints, and index definitions only.
> **Dump format:** PostgreSQL custom dump (v1.16-0), produced by pg_dump 18.2.
> **Last verified:** against actual DDL extracted from the binary dump.

---

## 1. Table Inventory

The Service Order domain splits into two parallel service tracks:

| Track | Meaning |
|-------|---------|
| **UUT** | *Unit Under Test* — calibration instruments (laboratory-based, in-situ) |
| **UTTP** | *Ukuran, Takar, Timbang, Perlengkapan* — weighing/measuring instruments (field inspection) |

Both tracks share the `service_requests` → `service_order*` lifecycle.

---

## 2. Core Active Tables

### 2.1 `service_requests`

The **root** of the UUT service domain. One service request from a customer.

**Primary Key:** `id` integer (`service_requests_pkey`)
**Soft-delete:** `deleted_at` timestamp

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `requestor_id` | `integer` | → `users_customers.id` (no FK declared) |
| `uml_id` | `integer` | Unit Metrologi Lokal reference |
| `uut_owner_id` | `integer` | → instrument owner |
| `service_type_id` | `integer` | → `master_service_types.id` (implied) |
| `status_id` | `integer` | → `master_request_status.id` (implied) |
| `stat_service_request` | `integer` | Aggregate status (default 0) |
| `booking_id` | `integer` | Booking reference |
| `booking_no` | `varchar` | Human-readable booking number |
| `no_register` | `varchar` | Registration number |
| `no_order` | `varchar` | Order number |
| `payment_code` / `billing_code` | `varchar` | Payment/billing references |
| `payment_date` / `payment_status_id` | | Payment tracking |
| `payment_expired_date` | `date` | Payment deadline |
| `received_date` | `date` | Date received — **used for SLA calculation** |
| `estimated_date` | `date` | Estimated completion date |
| `service_order_id` | `integer` | **Denormalized back-reference** — not a proper FK; use with caution |
| `service_request_id` | `integer` | Self-referential (revision chain) |
| `pending_status` | `integer` | Pending hold flag |
| `cancel_id` | `integer` | Cancellation reference |
| `status_sertifikat` | `integer` | Certificate status |
| `spuh_*` | various | SPUH (travel cost) billing/payment |
| `sp1_date` / `sp2_date` / `sp3_date` | `date` | Warning letter dates |
| `to_punpn` / `to_punpn_status` | `boolean`/`smallint` | Enforcement escalation |
| `inspection_loc` / `inspection_prov_id` / `inspection_kabkot_id` | | Inspection location |
| `scheduled_test_date_from` / `_to` | `date` | Scheduled test window |
| `created_at` / `updated_at` / `deleted_at` | `timestamp` | Soft-delete lifecycle |

> ⚠️ **Note:** `cancel_at` column does **not** exist in `service_requests`. Cancellation is tracked via `cancel_id` only. The `cancel_at` column exists on `service_orders` and `service_order_uttps`, not on the request tables.

**Status fields:** `status_id`, `stat_service_request`, `payment_status_id`, `status_sertifikat`, `spuh_payment_status_id`, `pending_status`, `to_punpn_status`

---

### 2.2 `service_request_items`

Line items on a UUT service request. One request → many items.

**Primary Key:** `id` integer (`service_request_items_pk`)
**Sequence:** `service_requests_items_id_seq`
**Soft-delete:** `deleted_at` timestamp

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `request_id` | `integer` | → `service_requests.id` (no FK declared) |
| `service_request_id` | `integer` | Alias/duplicate of `request_id`; inconsistency noted |
| `uut_id` | `integer` | → `uut.id` (the instrument being tested) |
| `uml_standard_id` | `integer` | Test standard reference |
| `standard_id` | `integer` | Alternative standard reference |
| `quantity` | `integer` | Number of instruments |
| `subtotal` | `real` | Price subtotal |
| `status_id` | `integer` | Item status |
| `stat_service_request_item` | `varchar` | Extended item status |
| `sla_overide` | `smallint` | SLA override flag per item |
| `no_order` | `varchar` | Item-level order number |
| `location` / `location_prov_id` / `location_kabkot_id` / `location_lat` / `location_long` / `location_alat` / `location_negara_id` | various | Geo/location of instrument |
| `delivered_at` / `received_at` / `order_at` | `date` | Logistics timeline |
| `created_at` / `updated_at` / `deleted_at` | `timestamp` | Soft-delete lifecycle |

---

### 2.3 `service_request_uttps`

The UTTP equivalent of `service_requests`. A service request for UTTP instruments.

**Primary Key:** `id` integer (`service_request_uttps_pkey`)
**Soft-delete:** `deleted_at` timestamp

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `requestor_id` | `integer` | **NOT NULL** — customer identity |
| `pic_id` | `integer` | **NOT NULL** — PIC (Person in Charge) |
| `booking_id` | `integer` | **NOT NULL** — booking reference |
| `uttp_owner_id` | `integer` | → `uttp_owners.id` (implied) |
| `service_type_id` | `integer` | Service type |
| `stat_service_request` | `integer` | Aggregate status (default 0) |
| `status_id` | `integer` | Request status |
| `payment_status_id` / `spuh_payment_status_id` | `integer` | Payment status |
| `status_sertifikat` | `integer` | Certificate status |
| `pending_status` / `pending_notes` | | Pending/hold |
| `cancel_at` / `cancel_id` | `timestamp` / `integer` | Cancellation (cancel_at **is** present here, unlike service_requests) |
| `received_date` | `date` | Date received — **used for SLA calculation** |
| `no_register` / `no_order` | `varchar` | Registration/order numbers |
| `billing_code` | `varchar` | Billing reference |
| `requestor_name` / `requestor_phone_no` / `requestor_type_id` / `requestor_id_no` | | Requestor contact snapshot |
| `sp1_date` / `sp2_date` / `sp3_date` | `date` | Warning letter dates |
| `to_punpn` / `to_punpn_status` | | Enforcement escalation |
| `inspection_loc` / `inspection_prov_id` | | Inspection location |
| `payment_expired_date` | `timestamp` | |
| `spuh_*` | various | SPUH billing |
| `created_at` / `updated_at` / `deleted_at` | `timestamp` | Soft-delete lifecycle |

**Relationship note:** `service_request_uttps` is **structurally parallel** to `service_requests` but serves the UTTP track. There is **no declared FK** between them.

---

### 2.4 `service_request_uttp_items`

Line items on a UTTP service request.

**Primary Key:** `id` integer (`service_request_uttp_items_pk`)
**Soft-delete:** `deleted_at` timestamp

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `request_id` | `integer` | **NOT NULL** → `service_request_uttps.id` (implied) |
| `uttp_id` | `integer` | → `uttps.id` (the instrument) |
| `uml_standard_id` | `integer` | Test standard |
| `quantity` | `integer` | Instrument count |
| `subtotal` | `integer` | Price subtotal |
| `status_id` | `integer` | Item status |
| `is_pemeriksaan` | `boolean` | Inspection flag |
| `location` / `location_prov_id` / `location_kabkot_id` / `location_lat` / `location_long` / `location_alat` / `location_negara_id` | various | Geo/location |
| `delivered_at` / `received_at` / `order_at` | `timestamp` | Logistics timeline |
| `created_at` / `updated_at` / `deleted_at` | `timestamp` | Soft-delete |

---

### 2.5 `service_orders`

The **canonical active service order table** for UUT. Each row is a lab work order.

**Primary Key:** `id` integer (`service_orders_pkey`); uses sequence `service_labs_id_seq`
**Index:** `service_orders_service_request_id_idx` on `service_request_id` (btree)
**No `deleted_at`** — no soft-delete on this table.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer DEFAULT nextval('service_labs_id_seq')` | **PK** |
| `service_request_id` | `integer` | → `service_requests.id` (**indexed**) |
| `service_request_item_id` | `integer` | → `service_request_items.id` |
| `service_request_item_inspection_id` | `integer` | → `service_request_item_inspections.id` |
| `request_item_id` | `integer` | Alternative item reference |
| `laboratory_id` | `integer` | → `master_laboratory.id` |
| `uut_id` | `integer` | Direct instrument reference |
| `lab_staff` | `integer` | Lab technician (user) |
| `supervisor_staff` | `integer` | Supervisor (user) |
| `ditmet_staff` | `integer` | Ditmet approver (user) |
| `kadivtek_staff` | `integer` | Ka-Divtek approver (user) |
| `kalab_id` | `integer` | Head of Lab approver |
| `kabalai_id` | `integer` | Head of Agency approver |
| `subkoordinator_id` | `integer` | Sub-coordinator approver |
| `stat_service_order` | `integer DEFAULT 0` | **Primary order status** |
| `is_finish` | `integer DEFAULT 0` | Completion flag (0/1) |
| `stat_sertifikat` | `integer` | Certificate issuance status |
| `stat_warehouse` | `integer` | Warehouse status |
| `pending_status` | `integer` | Pending hold flag |
| `cancel_at` | `timestamp` | Cancellation timestamp (non-null = cancelled) |
| `cancel_id` | `integer` | Cancellation reference |
| `no_sertifikat` | `varchar` | Certificate number |
| `is_skhpt` | `boolean` | SKHPT (type approval) flag |
| `is_certified` | `boolean` | Certificate issued |
| `is_pnbp_returned` | `boolean` | Government fee returned |
| `batal_type` | `integer` | Cancellation type |
| `hasil_uji` / `hasil_uji_memenuhi` | `text`/`boolean` | Test result / pass-fail |
| `sertifikat_expired_at` | `date` | Certificate expiry |
| `staff_entry_datein` / `staff_entry_dateout` | `date` | Staff entry/exit timestamps |
| `warehouse_in_*` / `warehouse_out_*` | | Warehouse movement |
| `tool_*` | various | Denormalized instrument snapshot |
| `qrcode_token` / `qrcode_file` | | QR code for certificate |
| `return_value` / `return_desc` / `return_date` | `real`/`varchar`/`timestamp` | PNBP return tracking |
| `updated_at` | `timestamp` | Last update (no `created_at` on this table) |

**Status fields:** `stat_service_order`, `is_finish`, `stat_sertifikat`, `stat_warehouse`, `pending_status`, `cancel_at`, `is_certified`

---

### 2.6 `service_order_uttps`

The **canonical active service order table** for UTTP. Parallel to `service_orders`.

**Primary Key:** `id` integer (`service_order_uttps_pk`)
**No `deleted_at`** — no soft-delete on this table.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** (own sequence, not `service_labs_id_seq`) |
| `service_request_id` | `integer` | → `service_request_uttps.id` (implied) |
| `service_request_item_id` | `integer` | → `service_request_uttp_items.id` |
| `service_request_item_inspection_id` | `integer` | → `service_request_uttp_item_inspections.id` |
| `laboratory_id` | `integer` | → `master_laboratory.id` |
| `uttp_id` | `integer` | Direct instrument reference |
| `lab_staff` / `supervisor_staff` | `integer` | Staff references |
| `stat_service_order` | `integer DEFAULT 0` | **Primary order status** |
| `is_finish` | `integer DEFAULT 0` | Completion flag |
| `stat_sertifikat` | `integer` | Certificate status |
| `stat_warehouse` | `integer` | Warehouse status |
| `pending_status` | `integer` | Pending hold |
| `cancel_at` / `cancel_id` | `timestamp`/`integer` | Cancellation |
| `is_skhpt` / `is_revisi` / `is_nonaktif` | `boolean` | Order flags |
| `revisi_ke` / `revision_id` / `order_direvisi_id` | `integer` | Revision chain |
| `status_order_revisi` | `integer` | Revision order status |
| `no_sertifikat` / `no_sertifikat_tipe` | `varchar` | Certificate numbers |
| `sertifikat_expired_at` | `date` | Certificate expiry |
| `hasil_uji` / `hasil_uji_memenuhi` / `hasil_pemeriksaan_memenuhi` | `text`/`boolean` | Test results |
| `location_lat` / `location_long` / `location_alat` | | Geolocation |
| `mulai_uji` / `selesai_uji` | `date` | Test start/end dates |
| `tool_*` | various | Denormalized UTTP snapshot |

---

### 2.7 `service_order_inspections`

Inspection checklist items for a **UUT** service order.

**Primary Key:** `id` integer (`service_order_inspections_pk`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `order_id` | `integer` | → `service_orders.id` (no FK declared) |
| `inspection_item_id` | `integer` | → inspection item catalog (table not confirmed) |
| `is_accepted` | `boolean` | Pass/fail per inspection item |

---

### 2.8 `service_order_uttp_inspections`

Inspection checklist for a **UTTP** service order.

**Primary Key:** `id` integer (`service_order_uttp_inspections_pk`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `order_id` | `integer` | → `service_order_uttps.id` (no FK declared) |
| `inspection_item_id` | `integer` | → inspection item catalog |
| `is_accepted` | `boolean` | Pass/fail |
| `order_no` | `integer` | Sequence within order |

---

### 2.9 `service_order_uttp_insitu_laporan`

Field inspection report for UTTP in-situ (on-site) orders.

**Primary Key:** `id` integer (`service_order_uttp_insitu_laporan_pk`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `service_order_id` | `integer` | → `service_order_uttps.id` (implied) |
| `service_request_id` | `integer` | → `service_request_uttps.id` |
| `service_request_item_id` | `integer` | → line item |
| `ringkasan` | `text` | Summary |
| `kendala_teknis` / `kendala_non_teknis` | `text` | Technical/non-technical issues |
| `metode_tindakan` | `text` | Action method |
| `saran_masukan` | `text` | Recommendations |

---

### 2.10 `service_order_uut_insitu_laporan`

Field inspection report for UUT in-situ orders. Structurally identical to `service_order_uttp_insitu_laporan`.

**Primary Key:** `id` integer (`service_order_uut_insitu_laporan_pk`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `service_order_id` | `integer` | → `service_orders.id` (implied) |
| `service_request_id` | `integer` | → `service_requests.id` |
| `service_request_item_id` | `integer` | → `service_request_items.id` |
| `ringkasan` / `kendala_*` / `metode_tindakan` / `saran_masukan` | `text` | Report fields |

---

### 2.11 `service_request_item_inspections`

Maps inspection price/type to a UUT request item. Tracks per-item certification status.

**Primary Key:** `id` integer (`service_request_item_inspections_pkey2`)
**Sequence:** `service_requests_item_inspections_id_seq`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `service_request_item_id` | `integer` NOT NULL | → `service_request_items.id` |
| `inspection_price_id` | `integer` NOT NULL | → inspection price catalog |
| `price` | `integer DEFAULT 0` | Agreed price |
| `qty_inspection` | `integer DEFAULT 0` | Inspection quantity |
| `quantity` | `integer` NOT NULL | Instrument quantity |
| `service_status_id` | `integer` | Service status |
| `status_id` | `integer` | Item status |
| `status_sertifikat` | `integer` | Certificate status |
| `laboratory_id` | `integer` | → `master_laboratory.id` |
| `request_item_id` | `integer` | Cross-reference |
| `updated_at` / `created_at` | `date` | Lifecycle |

---

### 2.12 `master_laboratory`

Reference table for laboratories.

**Primary Key:** `id` integer (`master_laboratoryori_pkey`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `nama_lab` | `varchar(100)` | Laboratory name |
| `is_active` | `boolean` | Active flag |
| `tipe` | `varchar(25)` | Lab type |
| `quota_online` / `quota_offline` | `integer` | Capacity quotas |
| `kaji_ulang` | `text` | Review notes |
| `sla_day` | `integer` | **SLA in days** for this lab — used for deadline computation |
| `sla_overide` | `boolean` | Whether per-lab SLA overrides global `master_uttp_sla` |
| `besaran` | `varchar` | Measurement domain |

---

### 2.13 `master_uttp_sla`

Reference SLA table for UTTP instrument types and service types.

**Primary Key:** `id` integer (`master_uttp_sla_pk`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `kelompok` | `varchar` | UTTP group/category |
| `jenis_pengujian` | `varchar` | Type of testing |
| `sla` | `real` | SLA value (days) |
| `service_type_id` | `integer` | → `service_types.id` (implied) |

> **Join gap:** `master_uttp_sla` has no direct column linking it to `service_order_uttps` or `service_request_uttps`. It keys on `kelompok` + `jenis_pengujian` + `service_type_id`. The AI layer **cannot** join it to order tables without application-level knowledge of how `kelompok` and `jenis_pengujian` are populated.

---

### 2.14 `users_customers`

Customer (external requestor) user accounts.

**Primary Key:** `id` integer (`users_customers_pkey`)
**Unique constraint:** `email` (`users_customers_email_unique`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `full_name` | `varchar(255)` | **NOT NULL** |
| `email` | `varchar(255)` | **NOT NULL, UNIQUE** |
| `username` | `varchar(255)` | Login username |
| `is_active` | `boolean` | Account active |
| `uml_id` | `integer` | → UML (local office) |
| `kota_id` | `integer` | → city reference |
| `uttp_owner_id` | `integer` | → `uttp_owners.id` |
| `uut_owner_id` | `integer` | → `uut_owners.id` (implied) |
| `bentuk_usaha_id` | `integer` | → business entity type |
| `npwp` | `varchar(50)` | Tax registration (PII) |
| `nib` | `varchar(50)` | Business registration (PII) |
| `kantor` | `varchar(100)` | Company/office name |
| `phone` / `alamat` | `varchar` | Contact info (PII) |
| `penanggung_jawab` | `varchar` | Responsible person (PII) |
| `ktp` | `varchar` | National ID number (sensitive PII) |
| `password` / `remember_token` / `token` | | Auth fields — **never expose** |

---

### 2.15 `service_request_uut_staff`

Staff scheduling for UUT service requests.

**Primary Key:** `id` integer (confirmed from DDL)

| Column | Type | Notes |
|--------|------|-------|
| `id` | `integer` | **PK** |
| `request_id` | `integer` | → `service_requests.id` (implied) |
| `scheduled_id` | `integer` | → scheduling table (not analysed) |

---

### 2.16 Supporting Tables (Active)

| Table | Purpose | Key Columns |
|-------|---------|------------|
| `service_request_uttp_item_inspections` | Inspection items for UTTP request | `request_item_id` → `service_request_uttp_items.id`, `inspection_price_id`, `status_id`, `status_sertifikat`, `status_uttp` |
| `service_request_standard_item_inspections` | Inspection items for standard requests | `request_item_id` → `service_request_standard_items.id` |
| `service_request_uttp_kajiulang` | Contract review (kajian ulang) for UTTP | `request_id`, `request_item_id` |
| `service_request_uttp_kajiulang_klausa` | Clause-level detail for UTTP kajian ulang | `kajiulang_id` |
| `service_request_uttp_insitu_doc` | In-situ field inspection document for UTTP | `request_id`, billing, payment, SPUH fields |
| `service_request_uut_insitu_doc` | In-situ field inspection document for UUT | Structurally identical to UTTP variant |
| `service_request_uttp_insitu_staff` | Staff assigned to UTTP in-situ doc | `doc_id`, `scheduled_id` |
| `service_request_uut_insitu_staff` | Staff assigned to UUT in-situ doc | `doc_id`, `scheduled_id` |
| `service_request_uttp_staff` | Staff scheduling for UTTP requests | `request_id`, `scheduled_id` |
| `service_request_uut_item_ttu_perlengkapan` | TTU ancillary equipment per UUT item | `request_item_id`, `uut_id` |
| `service_request_uttp_item_ttu_perlengkapan` | TTU ancillary equipment per UTTP item | `request_item_id`, `uttp_id` |
| `service_order_uttp_tipe` | Type-approval info for UTTP order | `order_id` |
| `service_order_uut_tipe` | Type-approval info for UUT order | `order_id` |
| `service_order_uttp_ttu_inspection` | TTU inspection for UTTP order | `order_id` |
| `service_order_uut_ttu_inspection` | TTU inspection for UUT order | `order_id` |
| `service_order_uttp_ttu_badanhitung` | Tachograph body calculation | `order_id` |
| `service_order_uut_ttu_badanhitung` | Tachograph body calculation (UUT) | `order_id` |
| `service_order_uttp_ttu_insp_items` | Individual TTU inspection items (UTTP) | `order_id` |
| `service_order_uut_ttu_insp_items` | Individual TTU inspection items (UUT) | `order_id` — **no PK constraint in DDL** |
| `service_order_uttp_ttu_perlengkapan` | TTU ancillary equipment (UTTP order) | `order_id` |
| `service_order_uut_ttu_perlengkapan` | TTU ancillary equipment (UUT order) | `order_id` |
| `service_order_uttp_ttu_ctms` | CTMS (fuel meter) inspection | `order_id` |
| `service_order_uttp_ttu_ctms_gauge` | CTMS gauge details | |
| `service_order_uttp_ttu_ctms_sistem` | CTMS system details | |
| `service_order_uttp_ttu_ctms_tank` | CTMS tank details | |
| `service_order_uttp_ttu_ctms_perlengkapan` | CTMS equipment | |
| `service_order_uttp_ttu_insp_suhu` | Temperature sub-inspection for UTTP | |
| `uttps` | UTTP instrument master registry | `id` PK, `owner_id`, `type_id` → `master_uttp_types` |
| `uut` | UUT instrument master registry | `id` PK, `owner_id`, `type_id` |
| `master_service_types` | Service type reference | `service_type`, `prefix` |
| `service_types` | Simplified service type reference | |
| `master_request_status` | Status lookup | `status` varchar |

---

## 3. Foreign Key Constraints (Declared)

Only **four FK constraints** are declared across the entire service domain. The vast majority of relationships are **convention-based** (column naming), not enforced at the database level.

| Table | Column | References | Constraint Name |
|-------|--------|-----------|----------------|
| `service_order` *(legacy)* | `lab_staff` | `users(id)` | `service_order_lab_staff_foreign` |
| `service_order` *(legacy)* | `supervisor` | `users(id)` | `service_order_supervisor_foreign` |
| `service_request_item_inspections_o` *(legacy)* | `service_request_item_id` | `service_request_items_o(id)` | `service_request_item_inspections_service_request_item_id_foreig` |
| `service_request_item_inspections_o` *(legacy)* | `standard_inspection_price_id` | `standard_inspection_prices(id)` | `service_request_item_inspections_standard_inspection_price_id_f` |

> ⚠️ **Critical:** All four declared FK constraints reference **legacy tables** (`service_order`, `service_request_items_o`, `service_request_item_inspections_o`). The production tables (`service_orders`, `service_order_uttps`, `service_requests`, `service_request_uttps`, etc.) have **zero declared FK constraints** and rely entirely on application-level referential integrity.

> ⚠️ **AI Layer Warning:** Do NOT assume referential integrity. All cross-table joins must treat foreign columns as soft references. NULL or orphaned values are possible.

---

## 4. Inferred Relationships (No FK Constraint)

| From Table | Column | To Table | Confidence |
|-----------|--------|---------|-----------|
| `service_requests` | `requestor_id` | `users_customers.id` | High |
| `service_requests` | `uut_owner_id` | (uut owner table) | Medium |
| `service_requests` | `service_type_id` | `master_service_types.id` | High |
| `service_requests` | `status_id` | `master_request_status.id` | High |
| `service_request_items` | `request_id` | `service_requests.id` | High |
| `service_request_items` | `uut_id` | `uut.id` | High |
| `service_request_uttps` | `requestor_id` | `users_customers.id` | High |
| `service_request_uttps` | `uttp_owner_id` | `uttp_owners.id` | High |
| `service_request_uttp_items` | `request_id` | `service_request_uttps.id` | High |
| `service_request_uttp_items` | `uttp_id` | `uttps.id` | High |
| `service_orders` | `service_request_id` | `service_requests.id` | **Confirmed** (index: `service_orders_service_request_id_idx`) |
| `service_orders` | `service_request_item_id` | `service_request_items.id` | High |
| `service_orders` | `laboratory_id` | `master_laboratory.id` | High |
| `service_orders` | `uut_id` | `uut.id` | High |
| `service_order_uttps` | `service_request_id` | `service_request_uttps.id` | High |
| `service_order_uttps` | `laboratory_id` | `master_laboratory.id` | High |
| `service_order_uttps` | `uttp_id` | `uttps.id` | High |
| `service_order_inspections` | `order_id` | `service_orders.id` | High |
| `service_order_uttp_inspections` | `order_id` | `service_order_uttps.id` | High |
| `service_request_item_inspections` | `laboratory_id` | `master_laboratory.id` | High |
| `uttps` | `type_id` | `master_uttp_types.id` | High |
| `master_uttp_sla` | `service_type_id` | `service_types.id` | High |
| `users_customers` | `uttp_owner_id` | `uttp_owners.id` | High |

---

## 5. Status Fields Summary

### `service_requests` / `service_request_uttps`

| Field | Table | Meaning |
|-------|-------|---------|
| `status_id` | both | Current workflow status (lookup: `master_request_status`) |
| `stat_service_request` | both | Aggregate numeric status (integer, default 0) |
| `payment_status_id` | both | Main payment status |
| `spuh_payment_status_id` | both | SPUH (travel cost) payment status |
| `pending_status` | both | Pending hold (integer) |
| `status_sertifikat` | both | Certificate aggregation status |
| `to_punpn_status` | both | Enforcement/penalisation status (smallint) |
| `cancel_at` | **UTTP only** | Cancellation timestamp — `service_requests` does NOT have this column |
| `cancel_id` | both | Cancellation reference integer |

### `service_orders` / `service_order_uttps`

| Field | Table | Meaning |
|-------|-------|---------|
| `stat_service_order` | both | Primary order status (integer, default 0) |
| `is_finish` | both | Completion flag (integer 0/1) |
| `stat_sertifikat` | both | Certificate issuance status |
| `stat_warehouse` | both | Instrument warehouse status |
| `pending_status` | both | Hold status |
| `cancel_at` | both | Cancellation timestamp (non-null = cancelled) |
| `is_certified` | UUT only | Certificate issued (boolean) |
| `is_pnbp_returned` | UUT only | Government fee returned |
| `is_nonaktif` | UTTP only | Revision superseded flag — treated as cancelled in AI view |
| `is_revisi` | UTTP only | This order is a revision |
| `status_order_revisi` | UTTP only | Revision lifecycle status |

### `service_request_item_inspections` / `service_request_uttp_item_inspections`

| Field | Meaning |
|-------|---------|
| `status_id` | Item-level status |
| `status_sertifikat` | Per-item certificate status |
| `status_uttp` | UTTP-specific status (UTTP variant only) |

---

## 6. SLA Relationship

SLA tracking spans three layers:

1. **`master_uttp_sla`** — Reference SLA by UTTP group + service type (`sla` column, real value in days). No FK to any order table. **Cannot be joined to order tables directly.**

2. **`master_laboratory.sla_day`** — Per-laboratory SLA default (integer days). `sla_overide` boolean controls whether lab SLA takes precedence over `master_uttp_sla`.

3. **`service_request_items.sla_overide`** — Per-line-item SLA override flag (smallint). Allows individual items to bypass standard SLA.

> **Missing:** There is no `sla_started_at` or `sla_deadline` column on any order table. SLA tracking is always **derived**:
> ```
> sla_deadline = received_date + sla_day
> ```
> where `received_date` comes from `service_requests.received_date` (UUT) or `service_request_uttps.received_date` (UTTP), and `sla_day` comes from `master_laboratory.sla_day`.

---

## 7. Customer Relationship

```
users_customers.id
    ↓ (requestor_id — no FK)
service_requests.requestor_id          — UUT track
service_request_uttps.requestor_id     — UTTP track
```

`users_customers` links to instrument owners via:
- `uttp_owner_id` → `uttp_owners.id`
- `uut_owner_id` → (UUT owner table — not investigated in this analysis)

`service_requests.uut_owner_id` links directly without going through `users_customers`.

> **No FK constraint exists** between `service_requests.requestor_id` and `users_customers.id`. The join is application-enforced only.

---

## 8. Laboratory Relationship

```
master_laboratory.id
    ↓ (laboratory_id — no FK)
service_orders.laboratory_id                       — UUT lab assignment
service_order_uttps.laboratory_id                  — UTTP lab assignment
service_request_item_inspections.laboratory_id     — Item-level lab assignment
```

`master_laboratory` also carries SLA configuration (`sla_day`, `sla_overide`). It is the primary source for SLA computation in the AI view.

---

## 9. Inspection Relationship

Two parallel hierarchies:

**UUT path:**
```
service_requests → service_request_items
                         ↓
                service_request_item_inspections
                         ↓
                service_orders (via service_request_item_inspection_id)
                         ↓
                service_order_inspections (order-level checklist)
                         ↓
                service_order_uut_ttu_* (TTU sub-inspections)
```

**UTTP path:**
```
service_request_uttps → service_request_uttp_items
                               ↓
                   service_request_uttp_item_inspections
                               ↓
                   service_order_uttps (via service_request_item_inspection_id)
                               ↓
                   service_order_uttp_inspections (order-level checklist)
                               ↓
                   service_order_uttp_ttu_* (TTU sub-inspections)
                               ↓
                   service_order_uttp_ttu_ctms_* (CTMS fuel meter sub-trees)
```

TTU (Type Testing Unit) sub-inspections branch from `service_order_uttps` and `service_orders` into multiple `service_order_uttp_ttu_*` / `service_order_uut_ttu_*` tables.

---

## 10. Legacy / Backup Tables

The following tables are confirmed as legacy or backup from DDL analysis and **must not** be used by the AI layer:

| Table | Evidence | Key Finding from DDL |
|-------|---------|---------------------|
| `service_order` | 6-column prototype | Only columns: `id`, `order_no`, `supervisor`, `supervisor_entry_date`, `lab_staff`, `staff_entry_date`. The only service-domain table with declared FK constraints — but to `users`, not the service domain. |
| `service_order_bck` | `_bck` suffix; **no PK constraint** | Structurally matches `service_orders` but frozen. Column `tool_capacity` is `integer` vs `character varying` in live table — schema drift confirmed. |
| `service_orders_old` | `_old` suffix; own PK `service_orders_pkey_1` | **Uses same sequence `service_labs_id_seq` as `service_orders`** — IDs may overlap. Lacks columns added after creation (`is_certified`, `batal_type`, `return_*`). |
| `service_request_items_o` | `_o` (old) suffix | Has declared FK to `standard_inspection_prices` (old price table). Superseded schema. |
| `service_request_item_inspections_o` | `_o` (old) suffix | FKs reference `service_request_items_o`. Superseded FK chain. |
| `service_request_uttp_items_bck` | `_bck` suffix; **no PK** | Confirmed older schema. |
| `service_order_uttps_des` | Suspected `des` = destroyed/description variant; **no PK** | Identical column set to `service_order_uttps` **minus** the revision columns (`is_revisi`, `is_nonaktif`, `revisi_ke`, `revision_id`, `order_direvisi_id`, `status_order_revisi`, `revision_date`). Frozen before revision feature was added. |
| `service_order_uttps_mirror` | `_mirror` suffix; **no PK** | Identical to `service_order_uttps_des`. Same frozen column set — also missing all revision columns. Shadow copy. |
| `service_request_uut_staff_1` | `_1` suffix | Schema identical to `service_request_uut_staff` (3 columns: `id`, `request_id`, `scheduled_id`). Confirmed duplicate. |
| `users_customers_1` | `_1` suffix | Confirmed missing: `bentuk_usaha_id`, `penanggung_jawab`, `ktp`. Older backup without these columns. |
| `master_laboratory_backup` | `_backup` suffix | Confirmed missing: `sla_day`, `sla_overide`, `besaran`, `kaji_ulang`, `quota_online`, `quota_offline`. Older schema backup. |
| `uttps_20231228_2358` | Date-stamped snapshot (2023-12-28) | Snapshot. |
| `uttps_20240110_0147` | Date-stamped snapshot (2024-01-10) | Snapshot. |
| `uttps_backup` | `_backup` suffix | Completely different schema (market survey data). |
| `master_standard_backup` | `_backup` suffix | Backup of standards table. |
| `master_standard_units_backup` | `_backup` suffix | Backup of standard units table. |

---

## 11. Tables That SHOULD NOT Be Used by the AI Layer

In addition to the legacy/backup tables above:

| Table | Reason |
|-------|--------|
| `service_order` | 6-column prototype; not part of production flow |
| `service_order_bck` | Backup snapshot; no PK |
| `service_orders_old` | Historical snapshot; **shares sequence with `service_orders`** — ID collisions possible |
| `service_request_items_o` | Superseded schema; FK to deprecated price table |
| `service_request_item_inspections_o` | Superseded; old FK chain |
| `service_request_uttp_items_bck` | Backup; no PK |
| `service_order_uttps_des` | Frozen pre-revision snapshot; no PK; missing revision columns |
| `service_order_uttps_mirror` | Shadow copy; no PK; missing revision columns |
| `service_request_uut_staff_1` | Duplicate of `service_request_uut_staff` |
| `users_customers_1` | Backup of `users_customers` (missing newer columns) |
| All `*_backup` tables | Backup snapshots |
| All `*_old` / `*_o` / `*_1` / date-stamped tables | Legacy/deprecated schemas |

---

## 12. Missing / Unresolved Information

The following relationships could **not be confirmed** from DDL alone:

1. **`service_requests.requestor_id` → `users_customers.id`** — No FK declared; inferred by column name. Needs application-level verification.

2. **`service_request_uttps.booking_id` → ?** — `booking_id NOT NULL`, but no `bookings` table was identified in the schema. Relationship is missing or uses a table not included in this analysis.

3. **SLA start/deadline columns** — No explicit `sla_start_at` or `sla_deadline` column exists on any order table. SLA computation must be derived by the AI layer using `received_date` + `master_laboratory.sla_day`.

4. **`inspection_item_id` references** — Both `service_order_inspections.inspection_item_id` and `service_order_uttp_inspections.inspection_item_id` reference an inspection item catalog. The exact target table was not confirmed from DDL.

5. **`standard_inspection_prices` / `uttp_inspection_prices`** — Referenced by `service_request_item_inspections.inspection_price_id` and UTTP counterpart. Table schema not analysed in this document.

6. **`uttps.owner_id` / `uut.owner_id`** — Instrument owner mapping. Target tables (`uttp_owners`, `uut_owners`) exist in schema listing but were not fully analysed.

7. **`service_order_uut_ttu_insp_items`** — Has **no PK constraint** in DDL. Likely oversight, not intentional design.

8. **`service_requests` has no `cancel_at` column** — Cancellation on UUT requests is tracked via `cancel_id` only. UTTP requests (`service_request_uttps`) DO have `cancel_at`. This asymmetry is confirmed from DDL and must be handled correctly in queries.

---

## 13. Authoritative Tables for AI Layer

The AI layer **SHOULD** use only the following tables (or the `ai_service_order_summary` view):

| Table | Role |
|-------|------|
| `service_requests` | UUT service request root |
| `service_request_items` | UUT request line items |
| `service_request_item_inspections` | UUT item inspection assignments |
| `service_request_uttps` | UTTP service request root |
| `service_request_uttp_items` | UTTP request line items |
| `service_request_uttp_item_inspections` | UTTP item inspection assignments |
| `service_orders` | UUT lab work orders |
| `service_order_uttps` | UTTP field/lab work orders |
| `service_order_inspections` | UUT order-level checklist |
| `service_order_uttp_inspections` | UTTP order-level checklist |
| `service_order_uttp_insitu_laporan` | UTTP in-situ field report |
| `service_order_uut_insitu_laporan` | UUT in-situ field report |
| `master_laboratory` | Laboratory reference + SLA config |
| `master_uttp_sla` | UTTP SLA reference (no direct join key to orders) |
| `master_service_types` | Service type reference |
| `users_customers` | Customer accounts |
| `uttps` | UTTP instrument registry |
| `uut` | UUT instrument registry |
| `master_request_status` | Status lookup |

> **Preferred entry point:** Use the `ai_service_order_summary` view ([`database/views/ai_service_order_summary.sql`](../../database/views/ai_service_order_summary.sql)) rather than querying production tables directly. See [`docs/database/ai-service-order-summary.md`](./ai-service-order-summary.md) for view reference.
