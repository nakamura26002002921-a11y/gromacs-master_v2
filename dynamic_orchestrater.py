# dynamic_orchestrater.py
# ============================================================
# Usage:
#   python3 dynamic_orchestrater.py -p plan.json --recovery-url https://... --test-env /tmp/recovery_env
#   python3 dynamic_orchestrater.py -p plan.json -s nvt -e npt_pr
#   python3 dynamic_orchestrater.py -p plan.json -ep /path/to/workdir --test-env ./child_env
#   python3 dynamic_orchestrater.py -p plan.json --history histories/test.json -l logs/test.json
#   python3 dynamic_orchestrater.py -p plan.json --depth 5 --branch 5 --population 4 --max-recoveries 10
# ============================================================

import argparse
import json
import math
import random
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

ARCHIVE, UCB_C, SIM_THRESHOLD, ARCHIVE_SIZE, LAMBDA = [], 1.0, 0.95, 40, 10.0

# テスト環境コピー時に持ち込まないもの(回復の残骸や別テスト環境)
COPY_IGNORE = shutil.ignore_patterns(
    "_sandbox", "*_testenv", "test_env*", "histories", "logs",
    "__pycache__", "recovery_*.json", "recovery_result_*.json",
)


def embed(text):
    words = text.split()
    counts = {w: words.count(w) for w in set(words)}
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1
    return {k: v / norm for k, v in counts.items()}


def similarity(a, b):
    return sum(v * embed(b).get(k, 0) for k, v in embed(a).items())


def novel(command):
    return all(similarity(command, e["実行コマンド"]) <= SIM_THRESHOLD for e in ARCHIVE)


def niche(command):
    return sum(1 for e in ARCHIVE if similarity(command, e["実行コマンド"]) > SIM_THRESHOLD)


def archive(entry):
    if len(ARCHIVE) < ARCHIVE_SIZE:
        ARCHIVE.append(entry)
        return
    ARCHIVE.sort(key=lambda e: e["スコア"])
    if entry["スコア"] > ARCHIVE[0]["スコア"] or novel(entry["実行コマンド"]):
        ARCHIVE[0] = entry


