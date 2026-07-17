import os, paramiko
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"run_wifi_logic_test_log.txt")
def log(m): open(LOG,"a",encoding="utf-8").write(str(m)+"\n"); print(m)
open(LOG,"w").close()
cli=paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("192.168.1.37", username="root", password="root", timeout=15, allow_agent=False, look_for_keys=False)
sftp=cli.open_sftp()
local=r"C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2\test_wifi_logic_onpi.py"
sftp.put(local, "/tmp/test_wifi_logic_onpi.py")
sftp.close()
def run(cmd,t=25):
    ch=cli.get_transport().open_session(); ch.settimeout(t); ch.exec_command(cmd)
    out=b""
    while True:
        d=ch.recv(65535)
        if not d: break
        out+=d
    return out.decode(errors="replace").strip()
log(run("python3 /tmp/test_wifi_logic_onpi.py 2>&1"))
log("--- saved networks after test (must still be exactly Staff + Quality Inn- Office) ---")
log(run("grep 'ssid=' /etc/wpa_supplicant/wpa_supplicant-wlan0.conf"))
log("--- still online? ---")
log(run("ip -4 addr show wlan0 | grep -o 'inet [0-9.]*'"))
run("rm -f /tmp/test_wifi_logic_onpi.py")
cli.close(); log("=== done ===")
