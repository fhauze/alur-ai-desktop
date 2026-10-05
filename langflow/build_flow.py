"""
Build the ServiceIQ Customer Agent Langflow flow.
Uses full component source code extracted from the Langflow component registry.
"""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:7860"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1MTBjZmM4Yi05ZjFiLTQzNjktODZlOC05Y2JhMGQ0Y2FjNTUiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzkxMTczNDcxfQ.ZunI0o5T_anY2W_YB1PIXeWtP58qAuV29Qaf9BQxNaA"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def api(method, path, body=None):
    import gzip
    import zlib
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    h = dict(HEADERS)
    h["Accept-Encoding"] = "gzip"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc in ("deflate", "zlib"):
                raw = zlib.decompress(raw)
            return r.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
        except Exception:
            err = {"raw": str(e)}
        return e.code, err


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Fetch component codes from a known working flow (Simple Agent)
#         and from the /all registry
# ─────────────────────────────────────────────────────────────────────────────

print("Fetching component templates from Langflow...")
status, all_components = api("GET", "/api/v1/all")
assert status == 200, f"Failed to fetch /all: {status}"

status, flows_list = api("GET", "/api/v1/flows/?page=1&size=50")
assert status == 200, f"Failed to fetch flows: {status}"

# Extract codes from Simple Agent reference flow
CODES = {}
for flow in flows_list:
    if flow.get("name") == "Simple Agent":
        for node in flow.get("data", {}).get("nodes", []):
            nd = node.get("data", {})
            ntype = nd.get("type", "")
            code_val = nd.get("node", {}).get("template", {}).get("code", {}).get("value", "")
            if code_val and ntype and ntype != "note":
                CODES[ntype] = code_val
        break

# Get Ollama code from /all
ollama_key = "ext:ollama:ChatOllamaComponent@official"
CODES["OllamaModel"] = (
    all_components.get("ollama", {})
    .get(ollama_key, {})
    .get("template", {})
    .get("code", {})
    .get("value", "")
)

print(f"Loaded codes: {', '.join(f'{k}({len(v)}ch)' for k,v in CODES.items())}")
assert CODES.get("Agent"), "Could not load Agent code"
assert CODES.get("ChatInput"), "Could not load ChatInput code"
assert CODES.get("ChatOutput"), "Could not load ChatOutput code"
assert CODES.get("OllamaModel"), "Could not load OllamaModel code"


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Tool code generator — one CustomComponent per tool
# ─────────────────────────────────────────────────────────────────────────────

