import pytest

from fakes import FakeLLM, trailer

from dialogic.agents import Agent
from dialogic.llm import CallContext
from dialogic.memory import Memory, Post
from dialogic.prompts import PromptLibrary
from dialogic.synthesis import extract_final

PROMPTS = PromptLibrary()


def agents(llm=None):
    llm = llm or FakeLLM(lambda *_: trailer())
    return Agent("A", "B", "accuracy", llm, PROMPTS), Agent("B", "A", "simplicity", llm, PROMPTS)


def test_agents_differ_only_in_objective_block():
    a, b = agents()
    sa = a.system_prompt().replace(PROMPTS.objective("accuracy"), "<OBJ>")
    sb = b.system_prompt().replace(PROMPTS.objective("simplicity"), "<OBJ>")
    # Swapping the A/B labels must make the rest identical.
    swapped = sb.replace("Agent A", "Agent <X>").replace("Agent B", "Agent A").replace("Agent <X>", "Agent B")
    assert sa == swapped
    assert "<OBJ>" in sa


def test_all_templates_render_without_missing_values():
    a, _ = agents()
    view = Memory("Q?", ["A", "B"]).view_for("A")
    assert a.core_messages(view, 300)[1]["content"].count("about 300 tokens") == 1
    assert "about 200 tokens" in a.scratch_messages(view, 200)[1]["content"]
    with pytest.raises(KeyError):
        PROMPTS.render("core_turn", task="x")


def test_agent_refuses_another_agents_view():
    a, _ = agents()
    view_b = Memory("Q?", ["A", "B"]).view_for("B")
    with pytest.raises(ValueError):
        a.core_messages(view_b, 300)


def test_thread_marks_own_posts():
    a, b = agents()
    m = Memory("Q?", ["A", "B"])
    m.post(Post.from_text(0, "A", "hello\n" + trailer()))
    assert "[Turn 0 · Agent A (you)]" in a.core_messages(m.view_for("A"), 300)[1]["content"]
    assert "[Turn 0 · Agent A]" in b.core_messages(m.view_for("B"), 300)[1]["content"]


async def test_speak_parses_post_and_passes_hard_cap():
    llm = FakeLLM(lambda *_: ("cut off mid-sentence", "length"))
    a, _ = agents(llm)
    post, c = await a.speak(Memory("Q?", ["A", "B"]).view_for("A"), 300, 600, CallContext("p", "dialogue", "A", "core", 0))
    assert llm.calls[0].max_tokens == 600
    assert post.truncated and post.protocol_error and post.agent == "A" and post.turn == 0


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
