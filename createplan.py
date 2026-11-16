# createplan.py
# ============================================================
# Usage:
#   python3 createplan.py -t templates/example1.json
#   python3 createplan.py -t templates/example1.json -o plans/example.json
# ============================================================

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

PARAM_PATTERN = r"\{([A-Za-z_][A-Za-z0-9_]*)\}"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--template", required=True)
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    text = Path(args.template).read_text(encoding="utf-8")
    params = list(dict.fromkeys(re.findall(PARAM_PATTERN, text)))
    values = {}
    for param in params:
        while True:
            value = input(f"{param}:").strip()
            if value:
                # テンプレートは JSON 文字列の中に埋め込まれるため、" や \ をエスケープしてから置換する
                values[param] = json.dumps(value, ensure_ascii=False)[1:-1]
                break
            print("空です。入力してください。")
    text = re.sub(PARAM_PATTERN, lambda m: values[m.group(1)], text)
    try:
        plan = json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"plan のJSONが不正です: {e}")
    if args.output:
        output = Path(args.output)
    else:
        output = Path("plans") / f"{datetime.now():%Y%m%d_%H%M%S}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Plan created: {output}")

if __name__ == "__main__":
    main()
