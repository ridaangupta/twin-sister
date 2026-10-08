"""WS1 exploratory analyses of existing dialogue logs (docs/PLAN_v2.md). No API calls.

    uv run python scripts/explore_logs.py runs/<dialogue run> [runs/<dialogue run> ...] [--sample 60]

For each dialogue run:
  1a  "both openings wrong", split by same vs different wrong answers, with recovery rates
  1b  direction of every answer switch (to correct / away from correct / wrong to wrong)
  1c  each agent's first numeric error, classified against the regenerated ground-truth graph,
      and whether it was corrected later in the thread

Writes analysis/results/exploratory_v1.md plus a hand-labelling sample
(analysis/results/error_validation_sample.md). All results are exploratory: these sets were
already used for confirmatory or development work.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from evals.datasets import load
from evals.synthetic import FRACTIONS, Synthetic, apply, generate

ROOT = Path(__file__).resolve().parent.parent
KNOBS = ("n_ops", "n_distractors", "n_reverse", "p_total", "shuffle", "max_value")

# ------------------------------------------------------------------ ground truth


def regenerate(meta: dict) -> Synthetic:
    return generate(meta["seed"], **{k: meta[k] for k in KNOBS})


def hidden_leaves(p: Synthetic) -> set[int]:
    stated = {s.node for s in p.statements if s.kind == "leaf"}
    return {i for i, n in p.nodes.items() if n.op is None and i not in stated}


def true_total(p: Synthetic, owner: str) -> int:
    return sum(n.value for n in p.nodes.values() if n.owner == owner)


# ------------------------------------------------------------------ claim extraction

_NUM = r"-?\d+(?:\.\d+)?"


def normalize(text: str) -> str:
    t = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)
    t = re.sub(r"\\boxed\{([^{}]*)\}|\\text\{([^{}]*)\}", lambda m: m.group(1) or m.group(2) or "", t)
    for a, b in (("\\(", " "), ("\\)", " "), ("\\[", " "), ("\\]", " "), ("\\times", "×"), ("\\cdot", "×"),
                 ("\\div", "÷"), ("\\$", "$"), ("\\,", ""), ("’", "'"), ("$", "")):
        t = t.replace(a, b)
    return t


@dataclass
class Claim:
    key: tuple  # ("node", id) or ("total", owner)
    value: float
    pos: int
    snippet: str = ""


def label_patterns(p: Synthetic) -> list[tuple[tuple, re.Pattern]]:
    pats = []
    for i, n in p.nodes.items():
        item, owner = re.escape(n.item), re.escape(n.owner)
        alts = [rf"(?:the )?number of {item} {owner} has", rf"{owner}'s {item}", rf"{item} {owner}\b", rf"{item} \({owner}\)"]
        pats.append((("node", i), re.compile(rf"\b(?:{'|'.join(alts)})", re.I)))
        pats.append((("node_has", i), re.compile(rf"\b{owner} has ({_NUM}) {item}\b", re.I)))
    for owner in {n.owner for n in p.nodes.values()}:
        o = re.escape(owner)
        alts = [rf"(?:the )?total(?: number of items| items)? {o}(?: has)?", rf"{o}'s total(?: number of items| items)?"]
        pats.append((("total", owner), re.compile(rf"\b(?:{'|'.join(alts)})", re.I)))
    return pats


_CLAUSE_START = re.compile(r"[\n;,:(“”\"]|\.\s|\b(?:and|so|then|thus|hence|since|because|which|but|while)\b")
_OPERATOR = re.compile(r"[=+×*/÷−]|\s-\s|\d\s*-|\b(?:times|plus|minus|of|than|half|sum|product|difference|divided|multiplied|over)\b", re.I)


def is_subject(t: str, start: int) -> bool:
    """A label is a claim's subject only on the left of its clause: no operator between clause start and label."""
    head = t[max(0, start - 200):start]
    starts = list(_CLAUSE_START.finditer(head))
    prefix = head[starts[-1].end():] if starts else head
    prefix = re.sub(r"^[\s\-*•]+", "", prefix)  # a list bullet is not an operator
    return not _OPERATOR.search(prefix)


