-- =============================================================================
-- View: public.ai_service_order_summary
-- Project: ServiceIQ — AI-Powered Enterprise Service Intelligence Platform
-- Purpose: Read-only semantic surface for the AI layer.
--          Unifies the UUT (calibration) and UTTP (field inspection) service
--          order tracks into a single, consistent row set.
--
-- Source tables used:
--   service_orders                  — UUT work-order root (track = 'UUT')
--   service_requests                — UUT service-request root
--   service_order_uttps             — UTTP work-order root (track = 'UTTP')
--   service_request_uttps           — UTTP service-request root
--   users_customers                 — Customer accounts (requestor_id)
--   master_laboratory               — Laboratory reference + SLA config
--   master_service_types            — Service type labels
--   service_order_inspections       — UUT order-level inspection checklist
--   service_order_uttp_inspections  — UTTP order-level inspection checklist
--
-- NOT used (excluded per domain analysis §10–§11):
--   service_order, service_order_bck, service_orders_old
--   service_request_items_o, service_request_item_inspections_o
--   service_request_uttp_items_bck
--   service_order_uttps_des, service_order_uttps_mirror
--   users_customers_1, master_laboratory_backup
--   uttps_20231228_2358, uttps_20240110_0147, uttps_backup
--
-- Referential integrity note:
--   No FK constraints exist on production service-domain tables.
--   All JOINs are LEFT JOINs where the reference cannot be guaranteed,
--   to prevent rows from being silently dropped by orphaned foreign keys.
--
-- SLA note:
--   No sla_started_at or sla_deadline column exists on any order table.
--   sla_deadline is derived:
--     UUT  → service_requests.received_date + master_laboratory.sla_day
--     UTTP → service_request_uttps.received_date + master_laboratory.sla_day
--            (lab-level SLA, since master_uttp_sla has no direct order join key)
--   When laboratory_id is NULL or sla_day is NULL, sla_deadline is NULL.
--
-- Sensitive fields deliberately excluded:
--   password, remember_token, token        (users_customers)
--   ktp, npwp, nib, penanggung_jawab       (users_customers — PII)
--   alamat, phone                          (users_customers — PII)
--   hasil_uji, no_sertifikat               (service order detail — not summary)
--   tool_* columns                         (denormalized instrument snapshot)
--   qrcode_token, qrcode_file              (certificate artifacts)
--   cancel_notes, pending_notes            (free-text operational notes)
--   spuh_*, denda_*                        (billing internals)
--
-- Author: ServiceIQ / AI Layer
-- =============================================================================

CREATE OR REPLACE VIEW public.ai_service_order_summary AS

