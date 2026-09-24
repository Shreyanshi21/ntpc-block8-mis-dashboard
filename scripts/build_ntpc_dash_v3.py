# -*- coding: utf-8 -*-
"""Assemble v2: template + live data + logo -> ../v2/index.html + meta.json + .datahash"""
import json, os, hashlib
SCR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCR)
tpl = open(os.path.join(SCR, "ntpc_dash_template_v3.html"), encoding="utf-8").read()
data_txt = open(os.path.join(SCR, "ntpc_dashboard_data_v2.json"), encoding="utf-8").read()
logo = "data:image/png;base64," + open(os.path.join(SCR, "kp_logo.b64"), encoding="ascii").read().strip()
sync_json = json.dumps({"repo": "Vikas-visilean/ntpc-block8-mis-dashboard", "workflow": "refresh-v2.yml"})
html = tpl.replace("__LOGO__", logo).replace("__SYNC__", sync_json).replace("__DATA__", data_txt)
assert "accessToken" not in html, "token leak!"
outdir = os.path.join(ROOT, "v3")
os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)

data = json.loads(data_txt)
meta = dict(data["meta"])
open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8").write(json.dumps(meta))
# change guard: hash of the data EXCLUDING generatedAt (so unchanged data != new commit)
d2 = json.loads(data_txt)
d2["meta"].pop("generatedAt", None)
h = hashlib.sha256(json.dumps(d2, sort_keys=True).encode()).hexdigest()
open(os.path.join(outdir, ".datahash"), "w").write(h)
# second guard: the TEMPLATE alone. .datahash only moves when VisiLean data moves,
# so without this a template change never reaches the published page on its own.
th = hashlib.sha256((tpl + "\x00" + logo).encode("utf-8")).hexdigest()
open(os.path.join(outdir, ".tplhash"), "w").write(th)
print("built v3/index.html", os.path.getsize(os.path.join(outdir, "index.html")), "bytes | datahash", h[:12])
