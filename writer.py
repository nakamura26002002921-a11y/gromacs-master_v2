# ============================================================
# Usage:
#   python3 writer.py --input "XXX" -o "YYY"
# ============================================================

import argparse

p = argparse.ArgumentParser()
p.add_argument("--input")
p.add_argument("-o")
a = p.parse_args()

open(a.o, "a").write(a.input + "\n")
