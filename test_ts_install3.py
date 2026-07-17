import os, paramiko
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"test_ts_install3_log.txt")
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

log(run("command -v rw >/dev/null && rw || mount -o remount,rw /"))
log("enable: "+run("systemctl enable --now tailscaled 2>&1"))
log("is-active: "+run("systemctl is-active tailscaled"))
log(run("command -v ro >/dev/null && ro || true"))
log("status: "+run("tailscale status 2>&1 | head -6"))
cli.close(); log("=== done ===")