_SEG_END = re.compile(r"[;\n,“”\"]|\.\s|\.$|\b(?:so|then|while|thus|hence|and|since|because|which|but)\b")
_ASSIGN = re.compile(rf"^\s*(?:=|:|is|are|equals)\s*(.*)$", re.I)


def extract_claims(text: str, pats) -> list[Claim]:
    t = normalize(text)
    claims: list[Claim] = []
    for key, pat in pats:
        for m in pat.finditer(t):
            if key[0] == "node_has":
                claims.append(Claim(("node", key[1]), float(m.group(1)), m.start(), t[max(0, m.start() - 60):m.end() + 60]))
                continue
            if not is_subject(t, m.start()):
                continue
            rest = t[m.end():]
            end = _SEG_END.search(rest)
            seg = rest[: end.start()] if end else rest
            a = _ASSIGN.match(seg)
            if not a:
                continue
            # A value claim ends in arithmetic: "= 271 - 8 = 263", or just "= 263". Words may appear earlier
            # ("= Ruby's hats - Hugo's cups = 271 - 8 = 263") but not in the last two steps.
            pieces = a.group(1).split("=")
            words = lambda x: re.search(r"[A-Za-z]{2,}", x)  # noqa: E731
            if words(pieces[-1]):
                continue
            if len(pieces) > 1 and words(pieces[-2]) and re.search(r"\d", pieces[-2]):
                continue  # numbers mixed with words right before the value: an unresolved expression
            tail = pieces[-1]
            num = re.fullmatch(rf"\s*({_NUM})\s*[.)\]]*\s*", tail)
            if num:
                claims.append(Claim(key, float(num.group(1)), m.start(), t[max(0, m.start() - 60):m.end() + len(seg) + 10]))
    return sorted(claims, key=lambda c: c.pos)


# ------------------------------------------------------------------ classification


def misread_alternatives(op: str, args: list[int], const: int | None) -> set[float]:
    """Values produced by plausible misreadings of a relation (direction, inverse, swapped operands)."""
    a = args[0]
    alts: set[float] = set()
    if op == "add_c":
        alts |= {a - const}
    elif op == "sub_c":
        alts |= {a + const}
    elif op == "mul_c":
        alts |= {a / const, a + const}
    elif op == "div_c":
        alts |= {a * const, a - const}
        alts |= {a / k for k in FRACTIONS if k != const}
    elif op == "sub":
        alts |= {args[1] - args[0], args[0] + args[1]}
    elif op == "add":
        alts |= {abs(args[0] - args[1])}
    elif op == "mul":
        alts |= {args[0] + args[1]}
    return alts


def classify(p: Synthetic, hidden: set[int], node_id: int, wrong: float, known: dict) -> str:
    """Type of the agent's first wrong claim. `known` = the agent's own earlier claims (key -> value)."""
    n = p.nodes[node_id]
    if n.distractor:
        return "distractor value (harmless)"
    if node_id in hidden:
        return "backward step"
    if n.op is None:
        return "misread given value"
    if any(r.is_total for r in n.args):
        r = next(r for r in n.args if r.is_total)
        claimed = known.get(("total", r.owner))
        if claimed is not None and claimed != true_total(p, r.owner):
            return "implicit total"
    true_args = [true_total(p, r.owner) if r.is_total else p.nodes[r.node].value for r in n.args]
    if wrong in misread_alternatives(n.op, true_args, n.const):
        return "misread relation"
    # operand swapped for another quantity (a distractor, or the wrong core quantity)
    for other in p.nodes.values():
        if other.id == node_id or (len(n.args) == 1 and not n.args[0].is_total and other.id == n.args[0].node):
            continue
        try:
            if n.op in ("add_c", "sub_c", "mul_c", "div_c") and apply(n.op, [other.value], n.const) == wrong:
                return "distractor used as operand" if other.distractor else "wrong operand"
        except ValueError:
            continue
    if any(r.is_total for r in n.args):
        return "implicit total"
    return "arithmetic or unexplained"


# ------------------------------------------------------------------ per-run analysis


