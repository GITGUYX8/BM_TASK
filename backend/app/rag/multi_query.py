import json
import re

MULTI_QUERY_SYSTEM_PROMPT = """You are a search query expansion assistant. Given a search query, generate 2 alternative phrasings that capture the same intent but use different terms. This improves the chance of finding relevant documents.

Return your response as a JSON array of strings. Example:
["windows update 0x800F0922 boot loop fix", "dell laptop startup failure after patch"]

Return only the JSON array, no other text."""


async def expand_queries(
    query: str,
    llm_call: callable | None = None,
    max_variants: int = 2,
) -> list[str]:
    if llm_call is None or not query.strip():
        return [query]

    response = await llm_call(MULTI_QUERY_SYSTEM_PROMPT, query)
    if not response:
        return [query]

    try:
        variants = json.loads(response)
        if isinstance(variants, list) and all(isinstance(v, str) for v in variants):
            return [query] + variants[:max_variants]
    except (json.JSONDecodeError, TypeError):
        pass

    return [query]


def deduplicate_by_text(chunks: list, top_k: int = 3) -> list:
    seen = set()
    result = []
    for chunk in chunks:
        key = chunk.chunk_text[:100]
        if key not in seen:
            seen.add(key)
            result.append(chunk)
    return result[:top_k]
