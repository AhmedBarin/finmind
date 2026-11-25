from app.explanation.memory import MAX_MEMORY_TURNS, memory_entry, merge_memory


def test_memory_is_bounded_to_latest_turns():
    values = [memory_entry(mode="follow_up", ticker="COMI", question=f"q{i}", answer=f"a{i}") for i in range(MAX_MEMORY_TURNS)]

    result = merge_memory(values, [memory_entry(mode="follow_up", ticker="COMI", question="new", answer="new")])

    assert len(result) == MAX_MEMORY_TURNS
    assert result[-1]["question"] == "new"