-- ─────────────────────────────────────────────────────────────────────────────
-- BRANCH 1: UUT track
--   Root tables: service_orders  ←→  service_requests
--   Inspection:  service_order_inspections
--   Laboratory:  master_laboratory
--   Customer:    users_customers  (via service_requests.requestor_id)
--   Service type:master_service_types (via service_requests.service_type_id)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    -- ── Identity ──────────────────────────────────────────────────────────────
    -- service_order_id: Primary key of the work order row in service_orders.
    so.id                                           AS service_order_id,

    -- order_number: Human-readable order number carried on the service request.
    --   service_requests.no_order is the canonical order number for UUT.
    sr.no_order                                     AS order_number,

    -- service_request_id: FK back to the originating service request.
    so.service_request_id                           AS service_request_id,

    -- track: Discriminator — which service track produced this row.
    'UUT'::text                                     AS track,

    -- ── Customer ──────────────────────────────────────────────────────────────
    -- customer_id: Internal ID from users_customers.
    --   Source: service_requests.requestor_id → users_customers.id
    --   No FK constraint; LEFT JOIN used to handle orphaned requestor_id values.
    uc.id                                           AS customer_id,

    -- customer_name: Full name of the requesting customer.
    --   Source: users_customers.full_name
    --   NULL when requestor_id has no matching users_customers row.
    uc.full_name                                    AS customer_name,

    -- ── Service type ──────────────────────────────────────────────────────────
    -- service_type: Human-readable service type label.
    --   Source: master_service_types.service_type
    --   NULL when service_type_id has no match.
    mst.service_type                                AS service_type,

    -- ── Laboratory ────────────────────────────────────────────────────────────
    -- laboratory_id: ID of the assigned laboratory.
    --   Source: service_orders.laboratory_id
    so.laboratory_id                                AS laboratory_id,

    -- laboratory_name: Human-readable lab name.
    --   Source: master_laboratory.nama_lab
    --   NULL when laboratory_id is NULL or unmatched.
    ml.nama_lab                                     AS laboratory_name,

    -- ── Order status ──────────────────────────────────────────────────────────
    -- order_status: Normalised lifecycle status label derived from the
    --   integer status fields on service_orders. Priority order:
    --     cancelled  → cancel_at IS NOT NULL
    --     pending    → pending_status IS NOT NULL AND pending_status > 0
    --     completed  → is_finish = 1
    --     certified  → stat_sertifikat IS NOT NULL AND stat_sertifikat > 0
    --     in_progress→ stat_service_order > 0
    --     new        → stat_service_order = 0 (default)
    CASE
        WHEN so.cancel_at IS NOT NULL                                    THEN 'cancelled'
        WHEN so.pending_status IS NOT NULL AND so.pending_status > 0     THEN 'pending'
        WHEN so.is_finish = 1                                            THEN 'completed'
        WHEN so.stat_sertifikat IS NOT NULL AND so.stat_sertifikat > 0   THEN 'certified'
        WHEN so.stat_service_order IS NOT NULL AND so.stat_service_order > 0 THEN 'in_progress'
        ELSE 'new'
    END                                             AS order_status,

    -- ── Inspection status ─────────────────────────────────────────────────────
    -- inspection_status: Aggregate pass/fail derived from the checklist rows in
    --   service_order_inspections for this order.
    --   Logic:
    --     'no_inspection' → no checklist rows exist for this order
    --     'failed'        → at least one item has is_accepted = false
    --     'passed'        → all items have is_accepted = true
    --     'partial'       → mix of NULL and true (some items not yet evaluated)
    --   Source: correlated subquery on service_order_inspections to avoid
    --           row-multiplication from a direct JOIN on a one-to-many.
    (
        SELECT
            CASE
                WHEN COUNT(*) = 0                            THEN 'no_inspection'
                WHEN COUNT(*) FILTER (WHERE soi.is_accepted = FALSE) > 0 THEN 'failed'
                WHEN COUNT(*) FILTER (WHERE soi.is_accepted IS NULL) > 0 THEN 'partial'
                ELSE 'passed'
            END
        FROM public.service_order_inspections soi
        WHERE soi.order_id = so.id
    )                                               AS inspection_status,

    -- ── SLA ───────────────────────────────────────────────────────────────────
    -- sla_deadline: Computed target completion date.
    --   Formula: service_requests.received_date + master_laboratory.sla_day
    --   NULL when received_date is NULL, laboratory_id is NULL, or sla_day is NULL.
    --   No sla_deadline column exists in any order table; this is always derived.
    CASE
        WHEN sr.received_date IS NOT NULL AND ml.sla_day IS NOT NULL
        THEN sr.received_date + ml.sla_day
        ELSE NULL
    END                                             AS sla_deadline,

    -- sla_status: Current SLA compliance state relative to today.
    --   'no_sla'    → sla_deadline cannot be computed (missing inputs)
    --   'overdue'   → order not completed, today is past the deadline
    --   'at_risk'   → order not completed, within 2 days of deadline
    --   'on_track'  → order not completed, more than 2 days remain
    --   'closed'    → order completed (is_finish = 1), SLA no longer applies
    CASE
        WHEN sr.received_date IS NULL OR ml.sla_day IS NULL             THEN 'no_sla'
        WHEN so.is_finish = 1 OR so.cancel_at IS NOT NULL               THEN 'closed'
        WHEN CURRENT_DATE > (sr.received_date + ml.sla_day)             THEN 'overdue'
        WHEN CURRENT_DATE > (sr.received_date + ml.sla_day - 2)         THEN 'at_risk'
        ELSE 'on_track'
    END                                             AS sla_status

FROM public.service_orders         so

-- service_requests: parent service request for this UUT order.
-- LEFT JOIN: service_orders.service_request_id has no FK constraint;
--            a missing request must not drop the order row.
LEFT JOIN public.service_requests  sr
    ON sr.id = so.service_request_id
   AND sr.deleted_at IS NULL

-- users_customers: the customer who submitted the request.
-- LEFT JOIN: requestor_id has no FK constraint; customer may be missing.
LEFT JOIN public.users_customers   uc
    ON uc.id = sr.requestor_id

-- master_service_types: human-readable service type.
-- LEFT JOIN: service_type_id has no FK constraint.
LEFT JOIN public.master_service_types mst
    ON mst.id = sr.service_type_id

-- master_laboratory: laboratory name + SLA days.
-- LEFT JOIN: laboratory_id has no FK constraint; orders may be unassigned.
LEFT JOIN public.master_laboratory ml
    ON ml.id = so.laboratory_id

UNION ALL

