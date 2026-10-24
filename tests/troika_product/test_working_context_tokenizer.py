"""Offline context estimates must never fetch a tokenizer during a request."""

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import pytest

from troika_product import working_context


VOCAB_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
VOCAB_HASH = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
CACHE_NAME = hashlib.sha1(VOCAB_URL.encode()).hexdigest()


def approximate(text):
    return max(1, len(text.encode()) // 3)


@pytest.fixture
def offline_cache(tmp_path, monkeypatch):
    tiktoken = pytest.importorskip("tiktoken")
    import tiktoken.load
    import tiktoken.registry

    directory = tmp_path / "tokenizer-cache"
    directory.mkdir()
    monkeypatch.delitem(tiktoken.registry.ENCODINGS, "cl100k_base", raising=False)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(directory))
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    working_context._cached_token_encoding.cache_clear()

    def forbidden(*args, **kwargs):
        pytest.fail("A context estimate tried to fetch tokenizer data")

    monkeypatch.setattr(tiktoken.load, "read_file", forbidden)
    return directory


def test_missing_cache_returns_existing_estimate_without_network_or_env_changes(offline_cache):
    text = "Привет. Synthetic cold context."
    environment = dict(os.environ)
    assert working_context.token_count(text) == approximate(text)
    assert dict(os.environ) == environment
    assert list(offline_cache.iterdir()) == []


def test_corrupt_cache_is_preserved_and_never_refetched(offline_cache):
    cached = offline_cache / CACHE_NAME
    cached.write_bytes(b"invalid cached public vocabulary")
    assert working_context.token_count("Synthetic context") == approximate("Synthetic context")
    assert cached.read_bytes() == b"invalid cached public vocabulary"
    assert sorted(path.name for path in offline_cache.iterdir()) == [CACHE_NAME]


def test_disabled_cache_never_fetches(offline_cache, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "")
    assert working_context.token_count("Synthetic context") == approximate("Synthetic context")


def test_missing_optional_tiktoken_keeps_existing_estimate(small_vocab, monkeypatch):
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    assert working_context.token_count("Привет") == approximate("Привет")


@pytest.fixture
def small_vocab(offline_cache, monkeypatch):
    """A complete byte vocabulary makes metadata parity tests portable."""
    import tiktoken
    import tiktoken_ext.openai_public

    ranks = {bytes([value]): value for value in range(256)}
    ranks.update({b"hello": 256, b" world": 257})
    data = b"".join(base64.b64encode(token) + b" " + str(rank).encode() + b"\n"
                    for token, rank in ranks.items())
    monkeypatch.setattr(working_context, "_CL100K_HASH", hashlib.sha256(data).hexdigest())
    path = offline_cache / CACHE_NAME
    path.write_bytes(data)
    monkeypatch.setattr(tiktoken_ext.openai_public, "load_tiktoken_bpe", lambda *a, **kw: ranks)
    reference = tiktoken.Encoding(**tiktoken_ext.openai_public.cl100k_base())
    return path, reference, data


@pytest.mark.parametrize("value", [
    "hello world", "Привет, мир!", "中文 🙂", "<|endoftext|> <|fim_prefix|>", "",
    [{"role": "user", "content": "Привет"}],
])
def test_local_encoding_matches_installed_cl100k_metadata_and_serialization(small_vocab, value):
    path, reference, original = small_vocab
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    environment = dict(os.environ)
    assert working_context.token_count(value) == len(reference.encode(text, disallowed_special=()))
    assert dict(os.environ) == environment and path.read_bytes() == original


