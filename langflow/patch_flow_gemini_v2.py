"""
langflow/patch_flow_gemini_v2.py
---------------------------------
Patch the ServiceIQ flow to use the Agent's built-in Gemini model dropdown
instead of an external LLM node. This avoids node structure complexity.

Changes:
1. Remove OllamaModel-SIQ04 node (already done in v1 patch, may need to redo)
2. Remove GeminiModel-SIQ04 node (added in v1 but broken)
3. Set Agent-SIQ03 model = gemini-2.5-flash-lite (stable, fast, tool-calling)
4. Set Agent-SIQ03 api_key = GOOGLE_API_KEY (from global variable)
5. Remove all LLM→Agent edges (model input now comes from the dropdown)
6. Re-add edges: ChatInput→Agent, Agent→ChatOutput, all 7 Tools→Agent
7. Update system prompt + all tool api_base_url
"""
from __future__ import annotations
import json
import urllib.request
import gzip as _gzip

LANGFLOW_URL = "http://localhost:7860"
FLOW_ID = "975f52f6-7883-4543-803c-45bfb9860e72"
Q = "\u0153"  # œ — Langflow handle quote character

SYSTEM_PROMPT = """You are ServiceIQ, an enterprise service intelligence assistant for a metrology laboratory service platform.

Answer questions using authorized enterprise service data ONLY. Never invent, guess, or fabricate data.

TOOL USAGE RULES:
1. For any question about a specific service order → extract the order number → call get_service_order_status
2. For detailed order info → call get_service_order
3. For inspection questions → call get_inspection_status
4. For SLA questions → call get_sla_status
5. For standards questions → call get_applicable_standard
6. For laboratory info → call get_laboratory
7. For customer requests → call get_customer_requests

CRITICAL:
- ALWAYS call the appropriate tool — never describe what you would do, just do it
- Never ask the user for credentials or tokens
- Never generate SQL
- If an order is not found, clearly state it was not found
- Answer in the same language as the user (Indonesian or English)
- Order numbers in this system look like: V-XXXX-XX-XXX or DL-25-XXX (NOT ORD- prefix)

EXAMPLE:
User: "Bagaimana status order V-6747-09-000?"
→ You MUST call: get_service_order_status with order_number="V-6747-09-000"
→ Then answer based ONLY on the returned data"""


def lf_jwt() -> str:
    req = urllib.request.Request(f"{LANGFLOW_URL}/api/v1/auto_login")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]


def api_get(path: str, token: str) -> dict:
    req = urllib.request.Request(LANGFLOW_URL + path)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
    if "gzip" in enc:
        raw = _gzip.decompress(raw)
    return json.loads(raw)


