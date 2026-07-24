import pytest
from app.rag.rewriter import rewrite_query
from app.rag.multi_query import expand_queries, deduplicate_by_text
from app.rag.retriever import _query_to_tsquery
from app.rag.reranker import rerank
from app.core.models import RetrievedChunk


@pytest.mark.asyncio
async def test_rewrite_query_no_llm():
    """Without LLM callback, returns original text unchanged."""
    result = await rewrite_query("my laptop won't boot after latest update")
    assert result == "my laptop won't boot after latest update"


@pytest.mark.asyncio
async def test_expand_queries_no_llm():
    """Without LLM callback, returns single-element list with original query."""
    result = await expand_queries("vpn not connecting")
    assert result == ["vpn not connecting"]


@pytest.mark.asyncio
async def test_expand_queries_empty():
    """Empty query returns list with empty string."""
    result = await expand_queries("")
    assert result == [""]


@pytest.mark.parametrize(
    "input_text, expected_tsquery",
    [
        ("VPN not connecting", "vpn | not | connecting"),
        ("error 691", "error | 691"),
        ("a an the", "the"),
        ("hi", ""),
        ("", ""),
    ],
)

def test_query_to_tsquery(input_text, expected_tsquery):
    assert _query_to_tsquery(input_text) == expected_tsquery


def test_deduplicate_by_text():
    base = "How to reset VPN password " * 6
    chunks = [
        RetrievedChunk(document_title="doc1", chunk_text=base + "method A steps"),
        RetrievedChunk(document_title="doc2", chunk_text="Windows update error 0x800F0922"),
        RetrievedChunk(document_title="doc3", chunk_text=base + "method B steps"),
        RetrievedChunk(document_title="doc4", chunk_text="MFA Okta setup guide"),
    ]
    result = deduplicate_by_text(chunks, top_k=10)
    assert len(result) == 3
    assert result[0].document_title == "doc1"
    assert result[2].document_title == "doc4"


def test_rerank_empty():
    result = rerank("test query", [], top_k=3)
    assert result == []


def test_rerank_no_query():
    chunks = [RetrievedChunk(document_title="doc1", chunk_text="some text")]
    result = rerank("", chunks, top_k=3)
    assert result == chunks
