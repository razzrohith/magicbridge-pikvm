#!/usr/bin/env python3
"""Copy the magicbridge-marketplace plugin into the MagicBridgeV2 git repo as
`agent-plugin/` and push it to GitHub, so the VM can pull + /plugin install it.
Commits DIRECTLY to E:\\ (git add), bypassing sync_and_push's robocopy excludes."""
import os, shutil, subprocess

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "push_plugin_log.txt")
def log(m): open(LOG, "a", encoding="utf-8").write(str(m) + "\n"); print(m)
open(LOG, "w").close()

SRC = r"C:\Users\razzr\AppData\Roaming\Claude\local-agent-mode-sessions\b8da399f-3c46-44aa-aa18-60b321602b8d\603ce8fb-5e73-4a23-b2e3-f8f16445e987\local_b2e9fed4-8953-4182-a43f-c44d95a8ce78\outputs\magicbridge-marketplace"
EDEV = r"E:\Startup\magicbridge-pikvm"
DST = os.path.join(EDEV, "agent-plugin")

def run(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout + p.stderr).strip()

if not os.path.isdir(SRC):
    log("ERROR: plugin source not found: " + SRC); raise SystemExit(1)
if not os.path.isdir(EDEV):
    log("ERROR: git repo not found: " + EDEV); raise SystemExit(1)

# fresh copy of the marketplace into the repo (drop any __pycache__)
if os.path.isdir(DST):
    shutil.rmtree(DST)
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
log("copied plugin -> " + DST)
log("files: " + str(sum(len(f) for _, _, f in os.walk(DST))))

rc, out = run(["git", "-C", EDEV, "add", "agent-plugin"]); log("git add rc=%d %s" % (rc, out))
rc, st = run(["git", "-C", EDEV, "status", "--short", "agent-plugin"]); log("staged:\n" + (st or "(nothing new)"))
rc, out = run(["git", "-C", EDEV, "commit", "-m",
               "add agent-plugin: magicbridge-toolkit Claude Code plugin (skills + MCP) for the VM"])
log("git commit rc=%d\n%s" % (rc, out))
rc, out = run(["git", "-C", EDEV, "push", "origin", "main"]); log("git push rc=%d\n%s" % (rc, out))
rc, head = run(["git", "-C", EDEV, "log", "-1", "--oneline"]); log("HEAD: " + head)
log("=== done — plugin is on GitHub under agent-plugin/ ===")