def analyse(run: Path) -> dict:
    meta = json.loads((run / "meta.json").read_text())
    problems = {q.id: q for q in load(meta["resolved_config"]["dataset"])}
    rows = {r["problem_id"]: r for r in map(json.loads, (run / "problems.jsonl").read_text().splitlines())}
    posts = defaultdict(list)
    for c in map(json.loads, (run / "calls.jsonl").read_text().splitlines()):
        if c["space"] == "core":
            posts[c["problem_id"]].append((c["turn"], c["agent"], c["response"]))

    both = Counter()
    switches = Counter()
    errors = Counter()
    caught = Counter()
    examples: list[dict] = []
    extraction = Counter()

    for pid, r in rows.items():
        q = problems[pid]
        gold = r["gold"]
        traj = r["answer_trajectory"]
        o = traj[min(1, len(traj) - 1)]
        a, b = o.get("A"), o.get("B")
        if a != gold and b != gold:
            kind = "same wrong answer" if a is not None and a == b else "different wrong answers (or none)"
            both[(kind, r["correct"])] += 1

        prev: dict = {}
        for step in traj:
            for ag, ans in step.items():
                if ans is not None and prev.get(ag) not in (None, ans):
                    d = "to correct" if ans == gold else "away from correct" if prev[ag] == gold else "wrong to wrong"
                    switches[(ag, d)] += 1
            prev = {k: (v if v is not None else prev.get(k)) for k, v in step.items()}

        # 1c: first numeric error per agent
        p = regenerate(q.meta)
        hidden = hidden_leaves(p)
        pats = label_patterns(p)
        thread = sorted(posts[pid])
        per_post_claims = [(t, ag, extract_claims(txt, pats), txt) for t, ag, txt in thread]
        extraction["posts"] += len(per_post_claims)
        extraction["posts with claims"] += sum(bool(c) for _, _, c, _ in per_post_claims)
        extraction["claims"] += sum(len(c) for _, _, c, _ in per_post_claims)
        for agent in ("A", "B"):
            known: dict = {}
            first = None
            for t, ag, claims, txt in per_post_claims:
                if ag != agent:
                    continue
                for c in claims:
                    truth = true_total(p, c.key[1]) if c.key[0] == "total" else p.nodes[c.key[1]].value
                    if c.value != truth and first is None:
                        if c.key[0] == "total":
                            first = (t, None, c.value, "implicit total", txt, c.key[1], c.snippet)
                        else:
                            first = (t, c.key[1], c.value, classify(p, hidden, c.key[1], c.value, known), txt, None, c.snippet)
                    known[c.key] = c.value
                if first:
                    break
            if not first:
                continue
            t, node_id, wrong, kind, txt, owner, snippet = first
            errors[kind] += 1
            key = ("total", owner) if node_id is None else ("node", node_id)
            truth = true_total(p, owner) if node_id is None else p.nodes[node_id].value
            fixer = None
            for t2, ag2, claims2, _ in per_post_claims:
                if t2 > t and any(c.key == key and c.value == truth for c in claims2):
                    fixer = "partner" if ag2 != agent else "self"
                    break
            status = f"corrected by {fixer}" if fixer else "never corrected in thread"
            caught[(kind, status)] += 1
            caught[(kind, "final answer correct" if r["correct"] else "final answer wrong")] += 1
            label = f"total items {owner}" if node_id is None else f"{p.nodes[node_id].item} {p.nodes[node_id].owner}"
            examples.append({"run": run.name, "problem": pid, "turn": t, "agent": agent, "quantity": label, "claimed": wrong,
                             "true": truth, "auto_type": kind, "status": status, "post": txt, "snippet": snippet.replace("\n", " | ")})
    return {"run": run.name, "name": meta["name"], "n": len(rows), "both": both, "switches": switches, "errors": errors,
            "caught": caught, "examples": examples, "extraction": extraction}


# ------------------------------------------------------------------ report