def tool_code(class_name, display_name, description, tool_input_name,
              tool_input_display, tool_input_info, endpoint_path, path_param):
    lines = [
        f'"""ServiceIQ tool: {display_name}"""',
        "from __future__ import annotations",
        "import json",
        "import re",
        "from typing import Any",
        "import httpx",
        "from lfx.custom.custom_component.component import Component",
        "from lfx.io import MessageTextInput, Output, SecretStrInput, StrInput",
        "from lfx.schema.data import Data",
        "",
        "_TIMEOUT = 15",
        r'_SAFE_RE = re.compile(r"^[\x20-\x7E]{1,200}$")',
        "",
        "",
        f"class {class_name}(Component):",
        f'    display_name = "{display_name}"',
        f'    description = "{description}"',
        '    icon = "ClipboardList"',
        f'    name = "{class_name}"',
        "",
        "    inputs = [",
        "        MessageTextInput(",
        f'            name="{tool_input_name}",',
        f'            display_name="{tool_input_display}",',
        f'            info="{tool_input_info}",',
        "            tool_mode=True,",
        "            required=True,",
        "        ),",
        "        StrInput(",
        '            name="api_base_url",',
        '            display_name="API Base URL",',
        '            info="Base URL of the ServiceIQ AI API.",',
        '            value="http://localhost:8000",',
        "            advanced=True,",
        "            required=True,",
        "        ),",
        "        SecretStrInput(",
        '            name="bearer_token",',
        '            display_name="Bearer Token",',
        '            info="JWT Bearer token. Store in Langflow secret store.",',
        "            required=True,",
        "        ),",
        "    ]",
        "",
        "    outputs = [",
        '        Output(display_name="Result", name="output", method="run_tool"),',
        "    ]",
        "",
        "    async def run_tool(self) -> Data:",
        f'        param_value = getattr(self, "{tool_input_name}", "")',
        '        if not param_value or not _SAFE_RE.match(str(param_value).strip()):',
        '            self.status = "Validation error"',
        f'            return Data(data={{"success": False, "error": "Invalid or missing {tool_input_name}."}})',
        '        base = self.api_base_url.rstrip("/")',
        f'        url = f"{{base}}{endpoint_path}".replace("{{{path_param}}}", str(param_value).strip())',
        '        hdrs = {"Authorization": f"Bearer {self.bearer_token}", "Accept": "application/json"}',
        "        try:",
        "            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:",
        "                resp = await client.get(url, headers=hdrs)",
        "        except httpx.TimeoutException:",
        '            self.status = "Timeout"',
        '            return Data(data={"success": False, "error": "Request timed out."})',
        "        except httpx.RequestError as exc:",
        '            self.status = f"Connection error: {type(exc).__name__}"',
        '            return Data(data={"success": False, "error": f"Connection error: {type(exc).__name__}"})',
        "        if resp.status_code == 200:",
        "            try:",
        "                body: dict[str, Any] = resp.json()",
        '                self.status = "OK"',
        '                return Data(data={"success": True, **body})',
        "            except Exception:",
        '                self.status = "Invalid JSON"',
        '                return Data(data={"success": False, "error": "Invalid JSON response."})',
        '        self.status = f"HTTP {resp.status_code}"',
        '        return Data(data={"success": False, "error_code": resp.status_code, "error": f"HTTP {resp.status_code}"})',
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    dict(
        class_name="GetServiceOrderStatusTool",
        display_name="get_service_order_status",
        description="Retrieve order status, inspection result, and SLA compliance by order number.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number e.g. ORD-2024-001.",
        endpoint_path="/api/ai/service-orders/{order_number}",
        path_param="order_number",
    ),
    dict(
        class_name="GetServiceOrderTool",
        display_name="get_service_order",
        description="Retrieve full service order details including customer and laboratory info.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to retrieve full details.",
        endpoint_path="/api/ai/service-orders/{order_number}",
        path_param="order_number",
    ),
    dict(
        class_name="GetCustomerRequestsTool",
        display_name="get_customer_requests",
        description="List all service requests submitted by a customer.",
        tool_input_name="customer_id", tool_input_display="Customer ID",
        tool_input_info="Customer ID to list all their service requests.",
        endpoint_path="/api/ai/customers/{customer_id}/requests",
        path_param="customer_id",
    ),
    dict(
        class_name="GetInspectionStatusTool",
        display_name="get_inspection_status",
        description="Retrieve inspection checklist result (passed/failed/partial/no_inspection) for a service order.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to check inspection result.",
        endpoint_path="/api/ai/service-orders/{order_number}/inspection",
        path_param="order_number",
    ),
    dict(
        class_name="GetSLAStatusTool",
        display_name="get_sla_status",
        description="Check SLA compliance of a service order (on_track/at_risk/overdue/closed/no_sla).",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to check SLA status.",
        endpoint_path="/api/ai/service-orders/{order_number}/sla",
        path_param="order_number",
    ),
    dict(
        class_name="GetApplicableStandardTool",
        display_name="get_applicable_standard",
        description="Retrieve the applicable calibration or inspection standard for a service order.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to retrieve the applicable standard.",
        endpoint_path="/api/ai/service-orders/{order_number}/standard",
        path_param="order_number",
    ),
    dict(
        class_name="GetLaboratoryTool",
        display_name="get_laboratory",
        description="Retrieve laboratory information (name, accreditation, SLA days) for a service order.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to retrieve assigned laboratory info.",
        endpoint_path="/api/ai/service-orders/{order_number}/laboratory",
        path_param="order_number",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Node IDs and layout
# ─────────────────────────────────────────────────────────────────────────────

CHAT_IN_ID  = "ChatInput-SIQ01"
CHAT_OUT_ID = "ChatOutput-SIQ02"
AGENT_ID    = "Agent-SIQ03"
OLLAMA_ID   = "OllamaModel-SIQ04"
TOOL_IDS    = [f"Tool-SIQ{10+i:02d}" for i in range(len(TOOLS))]


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Build nodes using templates from Simple Agent reference flow
# ─────────────────────────────────────────────────────────────────────────────

def get_ref_node(flows_list, flow_name, node_type):
    for flow in flows_list:
        if flow.get("name") == flow_name:
            for node in flow.get("data", {}).get("nodes", []):
                if node.get("data", {}).get("type") == node_type:
                    return node
    return None


def clone_node(ref_node, new_id, new_pos, overrides=None):
    """Deep-clone a reference node, replacing id and position, with optional template overrides."""
    import copy
    node = copy.deepcopy(ref_node)
    node["id"] = new_id
    node["position"] = new_pos
    node["data"]["id"] = new_id
    node["data"]["node"]["minimized"] = False
    if overrides:
        for key, val in overrides.items():
            if key == "display_name":
                node["data"]["node"]["display_name"] = val
            elif key == "system_prompt":
                tmpl = node["data"]["node"]["template"]
                if "system_prompt" in tmpl:
                    tmpl["system_prompt"]["value"] = val
    return node


# ChatInput node
ci_ref = get_ref_node(flows_list, "Simple Agent", "ChatInput")
chat_in = clone_node(ci_ref, CHAT_IN_ID, {"x": 200, "y": 600})

# ChatOutput node
co_ref = get_ref_node(flows_list, "Simple Agent", "ChatOutput")
chat_out = clone_node(co_ref, CHAT_OUT_ID, {"x": 1800, "y": 600})

# Agent node — clone and set the system prompt
agent_ref = get_ref_node(flows_list, "Simple Agent", "Agent")

SYSTEM_PROMPT = (
    "Anda adalah ServiceIQ Customer Service Agent — asisten cerdas untuk platform layanan metrologi.\n\n"
    "Anda membantu pelanggan mendapatkan informasi tentang:\n"
    "- Status order layanan (gunakan get_service_order_status)\n"
    "- Status permintaan layanan (gunakan get_customer_requests)\n"
    "- Status inspeksi (gunakan get_inspection_status)\n"
    "- Kepatuhan SLA (gunakan get_sla_status)\n"
    "- Standar yang berlaku (gunakan get_applicable_standard)\n"
    "- Informasi laboratorium (gunakan get_laboratory)\n\n"
    "ATURAN PENTING:\n"
    "1. Selalu gunakan tools yang tersedia untuk data nyata. JANGAN mengarang atau menduga data.\n"
    "2. Jangan pernah mengakses database secara langsung.\n"
    "3. Jangan pernah membagikan data pelanggan lain.\n"
    "4. Jika order tidak ditemukan, sampaikan dengan sopan.\n"
    "5. Jawab dalam bahasa yang sama dengan pertanyaan (Indonesia atau Inggris).\n"
    "6. Jika pelanggan tidak memberikan nomor order, tanya dengan sopan sebelum memanggil tool.\n"
    "7. Jangan pernah membuat SQL atau mengakses database langsung.\n\n"
    "Untuk pertanyaan tentang 'status order saya' -> tanya nomor order, lalu gunakan get_service_order_status.\n"
    "Untuk pertanyaan tentang 'kenapa belum selesai' -> gunakan get_service_order_status dan get_inspection_status.\n"
    "Untuk pertanyaan tentang 'apakah sesuai SLA' -> gunakan get_sla_status.\n"
    "Untuk pertanyaan tentang 'standar yang digunakan' -> gunakan get_applicable_standard."
)

agent = clone_node(agent_ref, AGENT_ID, {"x": 1000, "y": 600},
                   overrides={"display_name": "ServiceIQ Agent", "system_prompt": SYSTEM_PROMPT})

# Remove existing tool connections in the agent template (tools list should be empty at node level)
agent["data"]["node"]["template"]["tools"]["value"] = ""

# Ollama node — build from /all registry template
import copy

ollama_tpl = all_components["ollama"][ollama_key]
ollama = {
    "id": OLLAMA_ID,
    "type": "genericNode",
    "position": {"x": 1000, "y": 100},
    "data": {
        "id": OLLAMA_ID,
        "type": "OllamaModel",
        "node": copy.deepcopy(ollama_tpl),
    }
}
# Set model name
ollama["data"]["node"]["template"]["model_name"]["value"] = "mistral:latest"
ollama["data"]["node"]["template"]["model_name"]["options"] = ["mistral:latest"]
ollama["data"]["node"]["template"]["tool_model_enabled"]["value"] = True
ollama["data"]["node"]["display_name"] = "Ollama (mistral)"
ollama["data"]["node"]["minimized"] = False


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Build tool nodes (CustomComponent)
# ─────────────────────────────────────────────────────────────────────────────

# We need the CustomComponent template from /all
cc_tpl = all_components["custom_component"]["CustomComponent"]

def make_tool_node(tdef, nid, x, y):
    code = tool_code(**tdef)
    iname = tdef["tool_input_name"]
    node = copy.deepcopy(cc_tpl)
    node["display_name"] = tdef["display_name"]
    node["description"] = tdef["description"]
    node["edited"] = True
    node["minimized"] = False
    # Set code
    node["template"]["code"]["value"] = code
    # Replace default input with the tool-specific input
    node["template"].pop("input_value", None)
    node["template"][iname] = {
        "_input_type": "MessageTextInput",
        "advanced": False,
        "display_name": tdef["tool_input_display"],
        "dynamic": False,
        "info": tdef["tool_input_info"],
        "input_types": ["Message"],
        "list": False,
        "name": iname,
        "required": True,
        "show": True,
        "tool_mode": True,
        "type": "str",
        "value": "",
    }
    node["template"]["api_base_url"] = {
        "_input_type": "StrInput",
        "advanced": True,
        "display_name": "API Base URL",
        "dynamic": False,
        "info": "Base URL of the ServiceIQ AI API.",
        "list": False,
        "name": "api_base_url",
        "required": True,
        "show": True,
        "type": "str",
        "value": "http://localhost:8000",
    }
    node["template"]["bearer_token"] = {
        "_input_type": "SecretStrInput",
        "advanced": False,
        "display_name": "Bearer Token",
        "dynamic": False,
        "info": "JWT Bearer token for ServiceIQ API.",
        "list": False,
        "load_from_db": False,
        "name": "bearer_token",
        "required": True,
        "show": True,
        "type": "str",
        "value": "",
    }
    # Add component_as_tool output
    existing_outputs = node.get("outputs", [])
    has_tool_output = any(o.get("name") == "component_as_tool" for o in existing_outputs)
    if not has_tool_output:
        node["outputs"] = existing_outputs + [{
            "allows_loop": False,
            "cache": True,
            "display_name": "Component as Tool",
            "group_outputs": False,
            "method": "to_toolkit",
            "name": "component_as_tool",
            "selected": "Tool",
            "tool_mode": False,
            "types": ["Tool"],
            "value": "__UNDEFINED__",
        }]
    node["base_classes"] = list(set(node.get("base_classes", ["Data"]) + ["Tool"]))
    node["custom_fields"] = {iname: None}
    node["field_order"] = [iname, "api_base_url", "bearer_token"]

    return {
        "id": nid,
        "type": "genericNode",
        "position": {"x": x, "y": y},
        "data": {"id": nid, "type": "CustomComponent", "node": node},
    }


# Layout: 2 rows × 4 cols
COLS = 4
X_TOOL_START = -1400
X_TOOL_GAP = 450
Y_TOOL_ROWS = [80, 480]

tool_nodes = []
for i, (tdef, nid) in enumerate(zip(TOOLS, TOOL_IDS)):
    row = i // COLS
    col = i % COLS
    x = X_TOOL_START + col * X_TOOL_GAP
    y = Y_TOOL_ROWS[row] if row < len(Y_TOOL_ROWS) else Y_TOOL_ROWS[-1] + (row - len(Y_TOOL_ROWS) + 1) * 400
    tool_nodes.append(make_tool_node(tdef, nid, x, y))


# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Build edges
# ─────────────────────────────────────────────────────────────────────────────

def make_edge(src, src_name, src_types, tgt, tgt_field, tgt_input_types, tgt_type="other"):
    src_prefix = src.split("-")[0]
    return {
        "id": f"{src}-{tgt}-{src_name}",
        "source": src, "target": tgt,
        "sourceHandle": json.dumps({
            "dataType": src_prefix, "id": src, "name": src_name, "output_types": src_types,
        }),
        "targetHandle": json.dumps({
            "fieldName": tgt_field, "id": tgt, "inputTypes": tgt_input_types, "type": tgt_type,
        }),
        "data": {
            "sourceHandle": {"dataType": src_prefix, "id": src, "name": src_name, "output_types": src_types},
            "targetHandle": {"fieldName": tgt_field, "id": tgt, "inputTypes": tgt_input_types, "type": tgt_type},
        },
        "type": "default",
    }


edges = [
    make_edge(CHAT_IN_ID, "message", ["Message"], AGENT_ID, "input_value", ["Message"], "str"),
    make_edge(OLLAMA_ID, "model_output", ["LanguageModel"], AGENT_ID, "model", ["LanguageModel"], "model"),
    make_edge(AGENT_ID, "response", ["Message"], CHAT_OUT_ID, "input_value",
              ["Data", "JSON", "DataFrame", "Table", "Message"], "other"),
]
for nid in TOOL_IDS:
    edges.append(make_edge(nid, "component_as_tool", ["Tool"], AGENT_ID, "tools", ["Tool"], "other"))


# ─────────────────────────────────────────────────────────────────────────────
# Step 8: POST the flow
# ─────────────────────────────────────────────────────────────────────────────

all_nodes = [chat_in, agent, chat_out, ollama] + tool_nodes

flow = {
    "name": "ServiceIQ Customer Agent",
    "description": (
        "AI-powered customer service agent for the ServiceIQ metrological service platform. "
        "Handles service order status, inspection results, SLA compliance, applicable standards, "
        "and laboratory information. Uses backend API tools only — no direct database access."
    ),
    "is_component": False,
    "icon": "bot",
    "icon_bg_color": "#4F46E5",
    "tags": ["serviceiq", "customer-service", "ai-agent"],
    "data": {
        "nodes": all_nodes,
        "edges": edges,
        "viewport": {"zoom": 0.65, "x": 600, "y": 200},
    },
}

print(f"\nCreating flow with {len(all_nodes)} nodes and {len(edges)} edges...")
status, result = api("POST", "/api/v1/flows/", flow)
print(f"HTTP {status}")

if status in (200, 201):
    flow_id = result.get("id")
    print(f"\n✅  Flow created successfully!")
    print(f"    ID    : {flow_id}")
    print(f"    Name  : {result.get('name')}")
    print(f"    Nodes : {len(all_nodes)}")
    print(f"    Edges : {len(edges)}")
    print(f"    URL   : {BASE}/flow/{flow_id}")
    with open("langflow/flow_id.txt", "w") as fh:
        fh.write(flow_id)
    print(f"\n    Flow ID saved to langflow/flow_id.txt")
else:
    print(f"\n❌  Error creating flow:")
    print(json.dumps(result, indent=2)[:3000])
    sys.exit(1)
