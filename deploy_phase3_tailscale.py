#!/usr/bin/env python3
"""Deploy Phase 3 Tailscale fix: magicbridge-net app.py (rw/ro wrap + login URL
extraction), stealth page login-link UI, nginx timeout bump for /mb/net/."""
import os
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_phase3_tailscale_log.txt")
def log(m):
    open(LOG, "a", encoding="utf-8").write(str(m) + "\n"); print(m)

BASE = r"C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2"
FILES = [
    (BASE + r"\services\magicbridge-net\app.py", "/opt/magicbridge/services/magicbridge-net/app.py"),
    (BASE + r"\web\stealth\index.html", "/opt/magicbridge/web/stealth/index.html"),
    (BASE + r"\nginx\magicbridge.conf", "/etc/kvmd/nginx/magicbridge.conf"),
]

def main():
    open(LOG, "w").close()
    import paramiko
    cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect("192.168.1.37", username="root", password="root", timeout=15,
                allow_agent=False, look_for_keys=False)
    def run(cmd, t=30):
        ch = cli.get_transport().open_session(); ch.settimeout(t); ch.exec_command(cmd)
        out = b""
        while True:
            d = ch.recv(65535)
            if not d: break
            out += d
        return ch.recv_exit_status(), out.decode(errors="replace").strip()

    run("command rw 2>/dev/null || mount -o remount,rw /")
    sftp = cli.open_sftp()
    ok = True
    for local, remote in FILES:
        try:
            sftp.put(local, remote); sftp.chmod(remote, 0o644)
            match = os.path.getsize(local) == sftp.stat(remote).st_size
            log("%s -> %s : %s" % (local, remote, "OK" if match else "MISMATCH"))
            ok = ok and match
        except Exception as e:
            log("FAIL %s -> %s : %s" % (local, remote, e)); ok = False
    sftp.close()
    run("command ro 2>/dev/null || true")
    log("deploy ok: %s" % ok)

    # syntax-check app.py before restarting the service
    rc, out = run("python3 -m py_compile /opt/magicbridge/services/magicbridge-net/app.py && echo PY_OK || echo PY_ERR")
    log("py_compile: " + out)
    if "PY_ERR" in out:
        log("ABORT: syntax error, not restarting service")
        cli.close(); return

    rc, out = run("systemctl restart magicbridge-net && sleep 1 && systemctl is-active magicbridge-net")
    log("restart magicbridge-net: " + out)
    rc, out = run("nginx -t 2>&1 | tail -3; systemctl reload kvmd-nginx 2>&1")
    log("nginx reload: " + out)

    # --- functional tests ---
    log("=== test: /mb/net/tailscale install (idempotent, already installed) ===")
    rc, out = run("curl -sk -X POST https://127.0.0.1/mb/net/tailscale/install -H 'Content-Type: application/json' -d '{}'", t=40)
    log(out)
    log("=== test: /mb/net/tailscale up (expect login_url, node not yet authed) ===")
    rc, out = run("curl -sk -X POST https://127.0.0.1/mb/net/tailscale -H 'Content-Type: application/json' -d '{\"action\":\"up\"}'", t=20)
    log(out)
    cli.close()
    log("=== done ===")
main()
