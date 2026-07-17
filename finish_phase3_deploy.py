import os, paramiko
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"finish_phase3_deploy_log.txt")
def log(m): open(LOG,"a",encoding="utf-8").write(str(m)+"\n"); print(m)
open(LOG,"w").close()
cli=paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("192.168.1.37", username="root", password="root", timeout=15, allow_agent=False, look_for_keys=False)
def run(cmd,t=30):
    ch=cli.get_transport().open_session(); ch.settimeout(t); ch.exec_command(cmd)
    out=b""
    while True:
        d=ch.recv(65535)
        if not d: break
        out+=d
    return out.decode(errors="replace").strip()

log("py_compile with PYTHONDONTWRITEBYTECODE (no cache write, avoids RO false-negative): "+
    run("PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile /opt/magicbridge/services/magicbridge-net/app.py && echo PY_OK || echo PY_ERR"))
log("restart: "+run("systemctl restart magicbridge-net && sleep 1 && systemctl is-active magicbridge-net"))
log("nginx -t: "+run("nginx -t 2>&1 | tail -3"))
log("reload: "+run("systemctl reload kvmd-nginx 2>&1"))

log("=== test: tailscale install (idempotent) ===")
log(run("curl -sk -X POST https://127.0.0.1/mb/net/tailscale/install -H 'Content-Type: application/json' -d '{}'", t=40))
log("=== test: tailscale up (expect login_url) ===")
log(run("curl -sk -X POST https://127.0.0.1/mb/net/tailscale -H 'Content-Type: application/json' -d '{\"action\":\"up\"}'", t=20))
cli.close(); log("=== done ===")
