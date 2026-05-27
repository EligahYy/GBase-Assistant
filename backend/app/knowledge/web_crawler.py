"""GBase 官方文档爬虫 — 从 gbase.cn Docusaurus 站点爬取产品手册。

用法:
  .venv/bin/python -m app.knowledge.web_crawler

将 gbase.cn/docs/gbase-8a/ 下所有页面渲染并保存为 knowledge/official/*.md。
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_URL = "https://www.gbase.cn"
SITEMAP_URL = f"{BASE_URL}/docs/sitemap.xml"
DOCS_PREFIX = "/docs/gbase-8a/"
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "knowledge" / "official"


async def fetch_sitemap_urls() -> list[str]:
    """从 sitemap.xml 获取所有文档 URL。"""
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SITEMAP_URL)
        resp.raise_for_status()

    urls = re.findall(r'https://www\.gbase\.cn/docs/gbase-8a/[^<\s]+', resp.text)
    # Filter out non-doc pages (categories/tags)
    docs = [u for u in urls if '/category/' not in u and '/tag/' not in u]
    logger.info("Found %d docs in sitemap", len(docs))
    return sorted(set(docs))


async def render_page(url: str, headless: bool = True) -> str | None:
    """Playwright 渲染页面，提取正文。"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed. Run: uv add playwright && playwright install chromium")
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait for Docusaurus content to render
            await page.wait_for_selector("article", timeout=15000)

            # Extract article content as Markdown
            content = await page.evaluate("""() => {
                const article = document.querySelector('article');
                if (!article) return '';
                const clone = article.cloneNode(true);
                clone.querySelectorAll('nav, .theme-doc-toc-desktop, .theme-doc-breadcrumbs, .pagination-nav, script, style').forEach(el => el.remove());

                // Convert HTML headings to Markdown
                let html = clone.innerHTML;
                // h1 → # , h2 → ## , h3 → ###
                html = html.replace(/<h1[^>]*>(.*?)<\\/h1>/gi, '\\n# $1\\n');
                html = html.replace(/<h2[^>]*>(.*?)<\\/h2>/gi, '\\n## $1\\n');
                html = html.replace(/<h3[^>]*>(.*?)<\\/h3>/gi, '\\n### $1\\n');
                html = html.replace(/<h4[^>]*>(.*?)<\\/h4>/gi, '\\n#### $1\\n');
                // code blocks
                html = html.replace(/<pre[^>]*><code[^>]*>(.*?)<\\/code><\\/pre>/gi, '\\n```\\n$1\\n```\\n');
                html = html.replace(/<code[^>]*>(.*?)<\\/code>/gi, '`$1`');
                // lists
                html = html.replace(/<li[^>]*>(.*?)<\\/li>/gi, '- $1\\n');
                // paragraphs and line breaks
                html = html.replace(/<br\\s*\\/?>/gi, '\\n');
                html = html.replace(/<\\/p>/gi, '\\n\\n');
                // tables → keep as text
                html = html.replace(/<table[^>]*>/gi, '\\n');
                html = html.replace(/<\\/table>/gi, '\\n');
                html = html.replace(/<tr[^>]*>/gi, '| ');
                html = html.replace(/<\\/tr>/gi, ' |\\n');
                html = html.replace(/<t[dh][^>]*>/gi, '| ');
                html = html.replace(/<\\/t[dh]>/gi, ' ');
                // strip remaining tags
                html = html.replace(/<[^>]*>/g, '');
                // decode entities
                const txt = document.createElement('textarea');
                txt.innerHTML = html;
                return txt.value.replace(/\\n{3,}/g, '\\n\\n').trim();
            }""")

            # Get page title
            title = await page.title()
            # Clean up title (remove site suffix)
            title = re.sub(r'\s*[|–-]\s*GBASE.*$', '', title).strip()

            if content and len(content) > 100:
                # Build markdown with title
                md = f"# {title}\n\n"
                # Get relative URL path for reference
                path = url.replace(BASE_URL, "")
                md += f"> 来源: {url}\n\n"
                md += content
                return md

            return None
        finally:
            await browser.close()


def url_to_filename(url: str) -> str:
    """URL → safe filename. /docs/gbase-8a/产品手册/admin/ → 产品手册_admin.md"""
    path = url.replace(f"{BASE_URL}{DOCS_PREFIX}", "").strip("/")
    parts = [p for p in path.split("/") if p]
    name = "_".join(parts[-3:]) if len(parts) > 3 else "_".join(parts)
    name = re.sub(r'[<>:"/\\|?*]', '_', name)[:100]
    return f"{name}.md" if name else "index.md"


async def crawl_all(limit: int | None = None) -> int:
    """爬取所有文档页面，保存为本地 Markdown。

    Args:
        limit: 限制爬取页数（None = 全部）

    Returns:
        保存的文件数
    """
    urls = await fetch_sitemap_urls()
    if limit:
        urls = urls[:limit]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0

    for i, url in enumerate(urls):
        filename = url_to_filename(url)
        filepath = OUTPUT_DIR / filename

        # Skip if already cached and non-empty
        if filepath.exists() and filepath.stat().st_size > 200:
            saved += 1
            if (i + 1) % 50 == 0:
                logger.info("Progress: %d/%d (cached: %d)", i + 1, len(urls), saved)
            continue

        logger.info("[%d/%d] %s", i + 1, len(urls), url)
        md_content = await render_page(url)

        if md_content:
            filepath.write_text(md_content, encoding="utf-8")
            saved += 1
            logger.info("  -> %s (%d chars)", filename, len(md_content))
        else:
            logger.warning("  -> EMPTY")

        # Small delay to be polite
        await asyncio.sleep(0.5)

    logger.info("Crawl complete: %d/%d pages saved to %s", saved, len(urls), OUTPUT_DIR)
    return saved


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(crawl_all())
