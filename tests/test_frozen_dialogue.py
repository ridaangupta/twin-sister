"""The dialogue's prompts are frozen for every confirmatory comparison (docs/PLAN_v2.md).

These hashes were taken from code verified to rebuild, byte for byte, all 239 prompts sent in
the pre-registered test400 run (25 problems checked). A failure means a change altered what the
frozen dialogue sends: revert it, or freeze a new dialogue config and re-pre-register.
"""

from dialogic.agents import Agent
from dialogic.llm import prompt_hash
from dialogic.memory import Memory, Post
from dialogic.prompts import PromptLibrary
from dialogic.synthesis import SingleWriter

P = PromptLibrary()
TRAILER = "ANSWER: 36\nSTANCE: agree\nCONSENSUS: no\nFACT+: one box holds 12 eggs"


def scenario():
    a = Agent("A", "B", "accuracy", None, P)
    b = Agent("B", "A", "skepticism", None, P)
    m = Memory("A box holds 12 eggs. How many eggs are in 3 boxes?", ["A", "B"])
    m.write_scratch("B", "B opening note", turn=1)
    m.write_scratch("A", "A opening note", turn=0)
    m.post(Post.from_text(0, "A", "A opening\n" + TRAILER))
    m.post(Post.from_text(1, "B", "B opening\n" + TRAILER.replace("FACT+: one box holds 12 eggs", "FACT_OK: F1")))
    m.write_scratch("A", "A note before turn 2")
    return {
        "A_open_private": a.scratch_messages(Memory(m.task, ["A", "B"]).view_for("A"), 200, 0, opening=True),
        "B_open_post": b.core_messages(Memory(m.task, ["A", "B"]).view_for("B"), 150, 1, opening=True),
        "A_turn2_private": a.scratch_messages(m.view_for("A"), 200, 2),
        "A_turn2_post": a.core_messages(m.view_for("A"), 300, 2),
        "B_turn3_post": b.core_messages(m.view_for("B"), 600, 3),
        "writer": SingleWriter(a).messages(m.core_view()),
    }


SNAPSHOT = {
    "A_open_private": "sha256:03c6c089a6a75e1c8e4d2679d9be78791e5b23a71fe40a061aa53eb824334991",
    "B_open_post": "sha256:80ef111eac6cd7927aa8ec3f24b01605c0e728294a04c3e9266ed0ae184e82cb",
    "A_turn2_private": "sha256:fd93d96331bf6cbc2c0bbc6f53325f42912465a7872bb12c56cdc9d30bc462bf",
    "A_turn2_post": "sha256:091d38c0c937f0794e494148a97766dc35c89409ae4fe38600df0e6ead36cf4a",
    "B_turn3_post": "sha256:757208d2d8d40c2db88e1de8aede848c58acc85fe9c1576fe1930439baf2d93e",
    "writer": "sha256:55b3ecb7eb209697af7e39a5d37d94c6a60f99a9b024442c146d8e78e8fd87b7"
}


def test_dialogue_prompts_are_frozen():
    got = {k: prompt_hash(v) for k, v in scenario().items()}
    assert got == SNAPSHOT
