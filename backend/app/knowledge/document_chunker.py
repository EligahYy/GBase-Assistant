"""官方知识库：Markdown 文档切片器 + Qdrant 索引。

从 knowledge/official/ 目录下的 .md 文件（由 web_crawler.py 从 gbase.cn 爬取）
切片并索引到 Qdrant knowledge 集合。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
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
        title_match = re.match(r"^#\s+(.+)", content)
        if title_match:
            page_title = title_match.group(1).strip()

        # Split by ## headings
        sections = re.split(r"\n(?=##\s)", content)
        chunks = []

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Extract section heading
            heading_match = re.match(r"^#{1,3}\s+(.+)", section)
            section_title = heading_match.group(1).strip() if heading_match else page_title

            # Build full title path
            full_title = f"{page_title} > {section_title}" if section_title != page_title else page_title

            # Sub-split if too large
            sub_chunks = self._split_if_large(section, full_title, source, base_url)
            chunks.extend(sub_chunks)

        return chunks

    def _split_if_large(self, content: str, title: str, source: str, url: str) -> list[DocumentChunk]:
        if len(content) <= self.MAX_CHUNK_SIZE:
            return [
                DocumentChunk(
                    chapter_title=title,
                    content=content,
                    source_file=source,
                    metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3", "url": url},
                )
            ]

        # Split by sub-headings or fixed size
        sub_headings = list(
            re.finditer(r"(?:^|\n)(?:#{1,4}\s+[^\n]{2,80}|[A-Z_]+\s*\([^)]*\)[^\n]{0,60})\n", content, re.MULTILINE)
        )

        chunks = []
        if len(sub_headings) >= 2:
            for i, m in enumerate(sub_headings):
                start = m.start()
                end = sub_headings[i + 1].start() if i + 1 < len(sub_headings) else len(content)
                chunk_content = content[start:end].strip()
                if len(chunk_content) < 50:
                    continue
                sub_title = m.group(0).strip().lstrip("#").strip()
                chunks.append(
                    DocumentChunk(
                        chapter_title=f"{title} > {sub_title}",
                        content=chunk_content,
                        source_file=source,
                        metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3", "url": url},
                    )
                )
            if chunks:
                return chunks

        # Fixed-size fallback
        pos = 0
        part = 0
        while pos < len(content):
            end = min(pos + self.MAX_CHUNK_SIZE, len(content))
            chunks.append(
                DocumentChunk(
                    chapter_title=f"{title} (第{part + 1}部分)",
                    content=content[pos:end],
                    source_file=source,
                    metadata={"source": "GBase 8a MPP Cluster产品手册", "version": "V9.5.3", "url": url},
                )
            )
            pos = end - self.CHUNK_OVERLAP
            part += 1
        return chunks


class QdrantKnowledgeIndexer:
    """将文档块索引到 Qdrant knowledge 集合。"""

    COLLECTION_NAME = "knowledge"

    def __init__(self, embedder=None):
        self._embedder = embedder

    async def index_chunks(self, chunks: list[DocumentChunk], clear_existing: bool = True) -> int:
        from qdrant_client.models import PointStruct

        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder

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

        import hashlib

        # 并发 embedding，用 Semaphore 限制同时 5 批，避免 API 限流
        batch_size = 10
        max_concurrent = 4
        semaphore = asyncio.Semaphore(max_concurrent)
        qdrant_client = qdrant.client

        async def embed_and_upsert(batch_idx: int, batch: list[DocumentChunk]):
            async with semaphore:
                texts = [c.to_embedding_text() for c in batch]
                embeddings = await embedder.embed(texts)
                points = [
                    PointStruct(
                        id=int(hashlib.sha256(f"{c.chapter_title}:{c.source_file}".encode()).hexdigest()[:16], 16),
                        vector=embeddings[j],
                        payload=c.to_qdrant_payload(),
                    )
                    for j, c in enumerate(batch)
                ]
                await qdrant_client.upsert(collection_name=self.COLLECTION_NAME, points=points)
                return batch_idx, len(batch)

        tasks = []
        for i in range(0, len(chunks), batch_size):
            tasks.append(embed_and_upsert(i, chunks[i : i + batch_size]))

        total = 0
        for coro in asyncio.as_completed(tasks):
            _, count = await coro
            total += count
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

    # 检查是否需要重建
    state_file = md_path / ".index_state.json"
    current_hash = hashlib.sha256(
        "".join(f"{f.name}:{f.stat().st_mtime}:{f.stat().st_size}" for f in sorted(md_files)).encode()
    ).hexdigest()[:16]

    if not clear_existing and state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        if state.get("files_hash") == current_hash:
            logger.info("MD files unchanged, skipping re-index")
            return 0

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

    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump({"files_hash": current_hash, "chunks": count}, f)

    logger.info("Knowledge base built: %d chunks", count)
    return count


# ═══════════════════════════════════════════════════════════════════
# PDF 页面缓存（一次性提取，后续秒级加载）
# ═══════════════════════════════════════════════════════════════════


def _knowledge_dir() -> Path:
    return Path(__file__).parent.parent.parent.parent / "knowledge"


class PDFPageCache:
    """PDF 页面文本缓存：首次从 PDF 逐页提取（慢），后续从 JSON 秒级加载。"""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        self.cache_path = self.pdf_path.with_suffix(".pages.json")

    def is_cached(self) -> bool:
        return self.cache_path.exists() and self.cache_path.stat().st_size > 1000

    def extract_and_save(self) -> int:
        """从 PDF 提取所有页面文本并缓存（CPU 密集，~5 分钟）。"""
        import pdfplumber

        logger.info("Extracting text from PDF: %s", self.pdf_path)
        pdf = pdfplumber.open(str(self.pdf_path))
        pages = {}
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                text = re.sub(r"^GBase 8a MPP Cluster.*?\n", "", text)
                text = re.sub(r"文档版本953.*?南大通用数据技术股份有限公司.*?\n?$", "", text, flags=re.MULTILINE)
                pages[i + 1] = text.strip()
        pdf.close()

        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        logger.info(
            "PDF cache saved: %d pages -> %s (%.1f MB)",
            len(pages),
            self.cache_path,
            self.cache_path.stat().st_size / 1024 / 1024,
        )
        return len(pages)

    def load(self) -> dict[int, str]:
        """从缓存加载页面文本（秒级）。"""
        with open(self.cache_path, encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): v for k, v in data.items()}


def slice_from_pdf_cache(pdf_path: str | Path, toc_json_path: str | Path) -> list[DocumentChunk]:
    """从 PDF 缓存 + TOC 章节目录切片为文档块。

    需要先运行 extract_and_save() 生成缓存，或自动触发。
    """
    cache = PDFPageCache(pdf_path)
    if not cache.is_cached():
        logger.info("PDF cache not found, extracting...")
        cache.extract_and_save()

    pages = cache.load()
    total_pages = max(pages.keys()) if pages else 0

    with open(toc_json_path, encoding="utf-8") as f:
        toc_data = json.load(f)

    logger.info("Slicing from %d cached pages (%d TOC entries)", total_pages, len(toc_data))

    # Sort TOC by page number
    toc_data.sort(key=lambda e: e.get("page", 1))

    slicer = MDChapterSlicer()
    all_chunks = []

    for i, entry in enumerate(toc_data):
        if i % 50 == 0:
            logger.info("Slicing chapter %d/%d", i + 1, len(toc_data))

        start_page = entry["page"]
        if i + 1 < len(toc_data):
            end_page = toc_data[i + 1]["page"] - 1
            if end_page < start_page:
                end_page = start_page
        else:
            end_page = total_pages

        text_parts = []
        for p in range(start_page, end_page + 1):
            pt = pages.get(p, "")
            if pt:
                text_parts.append(pt)

        content = "\n\n".join(text_parts)
        if len(content.strip()) < 50:
            continue

        title = f"{entry['num']} {entry['title']}"
        chunks = slicer._split_if_large(content, title, f"pdf:{entry['num']}", "")
        all_chunks.extend(chunks)

    logger.info("Sliced %d chunks from PDF cache", len(all_chunks))
    return all_chunks


async def build_knowledge_from_pdf(
    pdf_path: str | None = None,
    toc_path: str | None = None,
    clear_existing: bool = True,
) -> int:
    """从 PDF 产品手册构建知识库。

    首次运行提取所有页面文本并缓存（~5 分钟），后续从缓存秒级切片。
    """
    if pdf_path is None:
        pdf_path = str(_knowledge_dir() / "GBase 8a MPP Cluster产品手册_V953.pdf")
    if toc_path is None:
        toc_path = str(_knowledge_dir() / "official_toc.json")

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not Path(toc_path).exists():
        raise FileNotFoundError(f"TOC not found: {toc_path}")

    # Slice from cache (auto-extracts on first run)
    chunks = await asyncio.to_thread(slice_from_pdf_cache, pdf_path, toc_path)

    # Index
    indexer = QdrantKnowledgeIndexer()
    count = await indexer.index_chunks(chunks, clear_existing=clear_existing)
    logger.info("PDF knowledge base built: %d chunks", count)
    return count
