# `ai_service_order_summary` — View Reference

> **Project:** ServiceIQ — AI-Powered Enterprise Service Intelligence Platform  
> **Schema:** `public`  
> **Object type:** `VIEW` (read-only)  
> **Definition file:** [`database/views/ai_service_order_summary.sql`](../../database/views/ai_service_order_summary.sql)  
> **Based on:** [`docs/database/service-order-domain-analysis.md`](./service-order-domain-analysis.md)

---

## Purpose

`ai_service_order_summary` is a **read-only semantic view** that provides a single, unified row per service order for consumption by the ServiceIQ AI layer. It abstracts away the dual-track schema (UUT and UTTP), derives computed fields (order status, inspection status, SLA), and suppresses all sensitive and operationally-internal columns.

The AI layer must **not** query production transactional tables directly. This view is the intended entry point for all service order intelligence.

---

## Source Tables

| Table | Role | Track | Notes |
|-------|------|-------|-------|
| `service_orders` | Work-order root | UUT | Indexed on `service_request_id` |
| `service_requests` | Service request parent | UUT | Soft-deleted via `deleted_at` |
| `service_order_uttps` | Work-order root | UTTP | Includes `is_nonaktif` for revision cancellation |
| `service_request_uttps` | Service request parent | UTTP | Soft-deleted via `deleted_at` |
| `users_customers` | Customer accounts | Both | Joined via `requestor_id` (no FK constraint) |
| `master_laboratory` | Lab reference + SLA config | Both | Supplies `sla_day` for deadline computation |
| `master_service_types` | Service type labels | Both | Joined via `service_type_id` |
| `service_order_inspections` | Order-level inspection checklist | UUT | Correlated subquery; one-to-many |
| `service_order_uttp_inspections` | Order-level inspection checklist | UTTP | Correlated subquery; one-to-many |

---

## Output Columns

| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `service_order_id` | `integer` | `service_orders.id` / `service_order_uttps.id` | Primary key of the work order. Unique within each track; **not** globally unique across both tracks — use together with `track` to form a surrogate key. |
| `order_number` | `varchar` | `service_requests.no_order` / `service_request_uttps.no_order` | Human-readable order number from the parent service request. May be `NULL` if the service request row is missing or the field was not yet assigned. |
| `service_request_id` | `integer` | `service_orders.service_request_id` / `service_order_uttps.service_request_id` | Foreign reference back to the parent service request. No FK constraint exists; may reference a deleted or missing request row. |
| `track` | `text` | Literal constant | Discriminator: `'UUT'` (calibration instruments) or `'UTTP'` (weighing/measuring instruments). |
| `customer_id` | `integer` | `users_customers.id` | Internal ID of the customer account. `NULL` when `requestor_id` has no matching row in `users_customers`. |
| `customer_name` | `varchar(255)` | `users_customers.full_name` | Full name of the customer. `NULL` when customer lookup fails. **Not** the company name (`kantor`); that field is excluded as non-essential PII. |
| `service_type` | `varchar(255)` | `master_service_types.service_type` | Human-readable service type label (e.g. `'Kalibrasi'`, `'Verifikasi'`). `NULL` when `service_type_id` has no match. |
| `laboratory_id` | `integer` | `service_orders.laboratory_id` / `service_order_uttps.laboratory_id` | ID of the assigned laboratory. `NULL` for unassigned orders. |
| `laboratory_name` | `varchar(100)` | `master_laboratory.nama_lab` | Human-readable laboratory name. `NULL` when `laboratory_id` is `NULL` or unmatched. |
| `order_status` | `text` | Derived — see §Order Status Logic | Normalised lifecycle status label. One of: `new`, `in_progress`, `pending`, `certified`, `completed`, `cancelled`. |
| `inspection_status` | `text` | Derived — see §Inspection Status Logic | Aggregated checklist result. One of: `no_inspection`, `passed`, `failed`, `partial`. |
| `sla_deadline` | `date` | Derived — see §SLA Logic | Computed target completion date. `NULL` when inputs are missing. |
| `sla_status` | `text` | Derived — see §SLA Logic | Current SLA compliance. One of: `no_sla`, `on_track`, `at_risk`, `overdue`, `closed`. |

---

## Derived Field Logic

### Order Status

Computed from `stat_service_order`, `is_finish`, `cancel_at`, `pending_status`, `stat_sertifikat`. Priority is applied top-to-bottom; the first matching condition wins.

