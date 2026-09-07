# -*- coding: utf-8 -*-
"""Assemble the user adoption report: template + adoption data + logo -> ../adoption/

Same shape as build_dash.py: the template consumes one JSON object, so the page is a
single self-contained file with no runtime dependencies. Writes index.html, meta.json
(for the Refresh check) and .datahash (so an unchanged trail does not make a commit).
"""
import hashlib
import json
import os

SCR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCR)

tpl = open(os.path.join(SCR, "adoption_template.html"), encoding="utf-8").read()
data_txt = open(os.path.join(SCR, "adoption_data.json"), encoding="utf-8").read()
logo = "data:image/png;base64," + open(os.path.join(SCR, "kp_logo.b64"), encoding="ascii").read().strip()

html = tpl.replace("__LOGO__", logo).replace("__DATA__", data_txt)
assert "accessToken" not in html, "token leak!"

outdir = os.path.join(ROOT, "adoption")
os.makedirs(outdir, exist_ok=True)
open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write(html)

data = json.loads(data_txt)
open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8").write(json.dumps(dict(data["meta"])))

# change guard: hash the events, not the build stamps
d2 = json.loads(data_txt)
d2["meta"].pop("generatedAt", None)
d2["meta"].pop("generatedAtEpoch", None)
h = hashlib.sha256(json.dumps(d2, sort_keys=True).encode()).hexdigest()
open(os.path.join(outdir, ".datahash"), "w").write(h)

print("built adoption/index.html %d bytes | %d events | datahash %s"
      % (os.path.getsize(os.path.join(outdir, "index.html")), len(data["events"]), h[:12]))