def test_verified_real_cl100k_cache_matches_reference_without_download(offline_cache):
    """Use public cached data when available; never provision it from a test."""
    import tiktoken
    candidates = [Path(tempfile.gettempdir()) / "data-gym-cache" / CACHE_NAME]
    if os.name == "nt":
        candidates.append(Path.home() / "AppData/Local/Temp/data-gym-cache" / CACHE_NAME)
    data = None
    for candidate in candidates:
        try:
            cached = candidate.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(cached).hexdigest() == VOCAB_HASH:
            data = cached
            break
    if data is None:
        pytest.skip("Verified public cl100k cache is not available locally")
    (offline_cache / CACHE_NAME).write_bytes(data)
    reference = tiktoken.get_encoding("cl100k_base")
    for value in ("Привет, мир!", "Mixed English и русский. 中文 🙂", "<|endoftext|>",
                  [{"role": "user", "content": "Синтетический контекст"}]):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        assert working_context.token_count(value) == len(reference.encode(text, disallowed_special=()))


def test_cache_appearance_and_replacement_are_seen_without_restart(offline_cache, small_vocab):
    path, reference, data = small_vocab
    path.unlink()
    assert working_context.token_count("hello world") == approximate("hello world")
    path.write_bytes(b"corrupt")
    assert working_context.token_count("hello world") == approximate("hello world")
    path.write_bytes(data)
    assert working_context.token_count("hello world") == len(reference.encode("hello world"))


@pytest.mark.parametrize("selection", ["legacy", "default", "primary"])
def test_cache_directory_precedence(small_vocab, monkeypatch, selection):
    path, reference, _ = small_vocab
    if selection == "legacy":
        monkeypatch.delenv("TIKTOKEN_CACHE_DIR")
        monkeypatch.setenv("DATA_GYM_CACHE_DIR", str(path.parent))
    elif selection == "default":
        monkeypatch.delenv("TIKTOKEN_CACHE_DIR")
        monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
        monkeypatch.setattr(working_context.tempfile, "gettempdir", lambda: str(path.parent.parent))
        directory = path.parent.parent / "data-gym-cache"
        directory.mkdir()
        path.rename(directory / CACHE_NAME)
    else:
        monkeypatch.setenv("DATA_GYM_CACHE_DIR", str(path.parent / "missing"))
    assert working_context.token_count("hello world") == len(reference.encode("hello world"))


def test_unreadable_cache_falls_back_without_writing(small_vocab, monkeypatch):
    path, _, _ = small_vocab
    original_open = Path.open

    def denied(selected, *args, **kwargs):
        if selected == path:
            raise PermissionError("Synthetic inaccessible cache")
        return original_open(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    assert working_context.token_count("hello world") == approximate("hello world")


def test_oversized_cache_is_not_read(offline_cache, monkeypatch):
    path = offline_cache / CACHE_NAME
    path.write_bytes(b"x" * (working_context._CL100K_MAX_BYTES + 1))

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized tokenizer cache was opened")

    monkeypatch.setattr(Path, "open", forbidden)
    assert working_context.token_count("hello world") == approximate("hello world")


def test_verified_encoder_is_reused_for_unchanged_file(small_vocab, monkeypatch):
    import tiktoken
    _, reference, _ = small_vocab
    expected = len(reference.encode("hello world"))
    assert working_context.token_count("hello world") == expected

    def forbidden(*args, **kwargs):
        pytest.fail("An unchanged vocabulary was parsed again")

    monkeypatch.setattr(tiktoken, "Encoding", forbidden)
    assert working_context.token_count("hello world") == expected


def test_explicit_cache_does_not_require_a_default_temporary_directory(small_vocab, monkeypatch):
    _, reference, _ = small_vocab

    def unavailable():
        raise FileNotFoundError("Synthetic unavailable temporary directory")

    monkeypatch.setattr(working_context.tempfile, "gettempdir", unavailable)
    assert working_context.token_count("hello world") == len(reference.encode("hello world"))


def test_unavailable_default_cache_returns_existing_estimate(offline_cache, monkeypatch):
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR")

    def unavailable():
        raise FileNotFoundError("Synthetic unavailable temporary directory")

    monkeypatch.setattr(working_context.tempfile, "gettempdir", unavailable)
    assert working_context.token_count("hello world") == approximate("hello world")