| Priority | Condition | Value |
|----------|-----------|-------|
| 1 | `cancel_at IS NOT NULL` (or `is_nonaktif = TRUE` for UTTP) | `'cancelled'` |
| 2 | `pending_status IS NOT NULL AND pending_status > 0` | `'pending'` |
| 3 | `is_finish = 1` | `'completed'` |
| 4 | `stat_sertifikat IS NOT NULL AND stat_sertifikat > 0` | `'certified'` |
| 5 | `stat_service_order IS NOT NULL AND stat_service_order > 0` | `'in_progress'` |
| 6 | (default) | `'new'` |

> **Note:** `is_nonaktif` is UTTP-only and indicates a superseded revision, treated as `cancelled` at the view level. UUT does not have this flag.

---

### Inspection Status

Computed via a correlated subquery against `service_order_inspections` (UUT) or `service_order_uttp_inspections` (UTTP). Avoids row multiplication from a JOIN.

| Condition | Value |
|-----------|-------|
| No rows exist for the order | `'no_inspection'` |
| At least one row has `is_accepted = FALSE` | `'failed'` |
| All rows have `is_accepted = TRUE` | `'passed'` |
| Mix of `TRUE` and `NULL` (partial evaluation) | `'partial'` |

---

### SLA Logic

There are **no** `sla_deadline` or `sla_started_at` columns in any order table. The deadline is always computed.

**Formula:**
```
sla_deadline = received_date + sla_day
```

| Input | Source column |
|-------|--------------|
| `received_date` | `service_requests.received_date` (UUT) / `service_request_uttps.received_date` (UTTP) |
| `sla_day` | `master_laboratory.sla_day` |

`sla_deadline` is `NULL` when either `received_date` or `sla_day` is `NULL`.

**`sla_status` values:**

| Condition | Value |
|-----------|-------|
| `received_date` or `sla_day` is `NULL` | `'no_sla'` |
| Order is completed or cancelled | `'closed'` |
| `CURRENT_DATE > sla_deadline` | `'overdue'` |
| `CURRENT_DATE > sla_deadline - 2` | `'at_risk'` |
| (otherwise) | `'on_track'` |

> **At-risk window:** 2 calendar days before deadline. This is a configurable constant in the `CASE` expression; adjust to business requirement.

---

## Excluded / Suppressed Fields

The following fields are deliberately **not exposed** by this view:

| Category | Fields | Reason |
|----------|--------|--------|
| Auth secrets | `password`, `remember_token`, `token` | Security — never in AI context |
| PII | `ktp`, `npwp`, `nib`, `alamat`, `phone`, `penanggung_jawab` | Privacy — not required for order intelligence |
| Instrument snapshot | `tool_*` (all) | Denormalized volatile data — not semantic summary |
| Certificate artifacts | `no_sertifikat`, `qrcode_token`, `qrcode_file` | Detail, not summary |
| Test result detail | `hasil_uji`, `hasil_uji_memenuhi` | Detail per order; not summary-level |
| Billing internals | `spuh_*`, `denda_*`, `billing_code` | Operational finance detail |
| Free-text notes | `cancel_notes`, `pending_notes` | Not structured; AI should query separately |
| Revision chain | `revision_id`, `revisi_ke`, `order_direvisi_id` | Structural; not summary field |
| Approval workflow | `kalab_id`, `kabalai_id`, `subkoordinator_id` | Workflow detail |

---

## Integrity Constraints

Since no FK constraints exist on the production service-domain tables:

- All JOINs to `users_customers`, `master_laboratory`, and `master_service_types` are `LEFT JOIN`. Missing lookups produce `NULL` columns, **not** missing rows.
- `service_requests.deleted_at IS NULL` and `service_request_uttps.deleted_at IS NULL` filters are applied to exclude soft-deleted parent requests.
- An order can exist without a matching service request (orphaned order). It will appear in the view with `NULL` values for all request-derived columns.

---

## Uniqueness Constraint

`service_order_id` is **not globally unique** across the view because the UUT and UTTP tracks have independent sequences. Use the composite `(track, service_order_id)` as a surrogate key:

```sql
-- Correct: uniquely identifies a row
WHERE track = 'UUT' AND service_order_id = 42

-- Incorrect: may return rows from both tracks
WHERE service_order_id = 42
```

---

## SQL Test Queries

### Test 1 — Valid order (basic retrieval)

