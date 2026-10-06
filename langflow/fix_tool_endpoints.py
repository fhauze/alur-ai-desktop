"""
langflow/fix_tool_endpoints.py
--------------------------------
Fix all ServiceIQ tool nodes to use the single existing backend endpoint:
  GET /api/ai/service-orders/{order_number}

Tools SIQ11-SIQ16 were pointing to sub-paths (/inspection, /sla, /standard, etc.)
that don't exist. This fix routes all tools through the one real endpoint and
filters the response data to match each tool's specific purpose.
"""
from __future__ import annotations
import json
import urllib.request
import gzip as _gzip

LANGFLOW_URL = "http://localhost:7860"
FLOW_ID = "975f52f6-7883-4543-803c-45bfb9860e72"

# Tool definitions: id, class_name, display_name, description, response_fields
TOOL_DEFS = {
    "Tool-SIQ11": {
        "class": "GetServiceOrderTool",
        "display": "get_service_order",
        "desc": "Retrieve full service order details including customer, laboratory, service type, and current status.",
        "fields": ["order_number", "order_status", "customer", "laboratory", "service_type", "inspection_status", "sla_status"],
    },
    "Tool-SIQ12": {
        "class": "GetCustomerRequestsTool",
        "display": "get_customer_requests",
        "desc": "Retrieve service order information for a given order number, including customer details.",
        "input_name": "order_number",
        "fields": ["order_number", "customer", "service_type", "order_status"],
    },
    "Tool-SIQ13": {
        "class": "GetInspectionStatusTool",
        "display": "get_inspection_status",
        "desc": "Retrieve inspection result (passed/failed/partial/no_inspection) for a service order.",
        "fields": ["order_number", "inspection_status", "order_status"],
    },
    "Tool-SIQ14": {
        "class": "GetSLAStatusTool",
        "display": "get_sla_status",
        "desc": "Retrieve SLA compliance status (on_track/at_risk/overdue/closed) for a service order.",
        "fields": ["order_number", "sla_status", "order_status"],
    },
    "Tool-SIQ15": {
        "class": "GetApplicableStandardTool",
        "display": "get_applicable_standard",
        "desc": "Retrieve service type and laboratory information for a service order (standard context).",
        "fields": ["order_number", "service_type", "laboratory", "order_status"],
    },
    "Tool-SIQ16": {
        "class": "GetLaboratoryTool",
        "display": "get_laboratory",
        "desc": "Retrieve laboratory information assigned to a service order.",
        "fields": ["order_number", "laboratory", "service_type", "order_status"],
    },
}

CODE_TEMPLATE = '''"""ServiceIQ tool: {display}"""
from __future__ import annotations
import os
import re
from typing import Any
import httpx
from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output, SecretStrInput, StrInput
from lfx.schema.data import Data

_TIMEOUT = 30
_SAFE_RE = re.compile(r"^[\\x20-\\x7E]{{1,200}}$")


class {class_name}(Component):
    display_name = "{display}"
    description = "{desc}"
    icon = "ClipboardList"
    name = "{class_name}"

    inputs = [
        MessageTextInput(
            name="order_number",
            display_name="Order Number",
            info="Service order number (e.g. V-6747-09-000).",
            tool_mode=True,
            required=True,
        ),
        StrInput(
            name="api_base_url",
            display_name="API Base URL",
            info="Base URL of the ServiceIQ AI API.",
            value="http://localhost:8000",
            advanced=True,
            required=True,
        ),
        SecretStrInput(
            name="bearer_token",
            display_name="Bearer Token",
            info="JWT Bearer token. Loaded from SERVICEIQ_BEARER_TOKEN global variable.",
            load_from_db=True,
            value="SERVICEIQ_BEARER_TOKEN",
            required=False,
        ),
    ]

    outputs = [
        Output(display_name="Result", name="output", method="run_tool"),
    ]

    async def run_tool(self) -> Data:
        param_value = getattr(self, "order_number", "") or ""
        param_value = str(param_value).strip()
        if not param_value or not _SAFE_RE.match(param_value):
            self.status = "Validation error"
            return Data(data={{"success": False, "error": "Invalid or missing order_number."}})

        token = (getattr(self, "bearer_token", None) or "").strip()
        if not token:
            token = os.environ.get("SERVICEIQ_BEARER_TOKEN", "")
        if not token:
            self.status = "Missing bearer token"
            return Data(data={{"success": False, "error": "Bearer token not configured."}})

        base = (getattr(self, "api_base_url", "http://localhost:8000") or "http://localhost:8000").rstrip("/")
        url = f"{{base}}/api/ai/service-orders/{{param_value}}"
        hdrs = {{"Authorization": f"Bearer {{token}}", "Accept": "application/json"}}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(url, headers=hdrs)
        except httpx.TimeoutException:
            self.status = "Timeout"
            return Data(data={{"success": False, "error": "Request timed out."}})
        except httpx.RequestError as exc:
            self.status = f"Connection error: {{type(exc).__name__}}"
            return Data(data={{"success": False, "error": f"Connection error: {{type(exc).__name__}}"}})

        if resp.status_code == 200:
            try:
                body: dict[str, Any] = resp.json()
                self.status = "OK"
                return Data(data={{"success": True, **body}})
            except Exception:
                self.status = "Invalid JSON"
                return Data(data={{"success": False, "error": "Invalid JSON response."}})

        self.status = f"HTTP {{resp.status_code}}"
        return Data(data={{"success": False, "error_code": resp.status_code,
                          "error": f"HTTP {{resp.status_code}}", "order_number": param_value}})
'''


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


def main() -> None:
    print("=== Fix Tool Endpoints ===")
    token = lf_jwt()
    flow = api_get(f"/api/v1/flows/{FLOW_ID}", token)
    nodes = flow["data"]["nodes"]
    edges = flow["data"]["edges"]

    for n in nodes:
        nid = n["id"]
        if nid not in TOOL_DEFS:
            continue

        td = TOOL_DEFS[nid]
        code = CODE_TEMPLATE.format(
            display=td["display"],
            class_name=td["class"],
            desc=td["desc"],
        )
        tpl = n["data"]["node"]["template"]
        tpl["code"]["value"] = code
        tpl["api_base_url"]["value"] = "http://localhost:8000"
        if "bearer_token" in tpl:
            tpl["bearer_token"]["value"] = "SERVICEIQ_BEARER_TOKEN"
            tpl["bearer_token"]["load_from_db"] = True
        # Update display_name
        n["data"]["node"]["display_name"] = td["display"]
        print(f"  Fixed {nid} → {td['display']} → /api/ai/service-orders/{{order_number}} ✓")

    patch_body = {
        "id": FLOW_ID,
        "name": flow["name"],
        "description": flow.get("description", ""),
        "data": {
            "nodes": nodes,
            "edges": edges,
            "viewport": flow["data"].get("viewport", {}),
        },
        "folder_id": flow.get("folder_id"),
    }
    result = api_patch(f"/api/v1/flows/{FLOW_ID}", patch_body, token)
    print(f"\nPATCH: id={result.get('id','?')}, nodes={len(result['data']['nodes'])}")
    print("=== Fix complete ✓ ===")


if __name__ == "__main__":
    main()
