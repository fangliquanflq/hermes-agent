from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest


class _WedgedRouterHandler(BaseHTTPRequestHandler):
    unload_status = 200
    unloads: list[str] = []
    model_status = "loaded"

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if self.path == "/models":
            self._send(200, {"data": [{"id": "model-a", "status": {"value": self.model_status}}]})
        else:
            self._send(404, {})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == "/v1/chat/completions":
            self._send(500, {"error": {"message": "Compute error"}})
        elif self.path == "/models/unload":
            type(self).unloads.append(body.get("model"))
            if self.unload_status == 200:
                type(self).model_status = "unloaded"
            self._send(self.unload_status, {"success": self.unload_status == 200})
        else:
            self._send(404, {})

    def log_message(self, *_args):
        pass


@pytest.fixture
def wedged_router(tmp_path, monkeypatch):
    class Handler(_WedgedRouterHandler):
        unload_status = 200
        unloads = []
        model_status = "loaded"

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    from hermes_cli.local_runtime.supervisor import state_path

    state_path().parent.mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps({
        "base_url": base_url,
        "api_key": "managed-key",
        "pid": os.getpid(),
    }), encoding="utf-8")
    yield base_url, Handler
    server.shutdown()


def test_provider_call_reports_managed_inference_outcome(monkeypatch):
    from agent.turn_api_call import perform_api_call
    from hermes_cli.local_runtime import watchdog

    outcomes: list[tuple[str, str, int | None]] = []
    monkeypatch.setattr(
        watchdog,
        "record_inference_failure",
        lambda base_url, model_id, status_code: outcomes.append((base_url, model_id, status_code)),
    )
    monkeypatch.setattr(
        watchdog,
        "record_inference_success",
        lambda base_url, model_id: outcomes.append((base_url, model_id, None)),
    )
    monkeypatch.setattr(
        "agent.relay_llm.execute",
        lambda kwargs, call, **_context: call(kwargs),
    )

    agent = SimpleNamespace(
        api_mode="chat_completions",
        base_url="http://127.0.0.1:18434/v1",
        provider="custom",
        model="model-a",
        session_id="session",
        platform="cli",
        _disable_streaming=True,
        _model_request_active=None,
        _pending_redirect_lock=None,
        _fallback_index=0,
        _has_stream_consumers=lambda: False,
        _has_pending_redirect=lambda: False,
    )
    call_args = dict(
        agent=agent,
        api_kwargs={"model": "model-a", "messages": []},
        _original_api_kwargs={"model": "model-a", "messages": []},
        _llm_middleware_trace=[],
        _moa_prepared_request=None,
        _retry=SimpleNamespace(),
        thinking_spinner=None,
        retry_count=0,
        api_call_count=1,
        api_request_id="request",
        effective_task_id=None,
        turn_id="turn",
        interrupted=False,
    )

    failure = RuntimeError("Compute error")
    failure.status_code = 500
    agent._interruptible_api_call = lambda _kwargs: (_ for _ in ()).throw(failure)
    with pytest.raises(RuntimeError, match="Compute error"):
        perform_api_call(**call_args)

    agent._interruptible_api_call = lambda _kwargs: {"choices": []}
    perform_api_call(**call_args)

    assert outcomes == [
        (agent.base_url, "model-a", 500),
        (agent.base_url, "model-a", None),
    ]


@pytest.mark.parametrize("unload_status, expected_kills", [(200, []), (500, ["model-a"])])
def test_threshold_probe_recovers_once_per_cooldown(
    monkeypatch, wedged_router, unload_status, expected_kills
):
    from hermes_cli.local_runtime import watchdog

    base_url, handler = wedged_router
    handler.unload_status = unload_status
    kills: list[str] = []
    monkeypatch.setattr(watchdog, "_terminate_model_child", lambda _pid, model: kills.append(model))
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"local_runtime": {"recover_wedged_models": True}},
    )
    monkeypatch.setattr(watchdog, "_FAILURE_THRESHOLD", 2)
    clock = [100.0]
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(watchdog.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    watchdog._reset_for_tests()

    watchdog.record_inference_failure(base_url, "model-a", 500)
    watchdog.record_inference_failure(base_url, "model-a", 500)
    watchdog.record_inference_failure(base_url, "model-a", 500)

    assert handler.unloads == ["model-a"]
    assert kills == expected_kills
