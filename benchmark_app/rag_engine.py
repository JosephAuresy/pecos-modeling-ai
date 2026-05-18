"""
RAG Engine for the Pecos benchmark
====================================

Self-contained RAG implementation that:
- Loads PDFs (or text files) into a vector store
- Embeds them with sentence-transformers (free, local)
- Retrieves relevant chunks for a query
- Calls Claude to generate an answer grounded in retrieved chunks

Designed to be simple, transparent, and easy to swap pieces of.

Key design choices:
- ChromaDB (local persistent vector store, no server needed)
- sentence-transformers all-MiniLM-L6-v2 (free, CPU-friendly, decent quality)
- Chunking: by paragraph with token cap, preserves context
- Claude as generator (via anthropic SDK)
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Lazy imports — only loaded when needed, since these are heavy
_chromadb = None
_sentence_transformer = None
_anthropic = None
_pypdf = None


def _lazy_import_chromadb():
    global _chromadb
    if _chromadb is None:
        import chromadb
        _chromadb = chromadb
    return _chromadb


def _lazy_import_st():
    global _sentence_transformer
    if _sentence_transformer is None:
        from sentence_transformers import SentenceTransformer
        _sentence_transformer = SentenceTransformer
    return _sentence_transformer


def _lazy_import_anthropic():
    global _anthropic
    if _anthropic is None:
        import anthropic
        _anthropic = anthropic
    return _anthropic


def _lazy_import_pypdf():
    global _pypdf
    if _pypdf is None:
        from pypdf import PdfReader
        _pypdf = PdfReader
    return _pypdf


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class Chunk:
    """A chunk of a document, with metadata."""
    chunk_id: str
    text: str
    source: str            # e.g. "Bailey_2020.pdf"
    page: Optional[int] = None
    section: Optional[str] = None


@dataclass
class RetrievalResult:
    """Result of a retrieval call."""
    chunks: list[Chunk] = field(default_factory=list)
    distances: list[float] = field(default_factory=list)


@dataclass
class RagResponse:
    """Full response from the RAG pipeline."""
    answer: str
    retrieved: RetrievalResult
    prompt_used: str
    model: str


# -----------------------------------------------------------------------------
# Document loading
# -----------------------------------------------------------------------------

def load_pdf(path: Path) -> list[tuple[int, str]]:
    """Return list of (page_number, text) tuples."""
    PdfReader = _lazy_import_pypdf()
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append((i + 1, text))
    return pages


def load_text(path: Path) -> list[tuple[int, str]]:
    """Treat a plain text file as one 'page'."""
    return [(1, path.read_text(encoding="utf-8"))]


def load_document(path: Path) -> list[tuple[int, str]]:
    """Dispatch to the right loader based on extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    elif suffix in {".txt", ".md"}:
        return load_text(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


# -----------------------------------------------------------------------------
# Chunking
# -----------------------------------------------------------------------------

def chunk_text(
    text: str,
    source: str,
    page: int,
    target_words: int = 250,
    overlap_words: int = 40,
) -> list[Chunk]:
    """
    Chunk by paragraph, combining short paragraphs and splitting long ones.
    target_words is approximate, not strict.

    Why paragraph-aware: preserves semantic coherence better than fixed-token
    chunks. Especially important for technical text where a single equation
    or table reference depends on surrounding sentences.
    """
    # Split on blank lines (paragraph boundaries)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    current_text = []
    current_word_count = 0

    def flush_chunk():
        nonlocal current_text, current_word_count
        if not current_text:
            return
        chunk_text_str = "\n\n".join(current_text)
        chunk_id = hashlib.md5(
            f"{source}:{page}:{chunk_text_str[:100]}".encode()
        ).hexdigest()[:12]
        chunks.append(Chunk(
            chunk_id=chunk_id,
            text=chunk_text_str,
            source=source,
            page=page,
        ))
        # Keep last few words for overlap on next chunk
        if overlap_words > 0 and chunk_text_str:
            words = chunk_text_str.split()
            tail = " ".join(words[-overlap_words:]) if len(words) > overlap_words else ""
            current_text = [tail] if tail else []
            current_word_count = len(tail.split())
        else:
            current_text = []
            current_word_count = 0

    for para in paragraphs:
        para_words = len(para.split())

        # Very long paragraph: split it forcibly into sentence-grouped chunks
        if para_words > target_words * 2:
            # First flush whatever is accumulated before processing the long para
            if current_text:
                flush_chunk()
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sub_chunk = []
            sub_count = 0
            for sent in sentences:
                w = len(sent.split())
                if sub_count + w > target_words and sub_chunk:
                    # Emit accumulated sentences as their own chunk directly
                    current_text = [" ".join(sub_chunk)]
                    current_word_count = sub_count
                    flush_chunk()
                    sub_chunk = [sent]
                    sub_count = w
                else:
                    sub_chunk.append(sent)
                    sub_count += w
            if sub_chunk:
                current_text = [" ".join(sub_chunk)]
                current_word_count = sub_count
                # Don't flush here — let the normal loop continue or final flush handle it
            continue

        # Normal paragraph
        if current_word_count + para_words > target_words and current_text:
            flush_chunk()

        current_text.append(para)
        current_word_count += para_words

    flush_chunk()

    # Dedupe by chunk_id (overlap can occasionally produce identical hashes)
    seen = set()
    deduped = []
    for c in chunks:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            deduped.append(c)
    return deduped


# -----------------------------------------------------------------------------
# Vector store
# -----------------------------------------------------------------------------

class VectorStore:
    """
    Wraps ChromaDB + sentence-transformers.

    Persistent: chunks survive between app reloads in `db_path`.
    """

    def __init__(
        self,
        db_path: Path,
        collection_name: str = "pecos_corpus",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self._embedder = None
        self._client = None
        self._collection = None

    @property
    def embedder(self):
        if self._embedder is None:
            ST = _lazy_import_st()
            self._embedder = ST(self.embedding_model_name)
        return self._embedder

    @property
    def client(self):
        if self._client is None:
            chromadb = _lazy_import_chromadb()
            self._client = chromadb.PersistentClient(path=str(self.db_path))
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def add_chunks(self, chunks: list[Chunk], batch_size: int = 64):
        """Embed and store chunks. Idempotent on chunk_id."""
        if not chunks:
            return 0

        # Filter out chunks already present
        existing_ids = set()
        if self.collection.count() > 0:
            try:
                # ChromaDB get with no filter returns everything; use ids only
                got = self.collection.get(ids=[c.chunk_id for c in chunks])
                existing_ids = set(got.get("ids", []))
            except Exception:
                existing_ids = set()

        new_chunks = [c for c in chunks if c.chunk_id not in existing_ids]
        if not new_chunks:
            return 0

        for i in range(0, len(new_chunks), batch_size):
            batch = new_chunks[i:i + batch_size]
            texts = [c.text for c in batch]
            embeddings = self.embedder.encode(texts, show_progress_bar=False).tolist()
            metadatas = [
                {
                    "source": c.source,
                    "page": c.page if c.page is not None else -1,
                    "section": c.section or "",
                }
                for c in batch
            ]
            self.collection.add(
                ids=[c.chunk_id for c in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        return len(new_chunks)

    def query(self, query_text: str, k: int = 5) -> RetrievalResult:
        """Retrieve top-k similar chunks."""
        if self.collection.count() == 0:
            return RetrievalResult()
        query_emb = self.embedder.encode([query_text]).tolist()
        results = self.collection.query(
            query_embeddings=query_emb,
            n_results=k,
        )
        chunks = []
        distances = []
        if results["ids"] and results["ids"][0]:
            for cid, doc, meta, dist in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                chunks.append(Chunk(
                    chunk_id=cid,
                    text=doc,
                    source=meta.get("source", ""),
                    page=meta.get("page") if meta.get("page", -1) != -1 else None,
                    section=meta.get("section") or None,
                ))
                distances.append(dist)
        return RetrievalResult(chunks=chunks, distances=distances)

    def stats(self) -> dict:
        """Summary of what's in the store."""
        n = self.collection.count()
        if n == 0:
            return {"total_chunks": 0, "sources": {}}
        # Sample to count sources (avoid loading everything for huge stores)
        sample_n = min(n, 5000)
        sample = self.collection.get(limit=sample_n)
        sources = {}
        for meta in sample.get("metadatas", []):
            src = meta.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1
        return {"total_chunks": n, "sources": sources}

    def reset(self):
        """Delete all chunks. Useful for starting clean."""
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._collection = None  # force recreation


# -----------------------------------------------------------------------------
# RAG pipeline
# -----------------------------------------------------------------------------

DEFAULT_RAG_PROMPT = """You are a domain expert in hydrologic modeling, specifically the SWAT/SWAT+ family of watershed models, MODFLOW, MT3D-USGS, and related coupled surface-groundwater modeling tools. You will answer a user's question about hydrologic modeling.

You have been given excerpts retrieved from a corpus of technical documents. Use them as your primary source. If the excerpts don't directly answer the question, say so explicitly rather than guess.

Be concrete, technical, and reference specific parameters, processes, or sources when appropriate. The audience is graduate-level modelers, not the general public.

RETRIEVED EXCERPTS:
{context}

QUESTION:
{question}

INSTRUCTIONS:
- Answer in the same language as the question (Spanish or English).
- If the excerpts directly address the question, ground your answer in them.
- If the excerpts only partially address the question, use them where relevant and note where you're going beyond them.
- If the excerpts don't address the question at all, say so and provide a brief answer based on general domain knowledge — but flag this clearly.
- Be concise: typically 4-8 sentences unless the question requires more.
- Do not invent citations or DOIs.

ANSWER:"""


def format_context(retrieved: RetrievalResult, max_chars: int = 6000) -> str:
    """Format retrieved chunks for the prompt."""
    if not retrieved.chunks:
        return "(No relevant excerpts retrieved.)"

    pieces = []
    total_chars = 0
    for i, chunk in enumerate(retrieved.chunks):
        source_label = chunk.source
        if chunk.page is not None:
            source_label += f", p.{chunk.page}"
        piece = f"[Excerpt {i+1} — {source_label}]\n{chunk.text}"
        if total_chars + len(piece) > max_chars:
            break
        pieces.append(piece)
        total_chars += len(piece)
    return "\n\n".join(pieces)


def call_claude(
    api_key: str,
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
) -> str:
    """Call Anthropic API and return the text response."""
    anthropic = _lazy_import_anthropic()
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    # Concatenate text blocks
    return "".join(
        block.text for block in response.content if hasattr(block, "text")
    )


def rag_answer(
    question: str,
    store: VectorStore,
    api_key: str,
    k: int = 5,
    model: str = "claude-sonnet-4-20250514",
    prompt_template: str = DEFAULT_RAG_PROMPT,
) -> RagResponse:
    """End-to-end: retrieve, format, call Claude, return."""
    retrieved = store.query(question, k=k)
    context = format_context(retrieved)
    prompt = prompt_template.format(context=context, question=question)
    answer = call_claude(api_key, prompt, model=model)
    return RagResponse(
        answer=answer,
        retrieved=retrieved,
        prompt_used=prompt,
        model=model,
    )


def baseline_answer(
    question: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """No retrieval — pure model knowledge baseline."""
    prompt = (
        "You are a domain expert in hydrologic modeling, specifically the SWAT/SWAT+ "
        "family, MODFLOW, MT3D-USGS, and related coupled surface-groundwater tools. "
        "Answer the following question concisely and technically (4-8 sentences). "
        "Answer in the same language as the question.\n\n"
        f"QUESTION:\n{question}\n\nANSWER:"
    )
    return call_claude(api_key, prompt, model=model)
