import subprocess, os
LOG=os.path.join(os.path.dirname(os.path.abspath(__file__)),"dump_gitlog_log.txt")
EDEV=r"E:\Startup\magicbridge-pikvm"
out=subprocess.run(["git","-C",EDEV,"log","--oneline","--all","--no-decorate"],capture_output=True,text=True)
open(LOG,"w",encoding="utf-8").write(out.stdout+out.stderr)
print("done")