def table(header: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--sample", type=int, default=60)
    args = ap.parse_args()
    results = [analyse(Path(r)) for r in args.runs]

    L = ["# Exploratory analyses of existing dialogue logs (WS1)", "",
         "**Exploratory.** These runs were already used for development or confirmation, so the results below generate "
         "hypotheses for later pre-registered sets; they confirm nothing. Produced by `scripts/explore_logs.py`.", ""]
    for res in results:
        n = res["n"]
        L += [f"## {res['name']} (`{res['run']}`, {n} problems)", "", "### 1a. Both opening posts wrong", ""]
        rows = []
        for kind in ("same wrong answer", "different wrong answers (or none)"):
            tot = res["both"][(kind, True)] + res["both"][(kind, False)]
            rec = res["both"][(kind, True)]
            rows.append([kind, tot, rec, f"{rec / tot:.0%}" if tot else "–"])
        L += table(["openings", "problems", "final answer correct", "recovery"], rows) + [""]

        L += ["### 1b. Direction of answer switches", ""]
        rows = []
        for ag in ("A", "B"):
            s = {d: res["switches"][(ag, d)] for d in ("to correct", "away from correct", "wrong to wrong")}
            rows.append([ag, s["to correct"], s["away from correct"], s["wrong to wrong"], sum(s.values())])
        tot = [sum(res["switches"][(ag, d)] for ag in "AB") for d in ("to correct", "away from correct", "wrong to wrong")]
        rows.append(["both", *tot, sum(tot)])
        L += table(["agent", "to correct", "away from correct", "wrong to wrong", "total"], rows) + [""]

        ex = res["extraction"]
        L += ["### 1c. First numeric error per agent, by type", "",
              f"Claim extraction: {ex['claims']} value claims from {ex['posts with claims']}/{ex['posts']} posts. "
              "An agent with no wrong claim, or whose working could not be parsed, has no row.", ""]
        rows = []
        for kind, cnt in res["errors"].most_common():
            c = res["caught"]
            rows.append([kind, cnt, c[(kind, "corrected by partner")], c[(kind, "corrected by self")],
                         c[(kind, "never corrected in thread")], c[(kind, "final answer correct")]])
        L += table(["error type", "agents", "corrected by partner", "corrected by self", "never corrected", "final answer correct"], rows) + [""]

    L += ["## Notes on method", "",
          "- 1a uses the answers after the first round (turn 1). \"Different wrong answers\" includes an opening with no answer.",
          "- 1b counts every change of an agent's stated answer between its own posts; gaps with no answer are skipped.",
          "- 1c regenerates each problem's hidden graph from its seed, extracts claims of the form `label = … = value` "
          "(LaTeX and prose forms), takes each agent's first claim that differs from the true value, and classifies it: "
          "backward step (a hidden leaf), misread given value, implicit total, misread relation (matches a plausible misreading), "
          "distractor or wrong operand (matches the relation applied to another quantity), else arithmetic or unexplained. "
          "Distractor values are wrong but harmless. Corrected = a later post states the true value for that quantity.",
          f"- Validation: `analysis/results/error_validation_sample.md` holds a random {args.sample} classified errors for hand labelling.",
          ""]
    out = ROOT / "analysis" / "results" / "exploratory_v1.md"
    out.write_text("\n".join(L) + "\n")

    pool = [e for res in results for e in res["examples"]]
    sample = random.Random(0).sample(pool, min(args.sample, len(pool)))
    V = ["# Error classification: hand-labelling sample", "",
         "For each case, read the post and fill `your label` with one of: backward step, misread given value, implicit total, "
         "misread relation, distractor used as operand, wrong operand, arithmetic, extraction error (the claim was misread "
         "by the script), other. Agreement with `auto type` is the classifier's validation.", ""]
    for i, e in enumerate(sample, 1):
        V += [f"## {i}. {e['problem']} · turn {e['turn']} · agent {e['agent']}", "",
              f"- quantity: **{e['quantity']}**, claimed {e['claimed']:g}, true {e['true']:g}",
              f"- auto type: {e['auto_type']}; {e['status']}", f"- read from: `…{e['snippet'].strip()}…`", "- your label: ", "",
              "<details><summary>full post</summary>", "", "```", e["post"].strip(), "```", "", "</details>", ""]
    (ROOT / "analysis" / "results" / "error_validation_sample.md").write_text("\n".join(V) + "\n")
    print(out.read_text())


if __name__ == "__main__":
    main()
