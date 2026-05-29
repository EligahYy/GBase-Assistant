"""SemanticChunker — 将 ParsedDocument 的 Section 切分为可索引的 DocumentChunk。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.knowledge.parsers.interface import ParsedDocument, Section


@dataclass
class ChunkConfig:
    max_chunk_size: int = 2000
    chunk_overlap: int = 200
    min_chunk_size: int = 100


@dataclass
class DocumentChunk:
    chapter_title: str
    content: str
    source_file: str = ""
    document_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_embedding_text(self) -> str:
        parts = [
            f"标题: {self.chapter_title}",
            f"来源: {self.metadata.get('source', 'GBase 8a 产品手册')}",
            "",
            self.content,
        ]
        return "\n".join(parts)

    def to_qdrant_payload(self) -> dict:
        return {
            "title": self.chapter_title,
            "source_file": self.source_file,
            "document_id": self.document_id,
            "source": self.metadata.get("source", "GBase 8a 产品手册"),
            "version": self.metadata.get("version", "V9.5.3"),
            "url": self.metadata.get("url", ""),
            "content": self.content[:2000],
        }


class SemanticChunker:
    """按段落边界 + 标题层级切分，优先保持语义完整性。"""

    def __init__(self, config: ChunkConfig | None = None):
        self.config = config or ChunkConfig()

    def chunk(self, document: ParsedDocument, source_file: str = "", document_id: str = "") -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for section in document.sections:
            section_chunks = self._chunk_section(section, source_file, document_id)
            chunks.extend(section_chunks)

        return [c for c in chunks if len(c.content) >= self.config.min_chunk_size]

    def _chunk_section(self, section: Section, source_file: str, document_id: str) -> list[DocumentChunk]:
        if len(section.content) <= self.config.max_chunk_size:
            return [DocumentChunk(
                chapter_title=section.heading,
                content=section.content,
                source_file=source_file,
                document_id=document_id,
                metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3"},
            )]

        # Split on paragraph boundaries first
        paragraphs = re.split(r"\n{2,}", section.content)
        chunks: list[DocumentChunk] = []
        current = ""
        part = 0

        for para in paragraphs:
            if len(current) + len(para) + 2 <= self.config.max_chunk_size:
                current = (current + "\n\n" + para).strip() if current else para
            else:
                if current and len(current) >= self.config.min_chunk_size:
                    title = section.heading if part == 0 else f"{section.heading} (第{part + 1}部分)"
                    chunks.append(DocumentChunk(
                        chapter_title=title,
                        content=current,
                        source_file=source_file,
                        document_id=document_id,
                        metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3"},
                    ))
                    part += 1
                current = para

        if current and len(current) >= self.config.min_chunk_size:
            title = section.heading if part == 0 else f"{section.heading} (第{part + 1}部分)"
            chunks.append(DocumentChunk(
                chapter_title=title,
                content=current,
                source_file=source_file,
                document_id=document_id,
                metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3"},
            ))

        return chunks
