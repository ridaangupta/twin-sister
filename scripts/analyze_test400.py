"""Pre-registered analysis for the test-set run (analysis/preregistration_test400.md).

    uv run python scripts/analyze_test400.py runs/<syn_test400_dialogue> runs/<syn_test400_baselines>

Written and committed before the test run. Every one of the 400 test problems counts: a problem
missing from a method's results (failed after retries) is scored as incorrect for that method.
Writes analysis/results/test400_report.md and prints it.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from math import comb
from pathlib import Path
from statistics import mean

from evals.baselines import majority_vote
from evals.datasets import load_jsonl

ROOT = Path(__file__).resolve().parent.parent
TEST = "evals/subsets/synthetic_test400.jsonl"
ALPHA = 0.05


def mcnemar_p(b: int, c: int) -> float:
    """Exact two-sided McNemar (binomial on discordant pairs)."""
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, j) for j in range(min(b, c) + 1)) / 2**n)


def boot_ci(diffs: list[float], n_boot: int = 10_000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    m = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(n_boot))
    return m[int(0.025 * n_boot)], m[int(0.975 * n_boot) - 1]


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Fisher exact test for [[a, b], [c, d]]."""
    r1, c1, n = a + b, a + c, a + b + c + d

    def p(x: int) -> float:
        return comb(c1, x) * comb(n - c1, r1 - x) / comb(n, r1)

    obs = p(a)
    lo, hi = max(0, r1 + c1 - n), min(r1, c1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs * (1 + 1e-9)))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    order = sorted(pvals, key=pvals.get)
    adj, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (len(order) - i) * pvals[k]))
        adj[k] = running
    return adj


def load_rows(run: Path) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in map(json.loads, (run / "problems.jsonl").read_text().splitlines()):
        out.setdefault(r["method"], {})[r["problem_id"]] = r
    return out


