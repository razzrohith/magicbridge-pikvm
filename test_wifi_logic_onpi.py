"""Uploaded to the Pi and run there to unit-test _wifi_write_network() without
touching the live WiFi connection (no systemctl restart). Restores the conf
file exactly afterward."""
import sys, re, importlib.util
spec = importlib.util.spec_from_file_location("mbnet", "/opt/magicbridge/services/magicbridge-net/app.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

conf = m.WPA_CONF
before = open(conf).read()
m._rw()
try:
    m._wifi_write_network("MB Unit Test Net", "testpass123")
    mid = open(conf).read()
    assert 'ssid="MB Unit Test Net"' in mid, "write failed"
    assert 'psk="testpass123"' in mid, "psk not plain-quoted correctly"
    m._wifi_write_network("MB Unit Test Net", "differentpass99")
    mid2 = open(conf).read()
    assert mid2.count("MB Unit Test Net") == 1, "dedupe failed, found %d" % mid2.count("MB Unit Test Net")
    assert "differentpass99" in mid2 and "testpass123" not in mid2, "replace failed"
    print("WRITE+DEDUPE OK")
finally:
    cleaned = re.sub(r'\nnetwork=\{[^}]*ssid="MB Unit Test Net"[^}]*\}\n', "\n", open(conf).read())
    open(conf, "w").write(cleaned)
    after = open(conf).read()
    m._ro()
    if after == before:
        print("RESTORE OK — conf identical to pre-test state")
    else:
        print("RESTORE MISMATCH!!! before=%d chars after=%d chars" % (len(before), len(after)))
