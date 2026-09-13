from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.error_classifier import FailoverReason
from agent.turn_recovery import _recover_format_errors
from agent.turn_retry_state import TurnRetryState


def test_caller_bound_encrypted_reasoning_retries_without_mutating_history():
    reasoning_details = [{"type": "reasoning.encrypted", "encrypted_content": "caller-bound"}]
    messages = [{"role": "assistant", "content": "answer", "reasoning_details": reasoning_details}]
    api_messages = [{"role": "assistant", "content": "answer", "reasoning_details": reasoning_details.copy()}]
    agent = MagicMock(api_mode="chat_completions", log_prefix="")
    retry = TurnRetryState()

    recovered = _recover_format_errors(
        agent,
        RuntimeError("reasoning `encrypted_content` was not issued to this caller"),
        SimpleNamespace(reason=FailoverReason.invalid_encrypted_content),
        retry,
        messages,
        api_messages,
    )

    assert recovered is True
    assert retry.invalid_encrypted_content_retry_attempted is True
    assert "reasoning_details" not in api_messages[0]
    assert messages[0]["reasoning_details"] == reasoning_details