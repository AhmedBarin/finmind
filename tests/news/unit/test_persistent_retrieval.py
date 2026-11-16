import sys
import types

import pytest

from app.news.retrieval import PersistentChromaNewsVectorIndex


def test_persistent_chroma_adapter_uses_one_named_collection(monkeypatch, tmp_path):
    calls = {}

    class Client:
        def __init__(self, *, path):
            calls["path"] = path

        def get_or_create_collection(self, *, name):
            calls["name"] = name
            return object()

    monkeypatch.setitem(sys.modules, "chromadb", types.SimpleNamespace(PersistentClient=Client))
    PersistentChromaNewsVectorIndex(path=str(tmp_path), collection_name="test_news")
    assert calls == {"path": str(tmp_path), "name": "test_news"}


def test_missing_chroma_is_an_explicit_configuration_error(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "chromadb", None)
    with pytest.raises(RuntimeError, match="ChromaDB is not installed"):
        PersistentChromaNewsVectorIndex(path=str(tmp_path))
