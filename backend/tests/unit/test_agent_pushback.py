"""The rules that decide when a customer's insistence is handed to a person: plain functions over
the conversation's messages."""

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes.ask_case import ask_case_node
from app.agent.pushback import CASE_QUESTION, asked_for_case, last_reply_in


def test_ask_case_replies_with_the_fixed_question_so_the_next_turn_can_recognize_it():
    update = ask_case_node({"messages": [HumanMessage(content="I want a person")]})

    assert [m.content for m in update["messages"]] == [CASE_QUESTION]
    assert asked_for_case(update["messages"])


def test_the_question_counts_only_while_it_is_recent():
    later = [HumanMessage(content="hi")] * 8
    assert asked_for_case([AIMessage(content=CASE_QUESTION), HumanMessage(content="x")])
    assert not asked_for_case([AIMessage(content=CASE_QUESTION), *later])


def test_a_user_quoting_the_question_does_not_count_as_the_assistant_asking():
    assert not asked_for_case([HumanMessage(content=CASE_QUESTION)])


def test_last_reply_in_looks_only_at_the_latest_assistant_reply():
    no = frozenset({"no"})
    assert last_reply_in([AIMessage(content="no"), HumanMessage(content="why")], no)
    assert not last_reply_in(
        [AIMessage(content="no"), AIMessage(content="yes"), HumanMessage(content="?")], no
    )
    assert not last_reply_in([HumanMessage(content="?")], no)


def test_a_reply_made_of_blocks_never_matches_instead_of_crashing():
    blocks = AIMessage(content=[{"type": "text", "text": "no"}])
    assert not last_reply_in([blocks], frozenset({"no"}))
