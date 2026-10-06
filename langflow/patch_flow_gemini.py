"""
langflow/patch_flow_gemini.py
------------------------------
Patch the ServiceIQ Customer Agent flow to:
1. Replace OllamaModel node with Google Generative AI (Gemini)
2. Rewire the LLM → Agent edge
3. Update all tool nodes: api_base_url = http://localhost:8000, bearer_token = SERVICEIQ_BEARER_TOKEN
4. Update Agent system prompt
5. Remove OllamaModel node from the flow
"""
from __future__ import annotations
import copy
import json
import sys
import urllib.request

LANGFLOW_URL = "http://localhost:7860"
FLOW_ID = "975f52f6-7883-4543-803c-45bfb9860e72"
GEMINI_NODE_ID = "GeminiModel-SIQ04"
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


def api(method: str, path: str, body: dict | None = None, token: str = "") -> dict:
    url = LANGFLOW_URL + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def handle(data_type: str, node_id: str, name: str, output_types: list[str]) -> str:
    return (
        f"{{{Q}dataType{Q}:{Q}{data_type}{Q},"
        f"{Q}id{Q}:{Q}{node_id}{Q},"
        f"{Q}name{Q}:{Q}{name}{Q},"
        f"{Q}output_types{Q}:[{Q}{Q.join(output_types)}{Q}]}}"
    )


def target_handle(field_name: str, node_id: str, input_types: list[str], type_: str) -> str:
    return (
        f"{{{Q}fieldName{Q}:{Q}{field_name}{Q},"
        f"{Q}id{Q}:{Q}{node_id}{Q},"
        f"{Q}inputTypes{Q}:[{Q}{Q.join(input_types)}{Q}],"
        f"{Q}type{Q}:{Q}{type_}{Q}}}"
    )


def build_gemini_node(gemini_comp: dict, google_api_key_var_id: str) -> dict:
    """Build a Gemini node dict using the component template from /all."""
    template = copy.deepcopy(gemini_comp["template"])

    # Set API key from global variable
    template["api_key"]["value"] = "GOOGLE_API_KEY"
    template["api_key"]["load_from_db"] = True

    # Use gemini-2.5-flash (fast, tool-calling capable)
    template["model_name"]["value"] = "gemini-2.5-flash"
    template["temperature"]["value"] = 0.1
    template["stream"]["value"] = False
    template["tool_model_enabled"]["value"] = True

    node_data = {
        "type": "GoogleGenerativeAIModel",
        "node": {
            "template": template,
            "description": gemini_comp.get("description", ""),
            "icon": gemini_comp.get("icon", "GoogleGenerativeAI"),
            "base_classes": gemini_comp.get("base_classes", ["LanguageModel"]),
            "display_name": "Gemini (gemini-2.5-flash)",
            "documentation": gemini_comp.get("documentation", ""),
            "minimized": False,
            "custom_fields": gemini_comp.get("custom_fields", {}),
            "output_types": gemini_comp.get("output_types", []),
            "pinned": False,
        },
        "id": GEMINI_NODE_ID,
    }

    return {
        "id": GEMINI_NODE_ID,
        "type": "genericNode",
        "position": {"x": 250, "y": 450},
        "data": node_data,
    }


def main() -> None:
    print("=== ServiceIQ Flow Patch: Ollama → Gemini ===")

    token = lf_jwt()
    print(f"JWT obtained: {token[:30]}...")

    # Load current flow
    flow_data = api("GET", f"/api/v1/flows/{FLOW_ID}", token=token)
    print(f"Flow: {flow_data['name']}, nodes={len(flow_data['data']['nodes'])}, edges={len(flow_data['data']['edges'])}")

    # Load all components (for Gemini template)
    print("Loading component templates...")
    req = urllib.request.Request(f"{LANGFLOW_URL}/api/v1/all")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept-Encoding", "gzip, deflate")
    with urllib.request.urlopen(req) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
    if enc == "gzip":
        import gzip
        raw = gzip.decompress(raw)
    all_comps = json.loads(raw)
    gemini_comp = all_comps["google"]["ext:google:GoogleGenerativeAIComponent@official"]
    print("Gemini component loaded ✓")

    nodes: list[dict] = flow_data["data"]["nodes"]
    edges: list[dict] = flow_data["data"]["edges"]

    # ── 1. Remove OllamaModel node ─────────────────────────────────────────────
    old_ollama_id = "OllamaModel-SIQ04"
    nodes = [n for n in nodes if n["id"] != old_ollama_id]
    print(f"Removed {old_ollama_id} ✓")

    # ── 2. Add Gemini node ─────────────────────────────────────────────────────
    gemini_node = build_gemini_node(gemini_comp, "970a59f5-453b-49fa-80ea-a99e1bd12eee")
    nodes.append(gemini_node)
    print(f"Added {GEMINI_NODE_ID} (gemini-2.5-flash) ✓")

    # ── 3. Update Agent node ───────────────────────────────────────────────────
    for n in nodes:
        if n["id"] == "Agent-SIQ03":
            tpl = n["data"]["node"]["template"]
            tpl["system_prompt"]["value"] = SYSTEM_PROMPT
            # Ensure stream = False
            if "stream" in tpl:
                tpl["stream"]["value"] = False
            print("Updated Agent system_prompt ✓")
            break

    # ── 4. Update all tool nodes: api_base_url + bearer_token ─────────────────
    tool_ids = ["Tool-SIQ10", "Tool-SIQ11", "Tool-SIQ12", "Tool-SIQ13", "Tool-SIQ14", "Tool-SIQ15", "Tool-SIQ16"]
    for n in nodes:
        if n["id"] in tool_ids:
            tpl = n["data"]["node"]["template"]
            if "api_base_url" in tpl:
                tpl["api_base_url"]["value"] = "http://localhost:8000"
            if "bearer_token" in tpl:
                tpl["bearer_token"]["value"] = "SERVICEIQ_BEARER_TOKEN"
                tpl["bearer_token"]["load_from_db"] = True
            print(f"  Updated {n['id']} ({n['data']['node'].get('display_name','?')}) api_base_url + bearer_token ✓")

    # ── 5. Replace OllamaModel→Agent edge with Gemini→Agent ───────────────────
    edges = [e for e in edges if e.get("source") != old_ollama_id]
    gemini_to_agent_edge = {
        "id": f"{GEMINI_NODE_ID}-Agent-SIQ03-model",
        "source": GEMINI_NODE_ID,
        "target": "Agent-SIQ03",
        "sourceHandle": handle("GoogleGenerativeAIModel", GEMINI_NODE_ID, "model_output", ["LanguageModel"]),
        "targetHandle": target_handle("model", "Agent-SIQ03", ["LanguageModel"], "model"),
    }
    edges.append(gemini_to_agent_edge)
    print(f"Rewired LLM edge: {GEMINI_NODE_ID} → Agent-SIQ03 ✓")

    print(f"\nFinal: nodes={len(nodes)}, edges={len(edges)}")

    # ── 6. PATCH the flow ──────────────────────────────────────────────────────
    patch_body = {
        "id": FLOW_ID,
        "name": flow_data["name"],
        "description": flow_data.get("description", ""),
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": flow_data["data"].get("viewport", {"zoom": 1, "x": 0, "y": 0}),
        },
        "folder_id": flow_data.get("folder_id"),
    }

    result = api("PATCH", f"/api/v1/flows/{FLOW_ID}", body=patch_body, token=token)
    result_id = result.get("id", "?")
    print(f"\nPATCH result: id={result_id}")
    print("=== Patch complete ✓ ===")


if __name__ == "__main__":
    main()
