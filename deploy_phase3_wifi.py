import os, paramiko
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"deploy_phase3_wifi_log.txt")
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

BASE=r"C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2"
FILES=[
    (BASE+r"\services\magicbridge-net\app.py","/opt/magicbridge/services/magicbridge-net/app.py"),
    (BASE+r"\web\index.html","/opt/magicbridge/web/index.html"),
]
run("command rw 2>/dev/null || mount -o remount,rw /")
sftp=cli.open_sftp()
ok=True
for local,remote in FILES:
    sftp.put(local,remote); sftp.chmod(remote,0o644)
    m=os.path.getsize(local)==sftp.stat(remote).st_size
    log("%s -> %s : %s"%(local,remote,"OK" if m else "MISMATCH")); ok=ok and m
sftp.close()
run("command ro 2>/dev/null || true")
log("deploy ok: %s"%ok)

log("syntax: "+run("python3 -c \"compile(open('/opt/magicbridge/services/magicbridge-net/app.py').read(),'app.py','exec')\" 2>&1 && echo CLEAN"))
log("restart: "+run("systemctl restart magicbridge-net && sleep 1 && systemctl is-active magicbridge-net"))

log("=== test: wifi saved list (read-only, safe) ===")
log(run("curl -s http://127.0.0.1:8410/wifi/saved"))
log("=== test: wifi connect validation (bad short pw, should reject BEFORE touching wpa conf or restarting wpa_supplicant) ===")
log(run("curl -s -X POST http://127.0.0.1:8410/wifi -H 'Content-Type: application/json' -d '{\"ssid\":\"TestNet\",\"password\":\"short\"}'"))
log("=== test: wifi forget on a nonexistent SSID (read+compare only, no restart, safe) ===")
log(run("curl -s -X POST http://127.0.0.1:8410/wifi/forget -H 'Content-Type: application/json' -d '{\"ssid\":\"MB-Does-Not-Exist\"}'"))
log("=== test the write/replace/dedupe LOGIC directly (no systemctl restart — avoids disrupting the live WiFi link) ===")
test_script = r'''
import sys
sys.path.insert(0, "/opt/magicbridge/services/magicbridge-net")
import importlib.util
spec = importlib.util.spec_from_file_location("mbnet", "/opt/magicbridge/services/magicbridge-net/app.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import re
conf = m.WPA_CONF
before = open(conf).read()
m._rw()
try:
    m._wifi_write_network("MB Unit Test Net", "testpass123")
    mid = open(conf).read()
    assert re.search(r"ssid=\"MB Unit Test Net\"", mid), "write failed"
    assert "MB Unit Test Net" in mid and 'psk="testpass123"' in mid, "psk not plain-quoted correctly"
    # re-write same SSID with a different password -> must dedupe, not duplicate
    m._wifi_write_network("MB Unit Test Net", "differentpass99")
    mid2 = open(conf).read()
    assert mid2.count("MB Unit Test Net") == 1, "dedupe failed, found %d" % mid2.count("MB Unit Test Net")
    assert "differentpass99" in mid2 and "testpass123" not in mid2, "replace failed"
finally:
    # clean up: remove the test block, restore to exactly the pre-test state
    cleaned = re.sub(r"\nnetwork=\{[^}]*ssid=\"MB Unit Test Net\"[^}]*\}\n", "\n", open(conf).read())
    open(conf, "w").write(cleaned)
    after = open(conf).read()
    assert after == before, "conf not restored to original state!"
    m._ro()
print("WIFI_WRITE_LOGIC_OK")
'''
log(run("python3 -c \"%s\"" % test_script.replace('"','\\"'), t=25))
log("=== confirm real saved networks (Staff, Quality Inn- Office) still exactly 2, untouched ===")
log(run("grep -c 'ssid=' /etc/wpa_supplicant/wpa_supplicant-wlan0.conf"))
log("=== confirm still online (no disruption) ===")
log(run("ip -4 addr show wlan0 | grep -o 'inet [0-9.]*'"))
cli.close(); log("=== done ===")
