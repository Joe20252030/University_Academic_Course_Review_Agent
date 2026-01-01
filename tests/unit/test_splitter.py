from langchain_core.documents import Document

from config import Settings
from indexing.splitter import split_documents


def test_split_documents_creates_multiple_chunks() -> None:
	docs = [Document(page_content="A" * 55)]
	settings = Settings(CHUNK_SIZE=10, CHUNK_OVERLAP=0)

	chunks = split_documents(docs, settings)

	assert len(chunks) >= 5
	assert all(isinstance(c, Document) for c in chunks)
	assert "".join(c.page_content for c in chunks).replace("\n", "")