def main(dialogue_dir: str, baselines_dir: str, problem_set: str = TEST, out_name: str = "test400_report.md") -> str:
    problems = load_jsonl(problem_set)
    ids = [p.id for p in problems]
    level = {p.id: p.meta["n_ops"] for p in problems}
    gold = {p.id: p.gold for p in problems}
    rows = {**load_rows(Path(dialogue_dir)), **load_rows(Path(baselines_dir))}

    def correct(method: str) -> dict[str, float]:
        return {i: float(rows.get(method, {}).get(i, {}).get("correct", False)) for i in ids}

    acc = {m: correct(m) for m in ("dialogue", "self_consistency", "two_plus_judge", "cot", "direct")}
    # Equal-token SC (n=5): majority of the first five of the seven SC draws.
    sc = rows["self_consistency"]
    acc["sc5"] = {i: float(i in sc and majority_vote(sc[i]["sample_answers"][:5]) == gold[i]) for i in ids}
    missing = {m: sum(i not in rows.get(m, {}) for i in ids) for m in ("dialogue", "self_consistency", "two_plus_judge", "cot")}

    def compare(a: str, b: str, subset: list[str]) -> dict:
        diffs = [acc[a][i] - acc[b][i] for i in subset]
        a_only = sum(acc[a][i] == 1 and acc[b][i] == 0 for i in subset)
        b_only = sum(acc[b][i] == 1 and acc[a][i] == 0 for i in subset)
        return {"n": len(subset), "acc_a": mean(acc[a][i] for i in subset), "acc_b": mean(acc[b][i] for i in subset),
                "diff": mean(diffs), "ci": boot_ci(diffs), "a_only": a_only, "b_only": b_only, "p": mcnemar_p(a_only, b_only)}

    hard = [i for i in ids if level[i] == 16]
    primary = compare("dialogue", "self_consistency", ids)
    secondary = {
        "S1 dialogue vs two_plus_judge (all 400)": compare("dialogue", "two_plus_judge", ids),
        "S2 dialogue vs SC n=7 (16-step, 200)": compare("dialogue", "self_consistency", hard),
        "S3 dialogue vs SC n=5 equal tokens (all 400)": compare("dialogue", "sc5", ids),
        "S5 dialogue vs CoT (all 400)": compare("dialogue", "cot", ids),
    }
    adj = holm({k: v["p"] for k, v in secondary.items()})

    # S4 (descriptive): recovery when both first attempts are wrong.
    dlg, j = rows["dialogue"], rows["two_plus_judge"]
    d_both_wrong = [i for i in ids if i in dlg and all(dlg[i]["answer_trajectory"][min(1, len(dlg[i]["answer_trajectory"]) - 1)].get(a) != gold[i] for a in ("A", "B"))]
    j_both_wrong = [i for i in ids if i in j and all(a != gold[i] for a in j[i]["sample_answers"])]
    d_rec, j_rec = sum(acc["dialogue"][i] for i in d_both_wrong), sum(acc["two_plus_judge"][i] for i in j_both_wrong)
    s4_p = fisher_two_sided(int(d_rec), len(d_both_wrong) - int(d_rec), int(j_rec), len(j_both_wrong) - int(j_rec))

    def tok(m: str, k: str = "generated") -> float:
        return mean(r["tokens"][k] for r in rows[m].values())

    L = ["# Test-set results (pre-registered: analysis/preregistration_test400.md)", "",
         f"Dialogue run: `{dialogue_dir}`  ", f"Baselines run: `{baselines_dir}`  ",
         f"Problems: {len(ids)} ({Counter(level.values())[10]} at 10 steps, {Counter(level.values())[16]} at 16 steps). "
         f"Missing (scored incorrect): {missing}", "",
         "## Accuracy", "", "| method | all | 10 steps | 16 steps | generated tokens/problem |", "|---|---|---|---|---|"]
    names = {"dialogue": "dialogue", "self_consistency": "self-consistency n=7 (cost-matched)", "sc5": "self-consistency n=5 (token-matched)",
             "two_plus_judge": "two attempts + judge", "cot": "chain of thought", "direct": "direct answer"}
    for m, nm in names.items():
        t = f"{tok(m):.0f}" if m in rows else "(first 5 of the n=7 draws)" if m == "sc5" else "n/a"
        L.append(f"| {nm} | {mean(acc[m].values()):.3f} | {mean(acc[m][i] for i in ids if level[i] == 10):.3f} | "
                 f"{mean(acc[m][i] for i in hard):.3f} | {t} |")
    pr = primary
    verdict = "SUPPORTED" if pr["p"] < ALPHA and pr["diff"] > 0 else "NOT SUPPORTED"
    L += ["", "## Primary: dialogue vs cost-matched self-consistency (n=7), all 400", "",
          f"- dialogue {pr['acc_a']:.3f} vs SC {pr['acc_b']:.3f}; difference {pr['diff']:+.3f}, 95% CI [{pr['ci'][0]:+.3f}, {pr['ci'][1]:+.3f}]",
          f"- discordant: dialogue-only {pr['a_only']}, SC-only {pr['b_only']}; exact McNemar p = {pr['p']:.4f}",
          f"- **H1 (dialogue > SC at α = {ALPHA}, two-sided): {verdict}**", "",
          "## Secondary (Holm-adjusted across S1, S2, S3, S5)", "",
          "| comparison | n | dialogue | other | diff | 95% CI | dlg-only | other-only | p | Holm p |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in secondary.items():
        L.append(f"| {k} | {v['n']} | {v['acc_a']:.3f} | {v['acc_b']:.3f} | {v['diff']:+.3f} | [{v['ci'][0]:+.3f}, {v['ci'][1]:+.3f}] | "
                 f"{v['a_only']} | {v['b_only']} | {v['p']:.4f} | {adj[k]:.4f} |")
    L += ["", "## S4 (descriptive): recovery when both first attempts are wrong", "",
          f"- dialogue: both opening posts wrong on {len(d_both_wrong)} problems; final answer correct on {int(d_rec)} "
          f"({d_rec / max(len(d_both_wrong), 1):.0%})",
          f"- two attempts + judge: both attempts wrong on {len(j_both_wrong)}; judge correct on {int(j_rec)} "
          f"({j_rec / max(len(j_both_wrong), 1):.0%})",
          f"- Fisher exact p = {s4_p:.4f} (different problem subsets per method; descriptive only)", ""]
    report = "\n".join(L)
    out = ROOT / "analysis" / "results" / out_name
    out.write_text(report + "\n")
    return report


if __name__ == "__main__":
    # Optional 3rd/4th args (problem set, report name) exist only to dry-run the script on dev data.
    print(main(*sys.argv[1:5]))
