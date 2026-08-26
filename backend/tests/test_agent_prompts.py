from app.agent import build_system_prompt, build_user_message


def test_system_prompt_mentions_untrusted_data():
    text = build_system_prompt().lower()
    collapsed = " ".join(text.split())
    assert "untrusted" in text
    assert "data, not instructions" in text
    assert "read-only" in text
    assert "stop calling tools" in collapsed
    assert "final answer" in collapsed
    assert "start_line=end_line+1" in collapsed
    assert "never pass an empty path" in collapsed
    assert "obey explicit user constraints" in collapsed
    assert "search_code for the symbol" in collapsed
    assert "do not keep guessing package prefixes" in collapsed
    assert "reuse prior tool results" in collapsed
    # No leading indentation from a raw triple-quoted block
    assert not build_system_prompt().startswith(" ")


def test_user_message_includes_url_and_instruction():
    msg = build_user_message(
        instruction="Find auth bugs",
        repository_url="https://github.com/example/repo",
        branch="main",
        head_sha="deadbeef",
    )
    assert "https://github.com/example/repo" in msg
    assert "Find auth bugs" in msg
    assert "- Branch: main" in msg
    assert "- HEAD: deadbeef" in msg
    assert "User instruction:" in msg


def test_user_message_omits_missing_branch_and_head():
    msg = build_user_message(
        instruction="Explain Session",
        repository_url="https://github.com/psf/requests",
    )
    assert "https://github.com/psf/requests" in msg
    assert "Explain Session" in msg
    assert "Branch:" not in msg
    assert "HEAD:" not in msg
