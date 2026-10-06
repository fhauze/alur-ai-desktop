"""Find flows with Google Generative AI nodes."""
import json
import urllib.request

LANGFLOW_URL = "http://localhost:7860"


def lf_jwt():
    req = urllib.request.Request(f"{LANGFLOW_URL}/api/v1/auto_login")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]


token = lf_jwt()
req = urllib.request.Request(f"{LANGFLOW_URL}/api/v1/flows/?page=1&size=100")
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Accept-Encoding", "identity")
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())

flows = data.get("flows", data) if isinstance(data, dict) else data
for f in flows:
    fid = f["id"]
    fname = f["name"]
    nodes = f.get("data", {}).get("nodes", []) if f.get("data") else []
    for n in nodes:
        ntype = n.get("data", {}).get("type", "")
        if "Google" in ntype or "Gemini" in ntype:
            print(f"FOUND: {fname} [{fid}] node_type={ntype}")
            # Print node structure (excluding 'code' for brevity)
            nd = n.get("data", {}).get("node", {})
            tpl = nd.get("template", {})
            print("  node keys:", list(n.keys()))
            print("  data keys:", list(n.get("data", {}).keys()))
            print("  node.data keys:", list(nd.keys()))
            # save model_name
            mn = tpl.get("model_name", {})
            print("  model_name:", mn.get("value") if isinstance(mn, dict) else mn)
            # save to workspace
            import os
            out_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "found_gemini_node.json"
            )
            with open(out_path, "w") as out:
                json.dump(n, out, indent=2)
            print(f"  Saved to {out_path}")
            break
    else:
        continue
    break
else:
    print("No flows with Google Generative AI found")
