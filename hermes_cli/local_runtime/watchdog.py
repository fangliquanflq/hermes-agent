"""Failure-triggered recovery for wedged children of the managed llama.cpp router."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

from hermes_cli.local_runtime.endpoint import managed_get_json, managed_root
from hermes_cli.local_runtime.supervisor import TOUCH_EXPECT, TOUCH_PROMPT, state_path

logger = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 3
_RECOVERY_COOLDOWN_S = 5 * 60
_PROBE_TIMEOUT_S = 60
_UNLOAD_TIMEOUT_S = 30
_UNLOAD_SETTLE_S = 15


@dataclass
class _ModelState:
    failures: int = 0
    last_recovery: float = 0.0
    recovering: bool = False


_LOCK = threading.Lock()
_STATES: dict[tuple[str, str], _ModelState] = {}


def _managed_target(base_url: str, model_id: str) -> tuple[str, str, str] | None:
    if not model_id or not str(base_url).lower().startswith("http://127.0.0.1:"):
        return None
    endpoint = managed_root()
    if endpoint is None:
        return None
    root, api_key = endpoint
    if str(base_url).rstrip("/") != f"{root}/v1":
        return None
    return root, api_key, model_id


def _enabled() -> bool:
    from hermes_cli.config import load_config

    section = (load_config().get("local_runtime") or {})
    return bool(section.get("recover_wedged_models"))


def _post(root: str, api_key: str, route: str, body: dict, timeout_s: float) -> dict:
    request = urllib.request.Request(
        f"{root}{route}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def _probe(root: str, api_key: str, model_id: str) -> bool:
    try:
        response = _post(root, api_key, "/v1/chat/completions", {
            "model": model_id,
            "messages": [{"role": "user", "content": TOUCH_PROMPT}],
            "max_tokens": 512,
            "temperature": 0,
        }, _PROBE_TIMEOUT_S)
        message = response["choices"][0]["message"]
        text = f"{message.get('content') or ''} {message.get('reasoning_content') or ''}"
        return TOUCH_EXPECT in text.lower()
    except Exception as exc:  # noqa: BLE001 — a failed probe is the recovery signal
        logger.warning("managed llama.cpp inference probe failed for %s: %s", model_id, exc)
        return False


def _router_pid() -> int | None:
    try:
        state = json.loads(state_path().read_text(encoding="utf-8"))
        pid = int(state.get("pid") or 0)
        return pid if pid > 0 else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _matches_model_arg(arg: str, model_id: str) -> bool:
    if arg == model_id:
        return True
    path = Path(arg)
    return path.suffix.lower() == ".gguf" and path.stem == model_id


def _terminate_model_child(router_pid: int | None, model_id: str) -> bool:
    """Terminate only descendants whose command line identifies the failed model."""
    if router_pid is None:
        return False
    try:
        import psutil

        parent = psutil.Process(router_pid)
        matches = []
        for child in parent.children(recursive=True):
            try:
                if any(_matches_model_arg(arg, model_id) for arg in child.cmdline()):
                    matches.append(child)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for child in matches:
            child.terminate()
        _, alive = psutil.wait_procs(matches, timeout=15)
        for child in alive:
            child.kill()
        return bool(matches)
    except Exception as exc:  # noqa: BLE001 — recovery must not replace the provider error
        logger.warning("could not terminate managed llama.cpp child for %s: %s", model_id, exc)
        return False


def _recover(root: str, api_key: str, model_id: str) -> None:
    if _probe(root, api_key, model_id):
        logger.info("managed llama.cpp model %s passed confirmation probe; recovery skipped", model_id)
        return
    try:
        _post(root, api_key, "/models/unload", {"model": model_id}, _UNLOAD_TIMEOUT_S)
        deadline = time.monotonic() + _UNLOAD_SETTLE_S
        while True:
            models = managed_get_json(root, api_key, "/models", timeout_s=3)
            statuses = {
                item.get("id"): (item.get("status") or {}).get("value")
                for item in (models or {}).get("data", [])
            }
            if statuses.get(model_id) not in {"loaded", "ready", "unloading"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("model child remained resident after unload")
            time.sleep(0.3)
        logger.warning("unloaded wedged managed llama.cpp model %s", model_id)
    except Exception as exc:  # noqa: BLE001 — owned-child kill is the bounded fallback
        logger.warning("managed llama.cpp unload failed for %s: %s", model_id, exc)
        if _terminate_model_child(_router_pid(), model_id):
            logger.warning("terminated wedged managed llama.cpp child for %s", model_id)


def record_inference_failure(base_url: str, model_id: str, status_code: int | None) -> None:
    """Recover after consecutive managed-endpoint 5xx responses; never raises to the caller."""
    try:
        if status_code is None or not 500 <= int(status_code) < 600:
            return
        target = _managed_target(base_url, model_id)
        if target is None or not _enabled():
            return
        root, api_key, model_id = target
        key = (root, model_id)
        now = time.monotonic()
        with _LOCK:
            state = _STATES.setdefault(key, _ModelState())
            state.failures += 1
            if (
                state.failures < _FAILURE_THRESHOLD
                or state.recovering
                or (
                    state.last_recovery > 0
                    and now - state.last_recovery < _RECOVERY_COOLDOWN_S
                )
            ):
                return
            state.failures = 0
            state.last_recovery = now
            state.recovering = True
        try:
            _recover(root, api_key, model_id)
        finally:
            with _LOCK:
                _STATES[key].recovering = False
    except Exception as exc:  # noqa: BLE001 — watchdog failure must preserve normal retries
        logger.warning("managed llama.cpp watchdog skipped recovery: %s", exc)


def record_inference_success(base_url: str, model_id: str) -> None:
    """A successful managed inference clears the model's consecutive-failure count."""
    try:
        target = _managed_target(base_url, model_id)
        if target is None:
            return
        root, _, model_id = target
        with _LOCK:
            state = _STATES.get((root, model_id))
            if state is not None:
                state.failures = 0
    except Exception as exc:  # noqa: BLE001 — observability must not break a successful call
        logger.debug("managed llama.cpp success observation failed: %s", exc)


def _reset_for_tests() -> None:
    with _LOCK:
        _STATES.clear()