Retrieve one complete row from each track to confirm all columns are populated correctly.

```sql
-- UUT: first 1 active order with all fields
SELECT
    service_order_id,
    order_number,
    service_request_id,
    track,
    customer_id,
    customer_name,
    service_type,
    laboratory_id,
    laboratory_name,
    order_status,
    inspection_status,
    sla_deadline,
    sla_status
FROM public.ai_service_order_summary
WHERE track = 'UUT'
  AND order_status != 'cancelled'
ORDER BY service_order_id DESC
LIMIT 1;

-- UTTP: first 1 active order
SELECT
    service_order_id,
    order_number,
    service_request_id,
    track,
    customer_id,
    customer_name,
    service_type,
    laboratory_id,
    laboratory_name,
    order_status,
    inspection_status,
    sla_deadline,
    sla_status
FROM public.ai_service_order_summary
WHERE track = 'UTTP'
  AND order_status != 'cancelled'
ORDER BY service_order_id DESC
LIMIT 1;
```

**Expected:** One row per query with all columns populated. `order_status` should not be `'cancelled'`. `customer_name` and `laboratory_name` may be `NULL` if lookups are unresolved.

---

### Test 2 — Non-existent order

Verify that querying a non-existent order ID returns zero rows and does not error.

```sql
SELECT *
FROM public.ai_service_order_summary
WHERE track = 'UUT'
  AND service_order_id = -1;
```

**Expected:** Zero rows returned, no error.

```sql
SELECT *
FROM public.ai_service_order_summary
WHERE track = 'UTTP'
  AND service_order_id = -1;
```

**Expected:** Zero rows returned, no error.

---

### Test 3 — Customer with multiple orders

Confirm that a customer with multiple orders produces the correct number of rows and that `customer_id` and `customer_name` are consistent across all rows.

```sql
SELECT
    customer_id,
    customer_name,
    track,
    COUNT(*)                AS order_count,
    MIN(sla_deadline)       AS earliest_deadline,
    MAX(sla_deadline)       AS latest_deadline,
    COUNT(*) FILTER (WHERE order_status = 'overdue' OR sla_status = 'overdue')
                            AS overdue_count
FROM public.ai_service_order_summary
WHERE customer_id IS NOT NULL
GROUP BY customer_id, customer_name, track
HAVING COUNT(*) > 1
ORDER BY order_count DESC
LIMIT 5;
```

**Expected:**
- Each row has the same `customer_id` and `customer_name` within a group.
- `order_count` > 1 for all returned rows.
- No duplicate-group anomalies (i.e., same `customer_id` with different `customer_name` should not occur — would indicate data quality issue).

---

### Test 4 — Order without inspection

Confirm that orders with no inspection checklist rows surface as `'no_inspection'` and are not dropped from the view.

```sql
SELECT
    service_order_id,
    track,
    order_number,
    order_status,
    inspection_status
FROM public.ai_service_order_summary
WHERE inspection_status = 'no_inspection'
ORDER BY service_order_id DESC
LIMIT 10;
```

**Expected:** Rows are returned (not empty, unless every order in the database has inspections). `inspection_status` = `'no_inspection'` for all rows. The order rows themselves must be present despite having no matching rows in `service_order_inspections` / `service_order_uttp_inspections`.

Cross-check: verify the correlated subquery returns 0 for one of these order IDs:

```sql
-- Replace <id> with a service_order_id from the above result where track = 'UUT'
SELECT COUNT(*)
FROM public.service_order_inspections
WHERE order_id = <id>;
-- Expected: 0
```

---

### Test 5 — Order without laboratory

Verify that orders with `laboratory_id = NULL` or no matching `master_laboratory` row appear in the view with `NULL` laboratory columns, and are not silently excluded.

```sql
SELECT
    service_order_id,
    track,
    order_number,
    laboratory_id,
    laboratory_name,
    sla_deadline,
    sla_status
FROM public.ai_service_order_summary
WHERE laboratory_id IS NULL
   OR laboratory_name IS NULL
ORDER BY service_order_id DESC
LIMIT 10;
```

**Expected:**
- Rows exist (not dropped).
- `laboratory_name` is `NULL`.
- `sla_deadline` is `NULL` (since `sla_day` comes from `master_laboratory`).
- `sla_status` is `'no_sla'`.

---

### Test 6 — Order with SLA data

Verify SLA computation is correct and status values are distributed sensibly.

