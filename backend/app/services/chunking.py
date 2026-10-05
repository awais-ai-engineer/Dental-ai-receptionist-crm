import re


def chunk_text(text: str, size: int = 1200, overlap: int = 180) -> list[str]:
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Chunk size must be positive and overlap smaller than size")
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", text.strip())]
    normalized = "\n\n".join(part for part in paragraphs if part)
    if not normalized:
        raise ValueError("Knowledge content cannot be blank")

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            window = normalized[start:end]
            boundary = window.rfind("\n\n", size // 2)
            if boundary >= 0:
                end = start + boundary + 2
            else:
                boundary = window.rfind(" ", size // 2)
                if boundary >= 0:
                    end = start + boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        start = max(start + 1, end - overlap)
        while start < len(normalized) and normalized[start].isspace():
            start += 1
    return chunks
