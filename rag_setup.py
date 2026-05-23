"""Build the ChromaDB vector store from travel knowledge documents.

Run this script once before starting the agent (or whenever travel data is updated):
    python rag_setup.py

This will load all .md files from the travel_data/ directory, convert them to
LangChain Document objects with metadata, and persist them to a ChromaDB vector
store for RAG retrieval during agent conversations.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
DATA_DIR = Path(__file__).parent / "travel_data"

CATEGORY_MAP = {
    "tokyo": "destination",
    "paris": "destination",
    "new_york": "destination",
    "bangkok": "destination",
    "travel_tips": "tips",
    "culture_food": "culture_food",
    "weather_seasons": "weather",
}


def load_travel_documents(data_dir: Path) -> list[Document]:
    """Read all .md files from data_dir and convert to LangChain Documents."""
    docs = []
    for filepath in data_dir.glob("*.md"):
        filename = filepath.stem
        category = CATEGORY_MAP.get(filename, "general")
        content = filepath.read_text(encoding="utf-8")
        doc = Document(
            page_content=content,
            metadata={"source": filename, "category": category},
        )
        docs.append(doc)
    return docs


def build_vectorstore():
    """Build (or rebuild) the ChromaDB vector store from travel documents."""
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    documents = load_travel_documents(DATA_DIR)
    if not documents:
        print(f"No documents found in {DATA_DIR}. Please add .md files first.")
        return

    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name="travel_knowledge",
        persist_directory=CHROMA_PERSIST_DIR,
    )

    # Verify with test queries
    print("\n--- Test Queries ---")
    test_queries = [
        "What is the best time to visit Tokyo?",
        "Paris food culture and etiquette",
        "Bangkok temple dress code",
    ]
    for query in test_queries:
        results = vectorstore.similarity_search(query, k=2)
        print(f"\nQuery: {query}")
        for r in results:
            source = r.metadata['source']
            category = r.metadata['category']
            preview = r.page_content[:80].encode('ascii', 'replace').decode('ascii')
            print(f"  [{source} ({category})] {preview}...")

    print(f"\nVector store built with {len(documents)} documents at {CHROMA_PERSIST_DIR}")


if __name__ == "__main__":
    build_vectorstore()