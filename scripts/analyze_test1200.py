"""Pre-registered analysis for the visible-reasoning confirmatory run (analysis/preregistration_test1200.md).

    uv run python scripts/analyze_test1200.py runs/<syn_test1200_dialogue> runs/<syn_test1200_baselines> runs/<syn_test1200_self_refine>

Written and committed before the run. All 1,200 problems count; a problem missing from a method's
results (failed after retries) is scored incorrect for that method. Writes
analysis/results/test1200_report.md and prints it. Optional 4th/5th args (problem set, report name)
exist only to dry-run on dev data.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_test400 import boot_ci, fisher_two_sided, holm, mcnemar_p  # noqa: E402
from match_cost import call_cost  # noqa: E402

from evals.datasets import load_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEST = "evals/subsets/synthetic_test1200.jsonl"
ALPHA = 0.05
DRIFT = 0.05  # realized cost ratio outside 1 +- DRIFT is reported as a deviation

# label -> (method name in problems.jsonl, pre-registered predicted direction of dialogue minus it)
PRIMARY = {
    "self_consistency": ("self_consistency", "+"),
    "k_plus_judge": ("k_plus_judge", "+"),
    "self_refine": ("self_refine_redraft", "+"),
    "reasoning": ("reasoning", "-"),
}


def load_rows(run: Path) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in map(json.loads, (run / "problems.jsonl").read_text().splitlines()):
        out.setdefault(r["method"], {})[r["problem_id"]] = r
    return out


def costs(run: Path) -> dict[str, float]:
    pricing = yaml.safe_load((run / "config.yaml").read_text())["pricing"]
    total: Counter = Counter()
    probs: dict[str, set] = {}
    for c in map(json.loads, (run / "calls.jsonl").read_text().splitlines()):
        total[c["method"]] += call_cost(c, pricing)
        probs.setdefault(c["method"], set()).add(c["problem_id"])
    return {m: total[m] / len(probs[m]) for m in total}


def main(*runs: str, problem_set: str = TEST, out_name: str = "test1200_report.md") -> str:
    problems = load_jsonl(problem_set)
    ids = [p.id for p in problems]
    level = {p.id: p.meta["n_ops"] for p in problems}
    gold = {p.id: p.gold for p in problems}
    rows: dict[str, dict] = {}
    cost: dict[str, float] = {}
    for r in runs:
        rows.update(load_rows(Path(r)))
        cost.update(costs(Path(r)))

    def acc(m: str) -> dict[str, float]:
        return {i: float(rows.get(m, {}).get(i, {}).get("correct", False)) for i in ids}

    A = {m: acc(m) for m in rows}
    missing = {m: sum(i not in rows[m] for i in ids) for m in rows}

    def compare(a: str, b: str, subset: list[str]) -> dict:
        diffs = [A[a][i] - A[b][i] for i in subset]
        a_only = sum(A[a][i] == 1 and A[b][i] == 0 for i in subset)
        b_only = sum(A[b][i] == 1 and A[a][i] == 0 for i in subset)
        return {"n": len(subset), "acc_a": mean(A[a][i] for i in subset), "acc_b": mean(A[b][i] for i in subset),
                "diff": mean(diffs), "ci": boot_ci(diffs), "a_only": a_only, "b_only": b_only, "p": mcnemar_p(a_only, b_only)}

    hard = [i for i in ids if level[i] == 16]
    prim = {k: compare("dialogue", m, ids) for k, (m, _) in PRIMARY.items()}
    padj = holm({k: v["p"] for k, v in prim.items()})
    sec = {f"{k}, 16 steps": compare("dialogue", m, hard) for k, (m, _) in PRIMARY.items()}
    sec["cot, all"] = compare("dialogue", "cot", ids)
    sadj = holm({k: v["p"] for k, v in sec.items()})

    def verdict(k: str) -> str:
        d, sign = prim[k]["diff"], PRIMARY[k][1]
        if padj[k] >= ALPHA:
            return "no significant difference"
        return ("SUPPORTED (dialogue higher)" if d > 0 else "REVERSED (dialogue lower)") if sign == "+" else \
               ("SUPPORTED (dialogue lower, as predicted)" if d < 0 else "REVERSED (dialogue higher)")

    tgt = cost["dialogue"]
    L = ["# Visible-reasoning confirmatory results (pre-registered: analysis/preregistration_test1200.md)", "",
         "Runs: " + ", ".join(f"`{Path(r).name}`" for r in runs) + "  ",
         f"Problems: {len(ids)} ({Counter(level.values())[10]} at 10 steps, {Counter(level.values())[16]} at 16 steps). "
         f"Missing (scored incorrect): {missing}", "",
         "## Accuracy, tokens and realized cost", "",
         "| method | all | 10 steps | 16 steps | generated tokens/problem | $/problem | cost ratio to dialogue |", "|---|---|---|---|---|---|---|"]
    for m in ["dialogue"] + [v[0] for v in PRIMARY.values()] + ["cot", "direct"]:
        if m not in rows:
            continue
        gen = mean(r["tokens"]["generated"] for r in rows[m].values())
        ratio = cost[m] / tgt
        flag = " (drift)" if m != "dialogue" and m in dict(PRIMARY.values()) and abs(ratio - 1) > DRIFT else ""
        L.append(f"| {m} | {mean(A[m].values()):.3f} | {mean(A[m][i] for i in ids if level[i] == 10):.3f} | "
                 f"{mean(A[m][i] for i in hard):.3f} | {gen:.0f} | {cost[m]:.5f} | {ratio:.3f}{flag} |")
    L += ["", "## Primary family: dialogue vs each cost-matched baseline, all 1,200 (Holm, α = 0.05, two-sided)", "",
          "| comparison | predicted | dialogue | other | diff | 95% CI | dlg-only | other-only | p | Holm p | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in prim.items():
        L.append(f"| dialogue vs {k} | dialogue {'higher' if PRIMARY[k][1] == '+' else 'lower'} | {v['acc_a']:.3f} | {v['acc_b']:.3f} | "
                 f"{v['diff']:+.3f} | [{v['ci'][0]:+.3f}, {v['ci'][1]:+.3f}] | {v['a_only']} | {v['b_only']} | {v['p']:.4g} | "
                 f"{padj[k]:.4g} | **{verdict(k)}** |")
    L += ["", "## Secondary family (Holm within the family)", "",
          "| comparison | n | dialogue | other | diff | 95% CI | p | Holm p |", "|---|---|---|---|---|---|---|---|"]
    for k, v in sec.items():
        L.append(f"| dialogue vs {k} | {v['n']} | {v['acc_a']:.3f} | {v['acc_b']:.3f} | {v['diff']:+.3f} | "
                 f"[{v['ci'][0]:+.3f}, {v['ci'][1]:+.3f}] | {v['p']:.4g} | {sadj[k]:.4g} |")

    # Descriptive: opening disagreement (WS1 hypotheses), now on fresh data.
    dlg = rows["dialogue"]
    same = diff_ = rs = rd = 0
    for i in ids:
        if i not in dlg:
            continue
        traj = dlg[i]["answer_trajectory"]
        o = traj[min(1, len(traj) - 1)]
        a, b = o.get("A"), o.get("B")
        if a != gold[i] and b != gold[i]:
            if a is not None and a == b:
                same += 1
                rs += dlg[i]["correct"]
            else:
                diff_ += 1
                rd += dlg[i]["correct"]
    p_same_diff = fisher_two_sided(rs, same - rs, rd, diff_ - rd) if same and diff_ else float("nan")
    L += ["", "## Descriptive: both openings wrong, same vs different answers (WS1 hypothesis on fresh data)", "",
          f"- same wrong answer: {same} problems, recovered {rs} ({rs / max(same, 1):.0%})",
          f"- different wrong answers (or none): {diff_} problems, recovered {rd} ({rd / max(diff_, 1):.0%})",
          f"- Fisher exact p = {p_same_diff:.4g} (descriptive; the WS5 ablation set carries the pre-registered test)", ""]
    report = "\n".join(L)
    (ROOT / "analysis" / "results" / out_name).write_text(report + "\n")
    return report


if __name__ == "__main__":
    args = sys.argv[1:]
    kw = {}
    if args and args[-1].endswith(".md"):
        kw["out_name"] = args.pop()
    if args and args[-1].endswith(".jsonl"):
        kw["problem_set"] = args.pop()
    print(main(*args, **kw))
