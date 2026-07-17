import os, paramiko
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"redeploy_and_test_ts_log.txt")
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

run("command rw 2>/dev/null || mount -o remount,rw /")
sftp=cli.open_sftp()
local=r"C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2\services\magicbridge-net\app.py"
sftp.put(local, "/opt/magicbridge/services/magicbridge-net/app.py")
sftp.chmod("/opt/magicbridge/services/magicbridge-net/app.py", 0o644)
match = os.path.getsize(local) == sftp.stat("/opt/magicbridge/services/magicbridge-net/app.py").st_size
log("deploy match: %s"%match)
sftp.close()
run("command ro 2>/dev/null || true")

log("syntax check: "+run("python3 -c \"compile(open('/opt/magicbridge/services/magicbridge-net/app.py').read(),'app.py','exec')\" 2>&1 && echo CLEAN"))
log("restart: "+run("systemctl restart magicbridge-net && sleep 1 && systemctl is-active magicbridge-net"))
log("=== tailscale up (direct, bypass nginx) ===")
log(run("curl -s -X POST http://127.0.0.1:8410/tailscale -H 'Content-Type: application/json' -d '{\"action\":\"up\"}'", t=20))
log("=== rootfs state after (should be back to ro) ===")
log(run("mount | grep 'on / ' "))
cli.close(); log("=== done ===")