def parents(k):
    if not ARCHIVE:
        return []
    median = sorted(e["スコア"] for e in ARCHIVE)[len(ARCHIVE) // 2]
    weights = []
    for e in ARCHIVE:
        fitness = 1 / (1 + math.exp(-LAMBDA * (e["スコア"] - median)))
        rarity = 1 / (1 + niche(e["実行コマンド"]))
        weights.append(fitness * rarity / (1 + e.get("子孫数", 0)))
    return random.choices(ARCHIVE, weights=weights, k=k)


def make_test_env(exec_path, test_env_arg):
    if test_env_arg:
        dst = Path(test_env_arg).expanduser().resolve()
        if dst.is_relative_to(exec_path.parent) and dst != exec_path.parent:
            raise ValueError("--test-env は実行パスの親ディレクトリの外側を指定してください")
        if dst.exists():
            return dst
    else:
        dst = exec_path.parent / f"{exec_path.name or 'workdir'}_testenv"
        if dst.exists():
            return dst
    shutil.copytree(exec_path.parent, dst, ignore=COPY_IGNORE)
    return dst


def refresh_test_dir(exec_path, test_cwd):
    if test_cwd.exists():
        shutil.rmtree(test_cwd)
    shutil.copytree(exec_path, test_cwd, ignore=COPY_IGNORE)


def run(node, plan, path, extra=None):
    step = plan[node]
    proc = subprocess.run(step["実行コマンド"], shell=True, cwd=path, capture_output=True, text=True)
    entry = {"ノード": node, "実行コマンド": step["実行コマンド"], "目的": step["目的"],
             "出力": proc.stdout, "エラー": proc.stderr, "終了コード": proc.returncode,
             "スコア": int(proc.returncode == 0), "子孫数": 0, "実行パス": str(path)}
    if extra:
        entry.update(extra)
    return entry


def steps(data):
    return data.get("回復手順", list(data.get("plan", {}).values()))


def recovery(node, result, plan, history, workdir, url, generation):
    rid = str(uuid.uuid4())
    data = {"id": rid, "ノード": node, "実行コマンド": result["実行コマンド"], "目的": result["目的"],
            "出力": result["出力"], "エラー": result["エラー"], "終了コード": result["終了コード"],
            "plan": plan, "history": history, "archive": ARCHIVE[-10:],
            "探索": {"方式": "shinka_evolve", "世代": generation}}
    request = workdir / f"recovery_{rid}.json"
    result_path = workdir / f"recovery_result_{rid}.json"
    request.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(f"curl -sS -X POST -F 'file=@{request}' '{url}/upload'",
                   shell=True, cwd=workdir, capture_output=True, text=True)
    result_url = urljoin(f"{url}/", f"result/{rid}.json")
    for _ in range(180):  # 最大 30 分ポーリング
        subprocess.run(f"wget -q -O '{result_path}' '{result_url}'",
                       shell=True, cwd=workdir, capture_output=True, text=True)
        if result_path.exists() and result_path.stat().st_size > 0:
            try:
                recovered = json.loads(result_path.read_text(encoding="utf-8"))
                request.unlink(missing_ok=True)
                return recovered
            except json.JSONDecodeError:
                pass
        time.sleep(10)
    raise TimeoutError(f"recovery result timeout: {rid}")


def evaluate_group(group, gen, failed_node, exec_path, test_cwd, test_env, history):
    refresh_test_dir(exec_path, test_cwd)
    for step in group:
        node = step.get("ノード", f"cand_{uuid.uuid4().hex[:8]}")
        cand_plan = {node: {"実行コマンド": step["実行コマンド"], "目的": step["目的"], "次のノード": node}}
        entry = run(node, cand_plan, test_cwd,
                    extra={"世代": gen, "探索方式": "shinka_evolve", "回復対象": failed_node,"テスト環境": str(test_env), "評価": "テスト"})
        archive(entry)
        history.append(entry)
        if entry["終了コード"] != 0:
            return False
    return True


def evolve_recovery(failed_node, result, plan, history, exec_path, test_env, url, population, generations, branch):
    test_cwd = test_env / exec_path.name
    seen = set()
    for gen in range(generations):
        mutants = []
        for p in (parents(population) or [result]):
            try:
                recovered = recovery(p["ノード"], p, plan, history, test_env, url, gen)
            except Exception:
                continue
            group = []
            for s in steps(recovered):
                cmd = s["実行コマンド"]
                if cmd in seen or not novel(cmd):
                    continue
                seen.add(cmd)
                group.append(s)
            if group:
                mutants.append(group)
        random.shuffle(mutants)
        for group in mutants[:branch]:
            if evaluate_group(group, gen, failed_node, exec_path, test_cwd, test_env, history):
                return group
    return None


def merge_fix_into_plan(plan, failed_node, fix_steps):
    ids = [f"fix_{uuid.uuid4().hex[:8]}" for _ in fix_steps]
    for i, (node_id, step) in enumerate(zip(ids, fix_steps)):
        nxt = ids[i + 1] if i + 1 < len(ids) else failed_node
        plan[node_id] = {"実行コマンド": step["実行コマンド"], "目的": step["目的"],"次のノード": nxt, "修復": True}
    prev = next((n for n, s in plan.items() if s.get("次のノード") == failed_node and n not in ids), None)
    if prev is not None:
        plan[prev]["次のノード"] = ids[0]
    return ids[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", "--plan", required=True)
    p.add_argument("--history")
    p.add_argument("-l", "--logpath")
    p.add_argument("-s", "--start")
    p.add_argument("-e", "--end")
    p.add_argument("-ep", "--executionpath")
    p.add_argument("--recovery-url", default="")
    p.add_argument("--test-env", default="",help="エラー回復のテスト環境。未指定 or 未存在なら実行パスの親ディレクトリのコピーで作成")
    p.add_argument("--depth", type=int, default=5, help="進化の世代数")
    p.add_argument("--branch", type=int, default=5, help="1 世代あたりに評価する候補群の最大数")
    p.add_argument("--population", type=int, default=3, help="1 世代あたりの親個体数")
    p.add_argument("--max-recoveries", type=int, default=10, help="1 ノードあたりの最大回復試行回数")
    args = p.parse_args()

    plan_path = Path(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = plan_path.stem
    history_path = Path(args.history or f"histories/{name}_{now}.json")
    log_path = Path(args.logpath or f"logs/{name}_{now}.json")
    exec_path = Path(args.executionpath or ".").resolve()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    test_env = make_test_env(exec_path, args.test_env) if args.recovery_url else None

    node, end, history, recoveries = args.start or next(iter(plan)), args.end or next(reversed(plan)), [], {}
    while True:
        result = run(node, plan, exec_path)
        archive(result)
        history.append(result)
        if result["終了コード"] != 0:
            recoveries[node] = recoveries.get(node, 0) + 1
            group = None
            if args.recovery_url and recoveries[node] <= args.max_recoveries:
                group = evolve_recovery(node, result, plan, history, exec_path, test_env, args.recovery_url, args.population, args.depth, args.branch)
            if not group:
                break
            history.append({"修復適用": True, "回復対象": node, "世代探索": "shinka_evolve",
                            "修復コマンド群": [{"実行コマンド": s["実行コマンド"], "目的": s["目的"]} for s in group],
                            "時刻": datetime.now().isoformat()})
            node = merge_fix_into_plan(plan, node, group)  # メインの plan に復帰
            continue

        if node == end:
            break

        for entry in ARCHIVE:
            if entry["実行コマンド"] == result["実行コマンド"]:
                entry["子孫数"] += 1
                break
        node = plan[node]["次のノード"]

    payload = json.dumps(history, ensure_ascii=False, indent=2)
    history_path.write_text(payload, encoding="utf-8")
    log_path.write_text(payload, encoding="utf-8")
    fixed_plan_path = history_path.with_name(f"{history_path.stem}_fixed_plan.json")
    fixed_plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
