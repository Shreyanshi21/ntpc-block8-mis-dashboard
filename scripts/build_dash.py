# -*- coding: utf-8 -*-
"""Assemble a project dashboard: template + <project> data + logo -> <outDir>/index.html,
meta.json and .datahash.   python build_dash.py <project key>   (scripts/projects/<key>.json)
NTPC keeps build_ntpc_dash_v3.py; this is the same assembly for any other project."""
import json, os, sys, hashlib
SCR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCR)
key = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DASH_PROJECT", "")).strip().lower()
if not key:
    raise SystemExit("usage: build_dash.py <project key>")
cfg = json.load(open(os.path.join(SCR, "projects", key + ".json"), encoding="utf-8"))
tpl = open(os.path.join(SCR, cfg.get("template", "ntpc_dash_template_v3.html")), encoding="utf-8").read()
data_txt = open(os.path.join(SCR, cfg["dataFile"]), encoding="utf-8").read()
logo = "data:image/png;base64," + open(os.path.join(SCR, "kp_logo.b64"), encoding="ascii").read().strip()
# what the page is made of, hashed together: the id moves whenever either side does
build_id = hashlib.sha256((tpl + "\x00" + data_txt).encode("utf-8")).hexdigest()[:16]
html = tpl.replace("__LOGO__", logo).replace("__DATA__", data_txt).replace("__BUILD__", build_id)
assert "accessToken" not in html, "token leak!"
outdir = os.path.join(ROOT, cfg["outDir"])
os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)
data = json.loads(data_txt)
open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8").write(json.dumps(dict(data["meta"])))
# the page fetches this to find out whether the copy it is running is the current one
open(os.path.join(outdir, "version.json"), "w", encoding="utf-8").write(
    json.dumps({"build": build_id}))
# change guard: hash of the data EXCLUDING the build stamps, so unchanged data != new commit
d2 = json.loads(data_txt)
d2["meta"].pop("generatedAt", None)
d2["meta"].pop("generatedAtEpoch", None)
h = hashlib.sha256(json.dumps(d2, sort_keys=True).encode()).hexdigest()
open(os.path.join(outdir, ".datahash"), "w").write(h)
print("built %s/index.html %d bytes | datahash %s | build %s"
      % (cfg["outDir"], os.path.getsize(os.path.join(outdir, "index.html")), h[:12], build_id))
