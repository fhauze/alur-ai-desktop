"""
Fix the ServiceIQ Customer Agent Langflow flow.

Root causes:
1. Only 2 edges exist (ChatInput->Agent, Agent->ChatOutput).
   Missing: OllamaModel->Agent and all 7 Tool->Agent.tools edges.
2. Tool code uses method="run_tool" but node outputs list "build_output" (mismatch).
3. Tool-SIQ13 (get_inspection_status) is missing the component_as_tool output entirely.
4. Bearer token is empty in all tools — needs to load from global variable SERVICEIQ_BEARER_TOKEN.
5. URL construction bug: uses f-string variable reference instead of str.replace correctly.

Fixes applied:
1. Rewrite all 7 tool codes with:
   - Correct Output(method="run_tool") matching the code method
   - bearer_token loaded from Langflow global variable (os.environ or self.variables)
   - Fixed URL construction
   - tool_mode=True on the primary input (order_number / customer_id)
2. Fix node output definitions: output.method = "run_tool" for all tools
3. Add component_as_tool output to Tool-SIQ13
4. Add 8 missing edges (Ollama->Agent.model, 7x Tool.component_as_tool->Agent.tools)
5. PATCH the flow via the Langflow REST API
"""

import copy
import gzip
import json
import sys
import urllib.request
import urllib.error

BASE  = "http://127.0.0.1:7860"
FLOW_ID = open("langflow/flow_id.txt").read().strip()

# ─── Auth ────────────────────────────────────────────────────────────────────

def get_token():
    req = urllib.request.Request(f"{BASE}/api/v1/auto_login", method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]

TOKEN = get_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip",
}


