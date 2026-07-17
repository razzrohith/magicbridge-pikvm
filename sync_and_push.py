#!/usr/bin/env python3
r"""
sync_and_push.py  --  keep git + local in sync for MagicBridgeV2.

Mirrors the mounted build folder (Projects\...\MagicBridgeV2, where edits are
made) into the git dev repo (E:\Startup\MagicbridgeV2), then commits and pushes
to GitHub. Run this after every change so git and local never drift.

  cmd /c python C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2\sync_and_push.py "commit message"

Check sync_and_push_log.txt. It does NOT delete extra files already in the repo
(push tooling, .git, .gitignore); it only copies build files over the top.
"""
import os, subprocess, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "sync_and_push_log.txt")
PROJ = r"C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2"
EDEV = r"E:\Startup\MagicbridgeV2"
# session-only artifacts we never want in git (logs, pulled temp copies, one-off diagnostics)
EXCLUDE_FILES = ["*_log.txt", "_*.html", "inspect_*.py", "fix_*.py", "check_*.py",
                 "pull_*.py", "get_*.py", "validate*.py", "rebrand_*.py", "find_*.py",
                 "install_portal.py", "enable_*.py", "diag_*.py", "apply_*.py",
                 "final_*.py", "recover_*.py", "finalize_*.py", "otg_*.py",
                 "verify_*.py", "audit_*.py", "deploy_nginx.py"]


def log(m):
    open(LOG, "a", encoding="utf-8").write(str(m) + "\n"); print(m)


def run(args, cwd=None, timeout=120):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def main():
    open(LOG, "w").close()
    msg = sys.argv[1] if len(sys.argv) > 1 else ("sync " + time.strftime("%Y-%m-%d %H:%M"))
    if not os.path.isdir(EDEV):
        log("ERROR: git repo missing: " + EDEV); return 1

    # 1) mirror build -> repo (copy over the top; do not delete repo-only files)
    cmd = ["robocopy", PROJ, EDEV, "/E", "/XD", ".git", "/XF"] + EXCLUDE_FILES + ["/NFL", "/NDL", "/NP"]
    rc, out = run(cmd)
    # robocopy: rc < 8 == success (0 none, 1 copied, 2 extra, 3 both, ...)
    log("robocopy rc=%d (%s)" % (rc, "ok" if rc < 8 else "FAILED"))
    if out:
        log(out[-1500:])
    if rc >= 8:
        return 1

    # 2) commit + push
    rc, out = run(["git", "-C", EDEV, "add", "-A"]); log("git add rc=%d %s" % (rc, out))
    rc, st = run(["git", "-C", EDEV, "status", "--short"]); log("staged:\n" + (st or "(clean)"))
    if not st.strip():
        log("nothing to commit — git already matches local."); log("=== done ==="); return 0
    rc, out = run(["git", "-C", EDEV, "commit", "-m", msg]); log("git commit rc=%d\n%s" % (rc, out))
    rc, out = run(["git", "-C", EDEV, "push", "origin", "main"]); log("git push rc=%d\n%s" % (rc, out))
    if rc != 0:
        log("PUSH FAILED — check credentials / network."); return 1
    rc, head = run(["git", "-C", EDEV, "log", "-1", "--oneline"]); log("HEAD now: " + head)
    log("=== done — git + local in sync ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