def api_patch(path: str, body: dict, token: str) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(LANGFLOW_URL + path, data=data, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
    if "gzip" in enc:
        raw = _gzip.decompress(raw)
    return json.loads(raw)


def edge(src_id: str, src_type: str, src_name: str, src_out_types: list[str],
         tgt_id: str, tgt_field: str, tgt_in_types: list[str], tgt_type: str) -> dict:
    sh = (f"{{{Q}dataType{Q}:{Q}{src_type}{Q},{Q}id{Q}:{Q}{src_id}{Q},"
          f"{Q}name{Q}:{Q}{src_name}{Q},{Q}output_types{Q}:[{Q}{Q.join(src_out_types)}{Q}]}}")
    th = (f"{{{Q}fieldName{Q}:{Q}{tgt_field}{Q},{Q}id{Q}:{Q}{tgt_id}{Q},"
          f"{Q}inputTypes{Q}:[{Q}{Q.join(tgt_in_types)}{Q}],{Q}type{Q}:{Q}{tgt_type}{Q}}}")
    return {
        "id": f"{src_id}-{tgt_id}-{tgt_field}",
        "source": src_id,
        "target": tgt_id,
        "sourceHandle": sh,
        "targetHandle": th,
    }


def main() -> None:
    print("=== ServiceIQ Flow Patch v2: Agent built-in Gemini ===")

    token = lf_jwt()
    print(f"JWT: {token[:30]}...")

    flow = api_get(f"/api/v1/flows/{FLOW_ID}", token)
    print(f"Flow: {flow['name']}, nodes={len(flow['data']['nodes'])}, edges={len(flow['data']['edges'])}")

    nodes: list[dict] = flow["data"]["nodes"]
    edges: list[dict] = flow["data"]["edges"]

    # ── 1. Remove OllamaModel and any broken Gemini external nodes ─────────────
    removed_ids = {"OllamaModel-SIQ04", "GeminiModel-SIQ04"}
    nodes = [n for n in nodes if n["id"] not in removed_ids]
    print(f"Removed external LLM nodes: {removed_ids} ✓")

    # ── 2. Update Agent: set model dropdown + api_key ─────────────────────────
    for n in nodes:
        if n["id"] == "Agent-SIQ03":
            tpl = n["data"]["node"]["template"]

            # Set model via the built-in dropdown
            # gemini-3.6-flash is in the Langflow dropdown and was originally selected
            gemini_option = {
                "name": "gemini-3.6-flash",
                "icon": "GoogleGenerativeAI",
                "category": "Google Generative AI",
                "provider": "Google Generative AI",
                "metadata": {
                    "context_length": 1000000,
                    "model_class": "ChatGoogleGenerativeAIFixed",
                    "model_name_param": "model",
                    "api_key_param": "google_api_key",
                    "max_tokens_field_name": "max_output_tokens",
                    "reasoning": False,
                    "reasoning_models": []
                }
            }
            tpl["model"]["value"] = [gemini_option]

            # Set API key from global variable
            tpl["api_key"]["value"] = "GOOGLE_API_KEY"
            tpl["api_key"]["load_from_db"] = True

            # Update system prompt
            tpl["system_prompt"]["value"] = SYSTEM_PROMPT

            # Ensure stream = False
            if "stream" in tpl:
                tpl["stream"]["value"] = False

            # max_iterations = 5 (reduce for faster testing)
            if "max_iterations" in tpl:
                tpl["max_iterations"]["value"] = 5

            print("Updated Agent-SIQ03: model=gemini-2.5-flash-lite, api_key from GOOGLE_API_KEY ✓")
            break

    # ── 3. Update all tool nodes: api_base_url + bearer_token ─────────────────
    tool_ids = ["Tool-SIQ10", "Tool-SIQ11", "Tool-SIQ12",
                "Tool-SIQ13", "Tool-SIQ14", "Tool-SIQ15", "Tool-SIQ16"]
    for n in nodes:
        if n["id"] in tool_ids:
            tpl = n["data"]["node"]["template"]
            if "api_base_url" in tpl:
                tpl["api_base_url"]["value"] = "http://localhost:8000"
            if "bearer_token" in tpl:
                tpl["bearer_token"]["value"] = "SERVICEIQ_BEARER_TOKEN"
                tpl["bearer_token"]["load_from_db"] = True
            dn = n["data"]["node"].get("display_name", n["id"])
            print(f"  Updated {n['id']} ({dn}) ✓")

    # ── 4. Rebuild edges (remove LLM→Agent, keep the rest) ────────────────────
    # Keep all non-LLM edges
    edges = [e for e in edges if e.get("source") not in removed_ids and e.get("target") not in removed_ids]
    print(f"Remaining edges after LLM removal: {len(edges)}")

    # Print remaining edges
    for e in edges:
        print(f"  {e['source']} → {e['target']}")

    # ── 5. PATCH the flow ──────────────────────────────────────────────────────
    patch_body = {
        "id": FLOW_ID,
        "name": flow["name"],
        "description": flow.get("description", ""),
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": flow["data"].get("viewport", {"zoom": 1, "x": 0, "y": 0}),
        },
        "folder_id": flow.get("folder_id"),
    }

    result = api_patch(f"/api/v1/flows/{FLOW_ID}", patch_body, token)
    print(f"\nPATCH result: id={result.get('id','?')}")
    print(f"Final: nodes={len(result['data']['nodes'])}, edges={len(result['data']['edges'])}")
    print("=== Patch v2 complete ✓ ===")


if __name__ == "__main__":
    main()
