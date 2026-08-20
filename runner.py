# ============================================================
# Usage:
#   python3 runner.py --cmd "XXX" --path "YYY" -o "ZZZ"
# ============================================================
import argparse, subprocess

p = argparse.ArgumentParser()
p.add_argument("--cmd")
p.add_argument("--path")
p.add_argument("-o")
a = p.parse_args()

subprocess.run(a.cmd, shell=True, cwd=a.path)
open(a.o, "a").write(a.cmd + "\n")
