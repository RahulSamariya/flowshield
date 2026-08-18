"""FlowShield knowledge package — RAG layer for policy/procedure grounding.

Public surface
--------------
KnowledgeChunk      — a single policy/SOP document fragment
KnowledgeBase       — corpus store with keyword retrieval
RetrievedChunk      — one retrieval result (chunk + relevance score)
RetrievalResult     — ordered list of RetrievedChunks
KnowledgeCategory   — controlled vocabulary for chunk categories

FLOWSHIELD_KB       — pre-built knowledge base with all built-in documents
"""

from src.knowledge.documents import FLOWSHIELD_KB
from src.knowledge.knowledge_base import KnowledgeBase, RetrievalResult, RetrievedChunk
from src.knowledge.knowledge_chunk import KnowledgeCategory, KnowledgeChunk

__all__ = [
    "KnowledgeChunk",
    "KnowledgeCategory",
    "KnowledgeBase",
    "RetrievedChunk",
    "RetrievalResult",
    "FLOWSHIELD_KB",
]
