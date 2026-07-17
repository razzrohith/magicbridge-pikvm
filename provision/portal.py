#!/usr/bin/env python3
"""
MagicBridgeV2 captive-portal setup page (stdlib only — no Flask).

Launched by mb-portal.sh while the "MagicBridge-Setup" AP is up. Serves a
branded page on every URL (captive detection), lists nearby networks, and on
submit writes the chosen SSID/password (+ optional Tailscale key) to the files
mb-portal.sh reads, then exits so the script can reconnect.

    python3 portal.py <ap_ip> <port> <wifi_file> <tskey_file>
"""
import html
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

AP_IP, PORT, WIFI_FILE, TS_FILE = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
_done = {"v": False}


def scan_ssids():
    ssids = []
    try:
        subprocess.run(["wpa_cli", "-i", "wlan0", "scan"], capture_output=True, timeout=6)
    except Exception:
        pass
    for cmd in (["wpa_cli", "-i", "wlan0", "scan_results"], ["iw", "dev", "wlan0", "scan"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout
        except Exception:
            continue
        if cmd[0] == "wpa_cli":
            for ln in out.splitlines()[1:]:
                c = ln.split("\t")
                if len(c) >= 5 and c[4].strip():
                    ssids.append(c[4].strip())
        else:
            for ln in out.splitlines():
                ln = ln.strip()
                if ln.startswith("SSID:") and ln[5:].strip():
                    ssids.append(ln[5:].strip())
        if ssids:
            break
    seen, uniq = set(), []
    for s in ssids:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return uniq[:25]


PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>MagicBridge Setup</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:#05070d;color:#e8f6ff;
font-family:-apple-system,Segoe UI,Roboto,sans-serif;display:grid;place-items:center;padding:20px;
background-image:radial-gradient(800px 400px at 20% -10%,rgba(0,229,255,.10),transparent 60%),radial-gradient(700px 350px at 100% 0,rgba(176,38,255,.12),transparent 55%)}}
.card{{width:100%;max-width:400px;background:rgba(13,18,32,.75);border:1px solid rgba(0,229,255,.18);
border-radius:14px;padding:24px;box-shadow:0 20px 50px rgba(0,0,0,.5)}}
.logo{{width:44px;height:44px;border-radius:10px;display:grid;place-items:center;font-weight:800;font-size:19px;color:#03121a;
background:linear-gradient(135deg,#00e5ff,#b026ff);box-shadow:0 0 22px rgba(0,229,255,.45);margin-bottom:14px}}
h1{{margin:0 0 4px;font-size:17px;letter-spacing:2px;text-transform:uppercase;
background:linear-gradient(90deg,#00e5ff,#b026ff);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}}
p.sub{{margin:0 0 18px;color:#8aa2c0;font-size:13px}}
label{{display:block;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#516079;margin:12px 0 5px}}
input,select{{width:100%;background:rgba(5,7,13,.8);border:1px solid rgba(176,38,255,.25);color:#e8f6ff;
border-radius:8px;padding:11px;font-size:14px;outline:none}}
input:focus,select:focus{{border-color:#00e5ff;box-shadow:0 0 0 3px rgba(0,229,255,.12)}}
button{{width:100%;margin-top:20px;padding:12px;border:0;border-radius:8px;font-size:14px;font-weight:700;
letter-spacing:1px;text-transform:uppercase;color:#03121a;cursor:pointer;
background:linear-gradient(135deg,#00e5ff,#b026ff);box-shadow:0 0 20px rgba(0,229,255,.4)}}
.hint{{font-size:11px;color:#516079;margin-top:14px;line-height:1.5}}
.ok{{text-align:center}}.ok h1{{margin-bottom:10px}}
</style></head><body><div class=card>{body}</div></body></html>"""

FORM = """<div class=logo>M</div><h1>MagicBridge Setup</h1>
<p class=sub>Connect your bridge to Wi-Fi to finish setup.</p>
<form method=post action="/save">
<label>Network</label>
<select name=ssid_pick onchange="document.getElementById('ssid').value=this.value">
<option value="">— choose a network —</option>{opts}</select>
<label>SSID</label><input id=ssid name=ssid placeholder="network name" required>
<label>Password</label><input name=psk type=password placeholder="leave blank if open">
<label>Tailscale auth key (optional)</label><input name=tskey placeholder="tskey-…">
<button type=submit>Connect</button></form>
<p class=hint>The bridge will join this network and this setup hotspot will disappear. Reconnect your device to that network to reach MagicBridge.</p>"""

DONE = """<div class=ok><div class=logo style="margin:0 auto 14px">M</div>
<h1>Connecting…</h1><p class=sub>MagicBridge is saving <b>{ssid}</b> and restarting to join it —
this takes about a minute. Rejoin your normal Wi-Fi and open <b>http://magicbridge.local/</b>.
If the <b>MagicBridge-Setup</b> hotspot reappears, the password was wrong — reconnect and try again.</p></div>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, code=200):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        opts = "".join("<option value=\"%s\">%s</option>" % (html.escape(s), html.escape(s))
                       for s in scan_ssids())
        self._send(PAGE.format(body=FORM.format(opts=opts)))

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        data = urllib.parse.parse_qs(self.rfile.read(n).decode())
        ssid = (data.get("ssid", [""])[0] or "").strip()
        psk = (data.get("psk", [""])[0] or "")
        tskey = (data.get("tskey", [""])[0] or "").strip()
        # strip newlines to keep the line-based files clean
        ssid = ssid.replace("\n", "").replace("\r", "")
        psk = psk.replace("\n", "").replace("\r", "")
        if ssid:
            with open(WIFI_FILE, "w") as f:
                f.write(ssid + "\n" + psk + "\n")
            if tskey:
                with open(TS_FILE, "w") as f:
                    f.write(tskey.replace("\n", "").replace("\r", "") + "\n")
        self._send(PAGE.format(body=DONE.format(ssid=html.escape(ssid or "the network"))))
        _done["v"] = True


def main():
    import time
    srv = ThreadingHTTPServer((AP_IP, PORT), H)
    srv.timeout = 1
    # Wait indefinitely — the setup hotspot must stay up until someone submits
    # credentials. mb-portal.sh then verifies the connection and only exits the
    # provisioning loop once we're actually joined to a real network.
    while not _done["v"]:
        srv.handle_request()
    # give the browser a moment to render the "connecting" page before teardown
    time.sleep(2)


if __name__ == "__main__":
    main()
