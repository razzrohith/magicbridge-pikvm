#!/usr/bin/env python3
r"""Align the Pi's /opt/magicbridge git tree with origin/main, then restart only
what actually changed (incremental) — or flag an out-of-tree/full deploy when a
change lands outside /opt/magicbridge. Run:
    python align_pi.py        (writes align_pi_log.txt next to this file)
"""
import os
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "align_pi_log.txt")
PI = "172.16.20.209"


def log(m):
    open(LOG, "a", encoding="utf-8").write(str(m) + "\n"); print(m)


# Which service(s) an in-tree path drives, for targeted (incremental) restarts.
SVC_MAP = [
    ("services/common/",             ["magicbridge-net", "magicbridge-stealth", "magicbridge-agent"]),  # shared lib
    ("services/magicbridge-net/",    ["magicbridge-net"]),
    ("services/magicbridge-stealth/", ["magicbridge-stealth"]),
    ("services/magicbridge-agent/",  ["magicbridge-agent"]),
]

# In-tree paths whose REAL target lives OUTSIDE /opt/magicbridge. `align_pi.py`
# only resets /opt/magicbridge, so a change here needs the installer or an SFTP
# step — we flag it instead of silently under-deploying (the "installer gap").
OUT_OF_TREE = {
    "systemd/":             "systemd units live in /etc/systemd/system - re-run magic-install.sh + daemon-reload",
    "nginx/":               "nginx include lives in /etc/kvmd/nginx - SFTP magicbridge.conf there + reload kvmd-nginx",
    "web/login_index.html": "login page lives in /usr/share/kvmd/web/login - SFTP it there",
    "kvmd-overrides/":      "kvmd overrides live in /etc/kvmd/override.d - re-run magic-install.sh",
    "magic-install.sh":     "installer changed - a full re-run picks up out-of-tree pieces",
}


def main():
    open(LOG, "w").close()
    import paramiko
    cli = paramiko.SSHClient(); cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(PI, username="root", password="root", timeout=15,
                allow_agent=False, look_for_keys=False)

    def run(cmd, t=90):
        ch = cli.get_transport().open_session(); ch.settimeout(t); ch.exec_command(cmd)
        out = b""
        while True:
            d = ch.recv(65535)
            if not d:
                break
            out += d
        return ch.recv_exit_status(), out.decode(errors="replace").strip()

    _, o = run("git -C /opt/magicbridge log -1 --oneline"); log("Pi HEAD before: " + o)
    run("command -v rw >/dev/null && rw || mount -o remount,rw /")
    # git refuses to touch a root-owned tree run as root ("detected dubious
    # ownership") unless the path is marked safe. The updater runs as root.
    run("git config --global --add safe.directory /opt/magicbridge")
    run("cd /opt/magicbridge && git fetch origin main 2>&1")
    # Incremental-vs-full detection: what will this pull actually change?
    _, changed = run("cd /opt/magicbridge && git diff --name-only HEAD..origin/main")
    files = [f for f in changed.splitlines() if f.strip()]
    _, o = run("cd /opt/magicbridge && git reset --hard origin/main 2>&1"); log("reset:\n" + o)
    run("command -v ro >/dev/null && ro || mount -o remount,ro /")

    if not files:
        log("changed files: none - already up to date, nothing to restart")
    else:
        log("changed files (%d):\n  %s" % (len(files), "\n  ".join(files)))
        to_restart = set()
        for f in files:
            for prefix, svcs in SVC_MAP:
                if f.startswith(prefix):
                    to_restart.update(svcs)
        if to_restart:
            for svc in sorted(to_restart):
                rc, _ = run("systemctl restart %s" % svc)
                log("restarted %s (rc=%d)" % (svc, rc))
        else:
            log("fast path: no live service needs a restart for this change")
        if any(f.startswith("web/") for f in files):
            run("systemctl reload kvmd-nginx 2>/dev/null"); log("reloaded kvmd-nginx (web changed)")
        flags = []
        for f in files:
            for prefix, msg in OUT_OF_TREE.items():
                if (f == prefix or f.startswith(prefix)) and msg not in flags:
                    flags.append(msg)
        if flags:
            log("!! OUT-OF-TREE changes - align only updates /opt/magicbridge, so also:")
            for m in flags:
                log("   - " + m)

    _, o = run("git -C /opt/magicbridge log -1 --oneline"); log("Pi HEAD after: " + o)
    _, o = run("git -C /opt/magicbridge status --short"); log("Pi tree status: " + (o or "(clean)"))
    _, o = run("systemctl is-active kvmd kvmd-nginx magicbridge-net magicbridge-stealth magicbridge-agent")
    log("services: " + o.replace("\n", " "))
    cli.close(); log("=== done ===")


if __name__ == "__main__":
    main()
