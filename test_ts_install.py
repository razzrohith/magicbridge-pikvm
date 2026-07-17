import os, paramiko
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"test_ts_install_log.txt")
def log(m): open(LOG,"a",encoding="utf-8").write(str(m)+"\n"); print(m)
open(LOG,"w").close()
cli=paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("192.168.1.37", username="root", password="root", timeout=15, allow_agent=False, look_for_keys=False)
def run(cmd,t=60):
    ch=cli.get_transport().open_session(); ch.settimeout(t); ch.exec_command(cmd)
    out=b""
    while True:
        d=ch.recv(65535)
        if not d: break
        out+=d
    return out.decode(errors="replace").strip()

log("=== unlock rootfs ===")
log(run("command -v rw >/dev/null && rw || mount -o remount,rw /"))
log("=== pacman -Ss tailscale (is it in the configured repos?) ===")
log(run("pacman -Ss tailscale 2>&1 | head -10", t=30))
log("=== pacman -Sy --noconfirm tailscale (real attempt, capped) ===")
log(run("timeout 45 pacman -Sy --noconfirm tailscale 2>&1 | tail -25", t=55))
log("=== relock rootfs ===")
log(run("command -v ro >/dev/null && ro || true"))
cli.close(); log("=== done ===")