def api(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    h = dict(HEADERS)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            enc = r.headers.get("Content-Encoding", "")
            if enc == "gzip":
                raw = gzip.decompress(raw)
            return r.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
            enc = e.headers.get("Content-Encoding", "")
            if enc == "gzip":
                raw = gzip.decompress(raw)
            err = json.loads(raw.decode("utf-8"))
        except Exception:
            err = {"raw": str(e)}
        return e.code, err


# ─── Load current flow ───────────────────────────────────────────────────────

print(f"Loading flow {FLOW_ID}...")
status, flow = api("GET", f"/api/v1/flows/{FLOW_ID}")
assert status == 200, f"Failed to load flow: {status} {flow}"
print(f"  name: {flow['name']}")
nodes = flow["data"]["nodes"]
edges = flow["data"]["edges"]
print(f"  nodes: {len(nodes)}, edges: {len(edges)}")


# ─── Handle encoding: Langflow stores handles with œ instead of "  ───────────

def make_source_handle(node_id, name, output_types):
    """Build a ReactFlow sourceHandle string using Langflow's œ-quote encoding."""
    data_type = node_id.split("-")[0]
    # Build the JSON-like string with œ instead of "
    parts = [
        f"\u0153dataType\u0153:\u0153{data_type}\u0153",
        f"\u0153id\u0153:\u0153{node_id}\u0153",
        f"\u0153name\u0153:\u0153{name}\u0153",
        f"\u0153output_types\u0153:[" + ",".join(f"\u0153{t}\u0153" for t in output_types) + "]",
    ]
    return "{" + ",".join(parts) + "}"


def make_target_handle(node_id, field_name, input_types, handle_type="other"):
    """Build a ReactFlow targetHandle string using Langflow's œ-quote encoding."""
    input_types_str = "[" + ",".join(f"\u0153{t}\u0153" for t in input_types) + "]"
    parts = [
        f"\u0153fieldName\u0153:\u0153{field_name}\u0153",
        f"\u0153id\u0153:\u0153{node_id}\u0153",
        f"\u0153inputTypes\u0153:{input_types_str}",
        f"\u0153type\u0153:\u0153{handle_type}\u0153",
    ]
    return "{" + ",".join(parts) + "}"


def make_edge(src_id, src_name, src_types, tgt_id, tgt_field, tgt_input_types, tgt_type="other"):
    src_prefix = src_id.split("-")[0]
    edge_id = f"reactflow__edge-{src_id}{make_source_handle(src_id, src_name, src_types)}-{tgt_id}{make_target_handle(tgt_id, tgt_field, tgt_input_types, tgt_type)}"
    return {
        "id": edge_id,
        "source": src_id,
        "target": tgt_id,
        "sourceHandle": make_source_handle(src_id, src_name, src_types),
        "targetHandle": make_target_handle(tgt_id, tgt_field, tgt_input_types, tgt_type),
        "data": {
            "sourceHandle": {
                "dataType": src_prefix,
                "id": src_id,
                "name": src_name,
                "output_types": src_types,
            },
            "targetHandle": {
                "fieldName": tgt_field,
                "id": tgt_id,
                "inputTypes": tgt_input_types,
                "type": tgt_type,
            },
        },
        "type": "default",
    }


# ─── Tool code generator ─────────────────────────────────────────────────────
#
# Key changes vs previous version:
# 1. Output method is "run_tool" (matching the code)
# 2. bearer_token is loaded via os.environ["SERVICEIQ_BEARER_TOKEN"] as fallback
#    The SecretStrInput with load_from_db=True loads the Langflow global variable
# 3. URL construction uses safe string replacement
# 4. order_number/customer_id are tool_mode=True (LLM-supplied)
# ─────────────────────────────────────────────────────────────────────────────

def tool_code(class_name, display_name, description, tool_input_name,
              tool_input_display, tool_input_info, endpoint_path, path_param):
    return "\n".join([
        f'"""ServiceIQ tool: {display_name}"""',
        "from __future__ import annotations",
        "import os",
        "import re",
        "from typing import Any",
        "import httpx",
        "from lfx.custom.custom_component.component import Component",
        "from lfx.io import MessageTextInput, Output, SecretStrInput, StrInput",
        "from lfx.schema.data import Data",
        "",
        "_TIMEOUT = 30",
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
        '            info="JWT Bearer token. Loaded from SERVICEIQ_BEARER_TOKEN global variable.",',
        '            load_from_db=True,',
        "            required=False,",
        "        ),",
        "    ]",
        "",
        "    outputs = [",
        '        Output(display_name="Result", name="output", method="run_tool"),',
        "    ]",
        "",
        "    async def run_tool(self) -> Data:",
        f'        param_value = getattr(self, "{tool_input_name}", "") or ""',
        "        param_value = str(param_value).strip()",
        '        if not param_value or not _SAFE_RE.match(param_value):',
        '            self.status = "Validation error"',
        f'            return Data(data={{"success": False, "error": "Invalid or missing {tool_input_name}."}})',
        "",
        "        # Bearer token: prefer component field, fall back to env var",
        '        token = (getattr(self, "bearer_token", None) or "").strip()',
        '        if not token:',
        '            token = os.environ.get("SERVICEIQ_BEARER_TOKEN", "")',
        '        if not token:',
        '            self.status = "Missing bearer token"',
        '            return Data(data={"success": False, "error": "Bearer token not configured."})',
        "",
        '        base = (getattr(self, "api_base_url", "http://localhost:8000") or "http://localhost:8000").rstrip("/")',
        f'        path = "{endpoint_path}".replace("{{{path_param}}}", param_value)',
        '        url = base + path',
        '        hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json"}',
        "",
        "        try:",
        "            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:",
        "                resp = await client.get(url, headers=hdrs)",
        "        except httpx.TimeoutException:",
        '            self.status = "Timeout"',
        '            return Data(data={"success": False, "error": "Request timed out."})',
        "        except httpx.RequestError as exc:",
        '            self.status = f"Connection error: {type(exc).__name__}"',
        '            return Data(data={"success": False, "error": f"Connection error: {type(exc).__name__}"})',
        "",
        "        if resp.status_code == 200:",
        "            try:",
        "                body: dict[str, Any] = resp.json()",
        '                self.status = "OK"',
        '                return Data(data={"success": True, **body})',
        "            except Exception:",
        '                self.status = "Invalid JSON"',
        '                return Data(data={"success": False, "error": "Invalid JSON response."})',
        "",
        '        self.status = f"HTTP {resp.status_code}"',
        '        return Data(data={"success": False, "error_code": resp.status_code,',
        f'                         "error": f"HTTP {{resp.status_code}}", "{tool_input_name}": param_value}})',
    ])


# ─── Tool definitions (7 required tools) ────────────────────────────────────

TOOLS = {
    "Tool-SIQ10": dict(
        class_name="GetServiceOrderStatusTool",
        display_name="get_service_order_status",
        description="Retrieve order status, inspection result, and SLA compliance by order number.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number e.g. ORD-2024-001.",
        endpoint_path="/api/ai/service-orders/{order_number}",
        path_param="order_number",
    ),
    "Tool-SIQ11": dict(
        class_name="GetServiceOrderTool",
        display_name="get_service_order",
        description="Retrieve full service order details including customer and laboratory info.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to retrieve full details.",
        endpoint_path="/api/ai/service-orders/{order_number}",
        path_param="order_number",
    ),
    "Tool-SIQ12": dict(
        class_name="GetCustomerRequestsTool",
        display_name="get_customer_requests",
        description="List all service requests submitted by a customer.",
        tool_input_name="customer_id", tool_input_display="Customer ID",
        tool_input_info="Customer ID to list all their service requests.",
        endpoint_path="/api/ai/customers/{customer_id}/requests",
        path_param="customer_id",
    ),
    "Tool-SIQ13": dict(
        class_name="GetInspectionStatusTool",
        display_name="get_inspection_status",
        description="Retrieve inspection checklist result (passed/failed/partial/no_inspection) for a service order.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to check inspection result.",
        endpoint_path="/api/ai/service-orders/{order_number}/inspection",
        path_param="order_number",
    ),
    "Tool-SIQ14": dict(
        class_name="GetSLAStatusTool",
        display_name="get_sla_status",
        description="Check SLA compliance of a service order (on_track/at_risk/overdue/closed/no_sla).",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to check SLA status.",
        endpoint_path="/api/ai/service-orders/{order_number}/sla",
        path_param="order_number",
    ),
    "Tool-SIQ15": dict(
        class_name="GetApplicableStandardTool",
        display_name="get_applicable_standard",
        description="Retrieve the applicable calibration or inspection standard for a service order.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to retrieve the applicable standard.",
        endpoint_path="/api/ai/service-orders/{order_number}/standard",
        path_param="order_number",
    ),
    "Tool-SIQ16": dict(
        class_name="GetLaboratoryTool",
        display_name="get_laboratory",
        description="Retrieve laboratory information (name, accreditation, SLA days) for a service order.",
        tool_input_name="order_number", tool_input_display="Order Number",
        tool_input_info="Service order number to retrieve assigned laboratory info.",
        endpoint_path="/api/ai/service-orders/{order_number}/laboratory",
        path_param="order_number",
    ),
}

# Correct output definition for all tool nodes
TOOL_OUTPUT_CORRECT = {
    "output": {
        "allows_loop": False,
        "cache": True,
        "display_name": "Result",
        "group_outputs": False,
        "method": "run_tool",
        "name": "output",
        "selected": "Data",
        "tool_mode": True,
        "types": ["Data"],
        "value": "__UNDEFINED__",
    },
    "component_as_tool": {
        "allows_loop": False,
        "cache": True,
        "display_name": "Toolset",
        "group_outputs": False,
        "method": "to_toolkit",
        "name": "component_as_tool",
        "selected": "Tool",
        "tool_mode": True,
        "types": ["Tool"],
        "value": "__UNDEFINED__",
    },
}


# ─── Apply fixes to each node ────────────────────────────────────────────────

print("\nApplying fixes to tool nodes...")
for node in nodes:
    nid = node["id"]
    if nid not in TOOLS:
        continue

    tdef = TOOLS[nid]
    nd = node["data"]["node"]
    tmpl = nd["template"]

    print(f"  Fixing {nid}: {tdef['display_name']}")

    # 1. Rewrite code
    new_code = tool_code(**tdef)
    tmpl["code"]["value"] = new_code
    nd["edited"] = True

    # 2. Fix outputs: replace with correct output definitions
    nd["outputs"] = [TOOL_OUTPUT_CORRECT["output"], TOOL_OUTPUT_CORRECT["component_as_tool"]]

    # 3. Fix the primary input field definition
    iname = tdef["tool_input_name"]
    # Ensure the input field exists and has tool_mode=True
    if iname in tmpl:
        tmpl[iname]["tool_mode"] = True
        tmpl[iname]["required"] = True
    else:
        tmpl[iname] = {
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

    # 4. Fix bearer_token: load_from_db=True so Langflow reads the global variable
    tmpl["bearer_token"] = {
        "_input_type": "SecretStrInput",
        "advanced": False,
        "display_name": "Bearer Token",
        "dynamic": False,
        "info": "JWT Bearer token. Loaded from SERVICEIQ_BEARER_TOKEN global variable.",
        "list": False,
        "load_from_db": True,
        "name": "bearer_token",
        "required": False,
        "show": True,
        "type": "str",
        "value": "SERVICEIQ_BEARER_TOKEN",  # global variable name
    }

    # 5. Update base_classes to include Tool
    nd["base_classes"] = list({"Data", "Tool"} | set(nd.get("base_classes", [])))
    nd["custom_fields"] = {iname: None}
    nd["field_order"] = [iname, "api_base_url", "bearer_token"]

print("  Tool nodes fixed.")


# ─── Fix edges ────────────────────────────────────────────────────────────────

print("\nBuilding new edge list...")

# Keep existing valid edges (ChatInput->Agent, Agent->ChatOutput)
kept_edges = []
for e in edges:
    src = e.get("source", "")
    tgt = e.get("target", "")
    # Keep the two valid working edges
    if (src == "ChatInput-SIQ01" and tgt == "Agent-SIQ03") or \
       (src == "Agent-SIQ03" and tgt == "ChatOutput-SIQ02"):
        kept_edges.append(e)
        print(f"  Keeping edge: {src} -> {tgt}")

# Add Ollama -> Agent.model
new_edges = kept_edges.copy()
new_edges.append(make_edge(
    "OllamaModel-SIQ04", "model_output", ["LanguageModel"],
    "Agent-SIQ03", "model", ["LanguageModel"], "model"
))
print("  Added: OllamaModel-SIQ04.model_output -> Agent-SIQ03.model")

# Add all 7 tool -> Agent.tools
for tool_id in TOOLS.keys():
    new_edges.append(make_edge(
        tool_id, "component_as_tool", ["Tool"],
        "Agent-SIQ03", "tools", ["Tool"], "other"
    ))
    print(f"  Added: {tool_id}.component_as_tool -> Agent-SIQ03.tools")

print(f"\nTotal edges: {len(new_edges)} (was {len(edges)})")

# ─── Update Agent model field ─────────────────────────────────────────────────

print("\nFixing Agent model field...")
for node in nodes:
    if node["id"] == "Agent-SIQ03":
        tmpl = node["data"]["node"]["template"]
        # Clear the inline model value — the model is now wired via edge
        model_f = tmpl.get("model", {})
        model_f["value"] = ""
        tmpl["model"] = model_f
        print("  Agent model.value cleared (Ollama connected via edge)")
        break


# ─── Assemble and PATCH the flow ─────────────────────────────────────────────

flow["data"]["nodes"] = nodes
flow["data"]["edges"] = new_edges

# Remove fields that should not be PATCHed
patch_payload = {
    "name":        flow["name"],
    "description": flow.get("description", ""),
    "data":        flow["data"],
    "is_component": flow.get("is_component", False),
    "icon":        flow.get("icon", "bot"),
    "icon_bg_color": flow.get("icon_bg_color", "#4F46E5"),
    "tags":        flow.get("tags", []),
}

print(f"\nPATCHing flow {FLOW_ID}...")
status, result = api("PATCH", f"/api/v1/flows/{FLOW_ID}", patch_payload)
print(f"HTTP {status}")

if status in (200, 201):
    # Verify
    nodes_out = result.get("data", {}).get("nodes", [])
    edges_out = result.get("data", {}).get("edges", [])
    print(f"\n✅  Flow patched successfully!")
    print(f"    Nodes : {len(nodes_out)}")
    print(f"    Edges : {len(edges_out)}")
    print(f"\nEdges:")
    for e in edges_out:
        sh = e.get("data", {}).get("sourceHandle", {})
        th = e.get("data", {}).get("targetHandle", {})
        sname = sh.get("name", "?") if isinstance(sh, dict) else "?"
        tname = th.get("fieldName", "?") if isinstance(th, dict) else "?"
        print(f"  {e['source']}.[{sname}] -> {e['target']}.[{tname}]")
else:
    print(f"\n❌  PATCH failed:")
    print(json.dumps(result, indent=2)[:3000])
    sys.exit(1)
