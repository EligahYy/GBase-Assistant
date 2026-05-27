"""官方知识库：Markdown 文档切片器 + Qdrant 索引。

从 knowledge/official/ 目录下的 .md 文件（由 web_crawler.py 从 gbase.cn 爬取）
切片并索引到 Qdrant knowledge 集合。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    chapter_title: str
    content: str
    source_file: str = ""
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
            "source": self.metadata.get("source", "GBase 8a 产品手册"),
            "version": self.metadata.get("version", "V9.5.3"),
            "url": self.metadata.get("url", ""),
            "content": self.content[:2000],
        }


class MDChapterSlicer:
    """按 Markdown 标题切分文档。"""

    MAX_CHUNK_SIZE = 5000
    CHUNK_OVERLAP = 500

    def slice_file(self, md_path: Path, base_url: str = "") -> list[DocumentChunk]:
        """切分单个 .md 文件。按 ## 标题分块。"""
        content = md_path.read_text(encoding="utf-8")
        source = md_path.name

        # Extract page title from first # heading
        page_title = source
        title_match = re.match(r'^#\s+(.+)', content)
        if title_match:
            page_title = title_match.group(1).strip()

        # Split by ## headings
        sections = re.split(r'\n(?=##\s)', content)
        chunks = []

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Extract section heading
            heading_match = re.match(r'^#{1,3}\s+(.+)', section)
            section_title = heading_match.group(1).strip() if heading_match else page_title

            # Build full title path
            full_title = f"{page_title} > {section_title}" if section_title != page_title else page_title

            # Sub-split if too large
            sub_chunks = self._split_if_large(section, full_title, source, base_url)
            chunks.extend(sub_chunks)

        return chunks

    def _split_if_large(self, content: str, title: str, source: str, url: str) -> list[DocumentChunk]:
        if len(content) <= self.MAX_CHUNK_SIZE:
            return [DocumentChunk(
                chapter_title=title,
                content=content,
                source_file=source,
                metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3", "url": url},
            )]

        # Split by sub-headings or fixed size
        sub_headings = list(re.finditer(
            r'(?:^|\n)(?:#{1,4}\s+[^\n]{2,80}|[A-Z_]+\s*\([^)]*\)[^\n]{0,60})\n',
            content, re.MULTILINE
        ))

        chunks = []
        if len(sub_headings) >= 2:
            for i, m in enumerate(sub_headings):
                start = m.start()
                end = sub_headings[i + 1].start() if i + 1 < len(sub_headings) else len(content)
                chunk_content = content[start:end].strip()
                if len(chunk_content) < 50:
                    continue
                sub_title = m.group(0).strip().lstrip('#').strip()
                chunks.append(DocumentChunk(
                    chapter_title=f"{title} > {sub_title}",
                    content=chunk_content,
                    source_file=source,
                    metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3", "url": url},
                ))
            if chunks:
                return chunks

        # Fixed-size fallback
        pos = 0
        part = 0
        while pos < len(content):
            end = min(pos + self.MAX_CHUNK_SIZE, len(content))
            chunks.append(DocumentChunk(
                chapter_title=f"{title} (第{part + 1}部分)",
                content=content[pos:end],
                source_file=source,
                metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3", "url": url},
            ))
            pos = end - self.CHUNK_OVERLAP
            part += 1
        return chunks


class QdrantKnowledgeIndexer:
    """将文档块索引到 Qdrant knowledge 集合。"""

    COLLECTION_NAME = "knowledge"

    def __init__(self, embedder=None):
        self._embedder = embedder

    async def index_chunks(self, chunks: list[DocumentChunk], clear_existing: bool = True) -> int:
        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder
        from qdrant_client.models import PointStruct

        embedder = self._embedder or get_embedder()
        qdrant = get_qdrant_manager()
        await qdrant.ensure_collections(dimension=embedder.dimension)

        if clear_existing:
            logger.info("Clearing existing knowledge collection...")
            try:
                await qdrant.client.delete_collection(self.COLLECTION_NAME)
                await qdrant.ensure_collections(dimension=embedder.dimension)
            except Exception as e:
                logger.warning("Failed to clear collection: %s", e)

        batch_size = 10
        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            import hashlib

            embeddings = await embedder.embed([c.to_embedding_text() for c in batch])
            points = []
            for j in range(len(batch)):
                c = batch[j]
                point_id = int(hashlib.sha256(
                    f"{c.chapter_title}:{c.source_file}".encode()
                ).hexdigest()[:16], 16)
                points.append(PointStruct(id=point_id, vector=embeddings[j], payload=c.to_qdrant_payload()))
            await qdrant.client.upsert(collection_name=self.COLLECTION_NAME, points=points)
            total += len(batch)
            logger.info("Indexed %d/%d chunks", total, len(chunks))
        return total


async def build_knowledge_from_md_dir(
    md_dir: str | None = None,
    clear_existing: bool = True,
) -> int:
    """从 Markdown 目录构建知识库（秒级）。

    从 knowledge/official/ 下所有 .md 文件切片并索引到 Qdrant。
    """
    if md_dir is None:
        md_dir = str(Path(__file__).parent.parent.parent.parent / "knowledge" / "official")

    md_path = Path(md_dir)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown directory not found: {md_dir}. Run web_crawler first.")

    md_files = sorted(md_path.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files in {md_dir}. Run web_crawler first.")

    logger.info("Building knowledge from %d Markdown files in %s", len(md_files), md_dir)

    slicer = MDChapterSlicer()
    all_chunks = []
    for f in md_files:
        chunks = slicer.slice_file(f)
        all_chunks.extend(chunks)

    all_chunks = [c for c in all_chunks if len(c.content) > 50]
    logger.info("Sliced %d chunks from %d files", len(all_chunks), len(md_files))

    indexer = QdrantKnowledgeIndexer()
    count = await indexer.index_chunks(all_chunks, clear_existing=clear_existing)
    logger.info("Knowledge base built: %d chunks", count)
    return count