```sql
-- Distribution of sla_status across all orders
SELECT
    track,
    sla_status,
    COUNT(*) AS order_count
FROM public.ai_service_order_summary
GROUP BY track, sla_status
ORDER BY track, sla_status;
```

**Expected:** Results in all five `sla_status` values (`no_sla`, `on_track`, `at_risk`, `overdue`, `closed`) depending on data. `no_sla` will dominate if laboratories have `NULL` `sla_day`.

```sql
-- Spot-check: verify manual SLA calc matches view output for a known UUT order
SELECT
    v.service_order_id,
    v.track,
    v.sla_deadline                      AS view_sla_deadline,
    v.sla_status                        AS view_sla_status,
    sr.received_date                    AS raw_received_date,
    ml.sla_day                          AS raw_sla_day,
    sr.received_date + ml.sla_day       AS manual_sla_deadline,
    CASE
        WHEN sr.received_date IS NULL OR ml.sla_day IS NULL
            THEN 'no_sla'
        WHEN so.is_finish = 1 OR so.cancel_at IS NOT NULL
            THEN 'closed'
        WHEN CURRENT_DATE > (sr.received_date + ml.sla_day)
            THEN 'overdue'
        WHEN CURRENT_DATE > (sr.received_date + ml.sla_day - 2)
            THEN 'at_risk'
        ELSE 'on_track'
    END                                 AS manual_sla_status
FROM public.ai_service_order_summary    v
JOIN public.service_orders              so ON so.id = v.service_order_id
LEFT JOIN public.service_requests       sr ON sr.id = so.service_request_id
LEFT JOIN public.master_laboratory      ml ON ml.id = so.laboratory_id
WHERE v.track = 'UUT'
  AND v.sla_deadline IS NOT NULL
LIMIT 5;
```

**Expected:**
- `view_sla_deadline` = `manual_sla_deadline` for all rows.
- `view_sla_status` = `manual_sla_status` for all rows.
- Zero discrepancies.

---

## Deployment Notes

1. **Apply the view:**
   ```sql
   \i database/views/ai_service_order_summary.sql
   ```

2. **Grant read access to the AI service role** (replace `ai_reader` with the actual role):
   ```sql
   GRANT SELECT ON public.ai_service_order_summary TO ai_reader;
   ```

3. **Revoke direct table access from the AI role** to enforce the view as the only entry point:
   ```sql
   REVOKE ALL ON public.service_orders        FROM ai_reader;
   REVOKE ALL ON public.service_order_uttps   FROM ai_reader;
   REVOKE ALL ON public.service_requests      FROM ai_reader;
   REVOKE ALL ON public.service_request_uttps FROM ai_reader;
   REVOKE ALL ON public.users_customers       FROM ai_reader;
   ```

4. **Refresh after schema changes:** The view is defined with `CREATE OR REPLACE VIEW`. Re-run the definition file after any upstream table DDL change. No `REFRESH` is needed as this is a plain view (not materialized).

5. **Performance:** The correlated subqueries for `inspection_status` will execute once per row. If the view is queried over large result sets without a `WHERE` clause, consider creating a `MATERIALIZED VIEW` variant or adding indexes on `service_order_inspections(order_id)` and `service_order_uttp_inspections(order_id)`.

---

## Limitations and Known Gaps

| Limitation | Detail |
|-----------|--------|
| No global unique key | `service_order_id` is not globally unique; use `(track, service_order_id)` |
| SLA derived only | No stored SLA start/deadline columns exist; computation is correct but depends on `received_date` and `sla_day` being populated |
| `master_uttp_sla` not used | Per the domain analysis (§6), `master_uttp_sla` has no direct join key to order tables (it keys on `kelompok` and `jenis_pengujian`, not on a column available in the order tables). Lab-level `sla_day` is used instead. When `master_laboratory.sla_overide = TRUE`, `sla_day` overrides the `master_uttp_sla` reference — the view reflects this correctly |
| No FK constraints on source tables | All joins are LEFT JOINs; NULL columns indicate missing lookups, not view errors |
| `customer_id` resolves via `requestor_id` only | The `uut_owner_id` / `uttp_owner_id` paths are not used; if a request was created on behalf of an owner without a `requestor_id`, `customer_id` will be NULL |
| Soft-delete filter on service requests only | `deleted_at IS NULL` is applied to `service_requests` and `service_request_uttps`. No `deleted_at` exists on `service_orders` or `service_order_uttps` |
