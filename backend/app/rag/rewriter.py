REWRITE_SYSTEM_PROMPT = """
You are a query rewriting assistant. Given a work order description, rewrite it into a concise search query optimized for a knowledge base retrieval system. Expand abbreviations, extract key entities, and remove filler words.

Examples:
  Work order: "my laptop won't boot after latest update, got error code 0x800F0922"
  Query: Windows update error 0x800F0922 boot failure resolve

  Work order: "need to reset MFA for user jdoe@acme.com, lost phone"
  Query: MFA reset lost phone user jdoe@acme.com Okta

  Work order: "VPN keeps disconnecting every 10 minutes, using client v2.1"
  Query: VPN frequent disconnection client v2.1 connectivity issues

Return only the rewritten query, no explanation.
"""


async def rewrite_query(
    description: str,
    llm_call: callable | None = None,
) -> str:
    if llm_call is None:
        return description

    rewritten = await llm_call(REWRITE_SYSTEM_PROMPT, description)
    if rewritten:
        return rewritten.strip().strip('"').strip("'")
    return description
