from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_document(title: str, content: str, metadata: dict | None = None) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    texts = splitter.split_text(content)
    return [
        {
            "title": title,
            "content": content,
            "chunk_index": i,
            "chunk_text": t,
            "metadata": metadata or {},
        }
        for i, t in enumerate(texts)
    ]
