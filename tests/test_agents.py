import pytest

from fakes import FakeLLM, trailer

from dialogic.agents import OPENING, Agent
from dialogic.llm import CallContext
from dialogic.memory import Memory, Post
from dialogic.prompts import BREAKPOINT_KEY, PromptLibrary, text_of
from dialogic.synthesis import SingleWriter, extract_final

PROMPTS = PromptLibrary()
CTX = CallContext("p", "dialogue", "A", "core", 0)


def agents(llm=None):
    llm = llm or FakeLLM(lambda *_: trailer())
    return Agent("A", "B", "accuracy", llm, PROMPTS), Agent("B", "A", "skepticism", llm, PROMPTS)


def blocks(messages):
    return messages[1]["content"]


def test_agents_differ_only_in_objective_block():
    a, b = agents()
    sa = a.system_prompt().replace(PROMPTS.objective("accuracy"), "<OBJ>")
    sb = b.system_prompt().replace(PROMPTS.objective("skepticism"), "<OBJ>")
    swapped = sb.replace("Agent A", "Agent <X>").replace("Agent B", "Agent A").replace("Agent <X>", "Agent B")
    assert sa == swapped and "<OBJ>" in sa


def test_message_layout_is_cacheable_prefix_then_volatile_tail():
    a, _ = agents()
    m = Memory("Q?", ["A", "B"])
    m.write_scratch("A", "note0")
    m.post(Post.from_text(0, "A", "p0\n" + trailer()))
    m.post(Post.from_text(1, "B", "p1\n" + trailer()))
    msgs = a.core_messages(m.view_for("A"), 300, turn=2)
    assert [x["role"] for x in msgs] == ["system", "user", "user"]
    bs = blocks(msgs)
    assert bs[0]["text"].startswith("PROBLEM:\nQ?") and bs[1]["text"].startswith("HOW TO WORK")
    assert [b["text"].split("\n")[0] for b in bs[2:]] == [
        "[Your private note, before your post for turn 0]",
        "[Turn 0 · Agent A (you)]",
        "[Turn 1 · Agent B]",
    ]
    assert all(BREAKPOINT_KEY in b for b in bs)
    assert isinstance(msgs[2]["content"], str) and "MODE: POST. Turn 2." in msgs[2]["content"]


def test_prefix_only_grows_between_turns():
    """Every block of an earlier call is an exact prefix of the later call's blocks (cache reuse)."""
    a, _ = agents()
    m = Memory("Q?", ["A", "B"])
    m.write_scratch("A", "n0")
    first = blocks(a.core_messages(m.view_for("A"), 300, turn=0))
    m.post(Post.from_text(0, "A", "p0\n" + trailer()))
    m.post(Post.from_text(1, "B", "p1\n" + trailer()))
    m.write_scratch("A", "n2")
    later = blocks(a.scratch_messages(m.view_for("A"), 200, turn=2))
    assert later[: len(first)] == first and len(later) == len(first) + 3


def test_private_and_post_modes_share_prefix_and_differ_in_tail():
    a, _ = agents()
    view = Memory("Q?", ["A", "B"]).view_for("A")
    post, private = a.core_messages(view, 300, turn=0), a.scratch_messages(view, 200, turn=0)
    assert post[:2] == private[:2]
    assert "MODE: POST" in post[2]["content"] and "about 300 tokens" in post[2]["content"]
    assert "MODE: PRIVATE WORK" in private[2]["content"] and "about 200 tokens" in private[2]["content"]
    assert "CONSENSUS: <yes | no>" not in post[2]["content"] + private[2]["content"]  # trailer spec lives in the cached instructions


def test_opening_line_only_on_openings():
    a, _ = agents()
    view = Memory("Q?", ["A", "B"]).view_for("A")
    assert OPENING in a.core_messages(view, 300, turn=0, opening=True)[2]["content"]
    assert OPENING not in a.core_messages(view, 300, turn=0)[2]["content"]


def test_all_templates_render_without_missing_values():
    with pytest.raises(KeyError):
        PROMPTS.render("turn_post", agreed_facts="x")


def test_agent_refuses_another_agents_view():
    a, _ = agents()
    with pytest.raises(ValueError):
        a.core_messages(Memory("Q?", ["A", "B"]).view_for("B"), 300, turn=0)


def test_writer_reads_core_only():
    a, _ = agents()
    m = Memory("Q?", ["A", "B"])
    m.write_scratch("A", "SECRET-NOTE")
    m.post(Post.from_text(0, "A", "p0\n" + trailer()))
    msgs = SingleWriter(a).messages(m.core_view())
    assert "SECRET-NOTE" not in text_of(msgs) and "[Turn 0 · Agent A]" in text_of(msgs)
    assert "Write exactly this format" in msgs[-1]["content"]


async def test_speak_parses_post_and_passes_hard_cap():
    llm = FakeLLM(lambda *_: ("cut off mid-sentence", "length"))
    a, _ = agents(llm)
    post, _c = await a.speak(Memory("Q?", ["A", "B"]).view_for("A"), 300, 600, CTX, turn=3)
    assert llm.calls[0].max_tokens == 600
    assert post.truncated and post.protocol_error and post.agent == "A" and post.turn == 3


@pytest.mark.parametrize(
    "text,expected",
    [
        ("SOLUTION:\n1. 3 boxes x 12 = 36\nANSWER: 36", ("36", 1)),
        ("SOLUTION:\n1. a\n2. b\n3) c\n\nANSWER: $1,200", ("1200", 3)),
        ("**SOLUTION:**\n1. a\n**ANSWER:** 7", ("7", 1)),
        ("no format, but the total is 42.", ("42", 0)),
        ("SOLUTION:\n1. nothing numeric\nANSWER: unknown", (None, 1)),
    ],
)
def test_extract_final(text, expected):
    answer, steps, _ = extract_final(text)
    assert (answer, steps) == expected


def test_parallel_openings_keep_each_agents_prefix_append_only():
    """B writes its opening note before seeing A's opening post; later calls must still extend B's earlier prefix."""
    _, b = agents()
    m = Memory("Q?", ["A", "B"])
    m.write_scratch("B", "B opening note", turn=1)  # written while the thread is still empty
    opening = blocks(b.core_messages(m.view_for("B"), 300, turn=1, opening=True))
    m.post(Post.from_text(0, "A", "A opening\n" + trailer()))
    m.post(Post.from_text(1, "B", "B opening\n" + trailer()))
    later = blocks(b.scratch_messages(m.view_for("B"), 200, turn=3))
    assert later[: len(opening)] == opening


def test_writer_marks_no_breakpoints():
    a, _ = agents()
    m = Memory("Q?", ["A", "B"])
    m.post(Post.from_text(0, "A", "p0\n" + trailer()))
    assert all(BREAKPOINT_KEY not in blk for blk in SingleWriter(a).messages(m.core_view())[1]["content"])