-- ─────────────────────────────────────────────────────────────────────────────
-- BRANCH 2: UTTP track
--   Root tables: service_order_uttps  ←→  service_request_uttps
--   Inspection:  service_order_uttp_inspections
--   Laboratory:  master_laboratory
--   Customer:    users_customers  (via service_request_uttps.requestor_id)
--   Service type:master_service_types (via service_request_uttps.service_type_id)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    -- ── Identity ──────────────────────────────────────────────────────────────
    sou.id                                          AS service_order_id,
    sru.no_order                                    AS order_number,
    sou.service_request_id                          AS service_request_id,
    'UTTP'::text                                    AS track,

    -- ── Customer ──────────────────────────────────────────────────────────────
    uc.id                                           AS customer_id,
    uc.full_name                                    AS customer_name,

    -- ── Service type ──────────────────────────────────────────────────────────
    mst.service_type                                AS service_type,

    -- ── Laboratory ────────────────────────────────────────────────────────────
    sou.laboratory_id                               AS laboratory_id,
    ml.nama_lab                                     AS laboratory_name,

    -- ── Order status ──────────────────────────────────────────────────────────
    -- Same priority logic as UUT branch, applied to service_order_uttps columns.
    -- service_order_uttps has is_nonaktif (deactivated/superseded by revision);
    -- treated as cancelled at the view level.
    CASE
        WHEN sou.cancel_at IS NOT NULL                                     THEN 'cancelled'
        WHEN sou.is_nonaktif = TRUE                                        THEN 'cancelled'
        WHEN sou.pending_status IS NOT NULL AND sou.pending_status > 0     THEN 'pending'
        WHEN sou.is_finish = 1                                             THEN 'completed'
        WHEN sou.stat_sertifikat IS NOT NULL AND sou.stat_sertifikat > 0   THEN 'certified'
        WHEN sou.stat_service_order IS NOT NULL AND sou.stat_service_order > 0 THEN 'in_progress'
        ELSE 'new'
    END                                             AS order_status,

    -- ── Inspection status ─────────────────────────────────────────────────────
    -- Correlated subquery on service_order_uttp_inspections.
    (
        SELECT
            CASE
                WHEN COUNT(*) = 0                                          THEN 'no_inspection'
                WHEN COUNT(*) FILTER (WHERE soui.is_accepted = FALSE) > 0 THEN 'failed'
                WHEN COUNT(*) FILTER (WHERE soui.is_accepted IS NULL) > 0 THEN 'partial'
                ELSE 'passed'
            END
        FROM public.service_order_uttp_inspections soui
        WHERE soui.order_id = sou.id
    )                                               AS inspection_status,

    -- ── SLA ───────────────────────────────────────────────────────────────────
    -- UTTP: received_date from service_request_uttps, sla_day from master_laboratory.
    CASE
        WHEN sru.received_date IS NOT NULL AND ml.sla_day IS NOT NULL
        THEN sru.received_date + ml.sla_day
        ELSE NULL
    END                                             AS sla_deadline,

    CASE
        WHEN sru.received_date IS NULL OR ml.sla_day IS NULL              THEN 'no_sla'
        WHEN sou.is_finish = 1 OR sou.cancel_at IS NOT NULL
             OR sou.is_nonaktif = TRUE                                     THEN 'closed'
        WHEN CURRENT_DATE > (sru.received_date + ml.sla_day)              THEN 'overdue'
        WHEN CURRENT_DATE > (sru.received_date + ml.sla_day - 2)          THEN 'at_risk'
        ELSE 'on_track'
    END                                             AS sla_status

FROM public.service_order_uttps       sou

-- service_request_uttps: parent UTTP service request.
-- LEFT JOIN: no FK constraint between service_order_uttps.service_request_id
--            and service_request_uttps.id.
LEFT JOIN public.service_request_uttps sru
    ON sru.id = sou.service_request_id
   AND sru.deleted_at IS NULL

-- users_customers: customer who submitted the UTTP request.
LEFT JOIN public.users_customers       uc
    ON uc.id = sru.requestor_id

-- master_service_types: service type label.
LEFT JOIN public.master_service_types  mst
    ON mst.id = sru.service_type_id

-- master_laboratory: lab name + SLA days.
LEFT JOIN public.master_laboratory     ml
    ON ml.id = sou.laboratory_id;

-- =============================================================================
-- Post-creation comment (run separately if desired):
-- COMMENT ON VIEW public.ai_service_order_summary IS
--   'Read-only semantic view for the ServiceIQ AI layer. Unifies UUT and UTTP
--    service order tracks. No transactional tables are modified. See
--    docs/database/ai-service-order-summary.md for full documentation.';
-- =============================================================================
