"""SemanticChunker — 将 ParsedDocument 的 Section 切分为可索引的 DocumentChunk。

分块策略：
1. 在段落边界 (\\n{2,}) 切分，优先保持语义完整性
2. 块间重叠前一个块的末尾文本（chunk_overlap），保留跨边界上下文
3. 超长段落回退按句子边界 (。！？\\n) 切分
"""

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
    """按段落边界切分，重叠窗口保留跨块上下文，超长段落回退句子切分。"""

    _SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？])\s*")

    def __init__(self, config: ChunkConfig | None = None):
        self.config = config or ChunkConfig()

    def chunk(self, document: ParsedDocument, source_file: str = "", document_id: str = "") -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for section in document.sections:
            section_chunks = self._chunk_section(section, source_file, document_id)
            chunks.extend(section_chunks)

        result = [c for c in chunks if len(c.content) >= self.config.min_chunk_size]
        return self._apply_overlap(result)

    def _chunk_section(self, section: Section, source_file: str, document_id: str) -> list[DocumentChunk]:
        if len(section.content) <= self.config.max_chunk_size:
            return [
                DocumentChunk(
                    chapter_title=section.heading,
                    content=section.content,
                    source_file=source_file,
                    document_id=document_id,
                    metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3"},
                )
            ]

        # 按段落边界切分
        paragraphs = re.split(r"\n{2,}", section.content)
        chunks: list[DocumentChunk] = []
        current = ""
        part = 0

        for para in paragraphs:
            if len(current) + len(para) + 2 <= self.config.max_chunk_size:
                current = (current + "\n\n" + para).strip() if current else para
            else:
                if current and len(current) >= self.config.min_chunk_size:
                    chunks.append(self._make_chunk(section.heading, current, source_file, document_id, part))
                    part += 1
                    current = ""
                # 如果单个段落超过 max_chunk_size，回退句子切分
                if len(para) > self.config.max_chunk_size:
                    sub_chunks = self._split_long_paragraph(para, section.heading, source_file, document_id, part)
                    chunks.extend(sub_chunks)
                    part += len(sub_chunks)
                    current = ""
                else:
                    current = para

        if current and len(current) >= self.config.min_chunk_size:
            chunks.append(self._make_chunk(section.heading, current, source_file, document_id, part))

        return chunks

    def _split_long_paragraph(
        self, text: str, heading: str, source_file: str, document_id: str, start_part: int
    ) -> list[DocumentChunk]:
        """超长段落按句子边界切分。"""
        sentences = self._SENTENCE_BOUNDARY.split(text)
        chunks: list[DocumentChunk] = []
        current = ""
        part = start_part

        for sent in sentences:
            if len(current) + len(sent) + 1 <= self.config.max_chunk_size:
                current = (current + sent).strip() if current else sent
            else:
                if current and len(current) >= self.config.min_chunk_size:
                    chunks.append(self._make_chunk(heading, current, source_file, document_id, part))
                    part += 1
                current = sent

        if current and len(current) >= self.config.min_chunk_size:
            chunks.append(self._make_chunk(heading, current, source_file, document_id, part))

        return chunks

    def _make_chunk(self, heading: str, content: str, source_file: str, document_id: str, part: int) -> DocumentChunk:
        title = heading if part == 0 else f"{heading} (第{part + 1}部分)"
        return DocumentChunk(
            chapter_title=title,
            content=content,
            source_file=source_file,
            document_id=document_id,
            metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3"},
        )

    def _apply_overlap(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        """在相邻块之间添加重叠文本，保留跨块上下文。"""
        if self.config.chunk_overlap <= 0 or len(chunks) < 2:
            return chunks

        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            if len(prev.content) > self.config.chunk_overlap:
                overlap_text = prev.content[-self.config.chunk_overlap :]
                chunks[i].content = overlap_text + "\n\n" + chunks[i].content

        return chunks
