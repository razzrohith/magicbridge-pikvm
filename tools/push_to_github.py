#!/usr/bin/env python3
r"""
push_to_github.py  —  MagicBridgeV2 local sync + GitHub push (Windows).

WHAT IT DOES
  1. Copies the Cowork build tree
        C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2
     into your canonical dev clone
        E:\Startup\magicbridge-pikvm
     (skips .git, __pycache__, venvs, logs).
  2. git init / set 'origin' to  github.com/razzrohith/MagicBridgeV2  (if needed).
  3. git add -A, commit (message = arg or timestamp), push to 'main'.

HOW TO RUN  (no admin needed)
  In File Explorer, click the address bar (Ctrl+L) and type:
      cmd /c python C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2\tools\push_to_github.py
  then press Enter. The window closing / address bar reverting to Home is normal.

  Optional commit message:
      cmd /c python C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2\tools\push_to_github.py "scaffold V2"

OUTPUT
  This script writes its OWN log to
      E:\Startup\magicbridge-pikvm\push_log.txt
  (never shell-redirect it — that conflicts with the internal writer). Open that
  file to see what happened.

AUTH
  Uses your existing Git credential manager (the same login that pushed the V1
  MagicBridge repo). If push asks for credentials, complete the GitHub login once
  and re-run.
"""
import os, sys, shutil, subprocess, datetime, io

SRC   = r"C:\Users\razzr\Claude\Projects\MagicBridge\MagicBridgeV2"
DEST  = r"E:\Startup\magicbridge-pikvm"
REPO  = "https://github.com/razzrohith/MagicBridgeV2.git"
BRANCH = "main"
LOG   = os.path.join(DEST, "push_log.txt")
IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "venv",
                                "*.log", "_scratch", "build", "dist")

_buf = io.StringIO()
def log(*a):
    line = " ".join(str(x) for x in a)
    print(line); _buf.write(line + "\n")

def run(args, cwd):
    log(">", " ".join(args))
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if p.stdout.strip(): log(p.stdout.strip())
    if p.stderr.strip(): log(p.stderr.strip())
    return p.returncode

def sync_tree():
    log(f"Syncing {SRC}  ->  {DEST}")
    os.makedirs(DEST, exist_ok=True)
    for name in os.listdir(SRC):
        if name in (".git",):        # never clobber dest git dir
            continue
        s = os.path.join(SRC, name)
        d = os.path.join(DEST, name)
        if os.path.isdir(s):
            if os.path.isdir(d): shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d, ignore=IGNORE)
        else:
            shutil.copy2(s, d)
    log("Sync complete.")

def git_push(msg):
    if run(["git", "rev-parse", "--is-inside-work-tree"], DEST) != 0:
        run(["git", "init"], DEST)
        run(["git", "branch", "-M", BRANCH], DEST)
    # ensure remote
    if run(["git", "remote", "get-url", "origin"], DEST) != 0:
        run(["git", "remote", "add", "origin", REPO], DEST)
    else:
        run(["git", "remote", "set-url", "origin", REPO], DEST)
    run(["git", "add", "-A"], DEST)
    # commit (may be no-op if nothing changed)
    run(["git", "commit", "-m", msg], DEST)
    rc = run(["git", "push", "-u", "origin", BRANCH], DEST)
    if rc != 0:
        run(["git", "push", "-u", "origin", BRANCH, "--force-with-lease"], DEST)

def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else \
          "MagicBridgeV2 sync " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        if not os.path.isdir(SRC):
            log("ERROR: source not found:", SRC); return
        sync_tree()
        git_push(msg)
        log("DONE. Pushed to", REPO, "branch", BRANCH)
    except Exception as e:
        log("EXCEPTION:", repr(e))
    finally:
        try:
            os.makedirs(DEST, exist_ok=True)
            with open(LOG, "w", encoding="utf-8") as f:
                f.write(_buf.getvalue())
        except Exception:
            pass

if __name__ == "__main__":
    main()
