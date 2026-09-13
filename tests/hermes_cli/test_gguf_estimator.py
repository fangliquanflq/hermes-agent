from __future__ import annotations

from hermes_cli.local_runtime.estimator import LayerKind, profile_from_gguf
from hermes_cli.local_runtime.gguf import GGUFHeader


def _header(architecture: str, **metadata) -> GGUFHeader:
    values = {"general.architecture": architecture}
    values.update({f"{architecture}.{key}": value for key, value in metadata.items()})
    return GGUFHeader(path="model.gguf", version=3, metadata=values)


def test_profile_uses_per_layer_swa_metadata_for_unknown_architecture():
    header = _header(
        "future_arch",
        block_count=6,
        context_length=262144,
        **{
            "attention.head_count_kv": [8] * 6,
            "attention.key_length": 512,
            "attention.value_length": 512,
            "attention.sliding_window": 1024,
            "attention.sliding_window_pattern": [True, True, True, True, True, False],
            "attention.key_length_swa": 256,
            "attention.value_length_swa": 256,
        },
    )

    profile = profile_from_gguf(header)

    assert [kind for kind, _ in profile.layers] == [LayerKind.SWA] * 5 + [LayerKind.FULL]
    assert {cost for kind, cost in profile.layers if kind == LayerKind.SWA} == {8 * 512 * 2}
    assert {cost for kind, cost in profile.layers if kind == LayerKind.FULL} == {8 * 1024 * 2}


def test_profile_keeps_architecture_fallback_without_complete_swa_pattern():
    header = _header(
        "gemma3",
        block_count=6,
        **{
            "attention.head_count_kv": 4,
            "attention.key_length": 128,
            "attention.value_length": 128,
            "attention.sliding_window": 1024,
            "attention.sliding_window_pattern": [True],
        },
    )

    profile = profile_from_gguf(header)

    assert [kind for kind, _ in profile.layers] == [LayerKind.SWA] * 5 + [LayerKind.FULL]