from bs4 import BeautifulSoup
from urllib.parse import urljoin
from app.utils.helpers import fetch_html

def get_novel_metadata(soup: BeautifulSoup, url: str) -> dict:
    """Extract metadata from the profile landing page."""
    # 1. Title
    title_el = soup.select_one("h1.novel-title")
    title = title_el.get_text(strip=True) if title_el else ""

    # 2. Author
    author_el = soup.select_one("span[itemprop='author'], .author a, .author span")
    author = author_el.get_text(strip=True) if author_el else ""

    # 3. Description
    # Attempt to read clean metadata description first
    desc_meta = soup.find("meta", {"itemprop": "description"})
    description = desc_meta.get("content", "").strip() if desc_meta else ""
    
    # Fallback to the text container on the page if meta is missing or generic SEO text
    if not description or ("Read" in description and "online free" in description):
        summary_div = soup.select_one(".summary .content")
        if summary_div:
            # Clean up the 'Show More' button from the description text
            expand_btn = summary_div.select_one(".expand")
            if expand_btn:
                expand_btn.decompose()
            description = summary_div.get_text(strip=True)

    # 4. Cover URL
    cover_el = soup.select_one(".cover img, .fixed-img img")
    cover_url = ""
    if cover_el:
        cover_url = cover_el.get("src") or cover_el.get("data-src") or ""
    if not cover_url:
        og_image = soup.find("meta", property="og:image")
        if og_image:
            cover_url = og_image.get("content", "")
    cover_url = urljoin(url, cover_url) if cover_url else ""

    # 5. Chapter Links
    chapter_links = []
    
    # Try locating the dedicated chapters list subpage first
    chapters_btn = soup.select_one("a.chapter-latest-container, a[href$='/chapters']")
    if chapters_btn:
        chapters_url = urljoin(url, chapters_btn.get("href"))
        try:
            chapters_html = fetch_html(chapters_url)
            if chapters_html:
                chapters_soup = BeautifulSoup(chapters_html, "lxml")
                for a in chapters_soup.find_all("a", href=True):
                    href = a["href"]
                    if "/chapter-" in href:
                        abs_url = urljoin(chapters_url, href)
                        if abs_url not in chapter_links:
                            chapter_links.append(abs_url)
        except Exception:
            pass  # Fallback to direct page parse if index subpage request fails

    # Secondary extraction direct from profile page in case of a different layout
    if not chapter_links:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/chapter-" in href and "latest" not in href and "button" not in a.get("class", []):
                abs_url = urljoin(url, href)
                if abs_url not in chapter_links:
                    chapter_links.append(abs_url)

    return {
        "title": title,
        "author": author,
        "description": description,
        "cover_url": cover_url,
        "chapter_links": chapter_links
    }

def get_chapter_content(url: str, chapter_num: int) -> dict:
    """Extract content from an individual chapter page."""
    html = fetch_html(url)
    if not html:
        raise Exception(f"Failed to fetch chapter page: {url}")

    soup = BeautifulSoup(html, "lxml")

    # Extract chapter title
    title_el = soup.select_one("span.chapter-title, h1 span.chapter-title")
    title = title_el.get_text(strip=True) if title_el else f"Chapter {chapter_num}"

    # Extract text block
    content_div = soup.select_one("#content")
    if not content_div:
        raise Exception(f"Failed to find content container on page: {url}")

    # Remove advertising wrappers and active scripts/styles
    for tag in content_div.select("script, style, .nf-ads, .adcash, iframe"):
        tag.decompose()

    # Extract individual paragraphs to exclude raw HTML, ads, or scripts
    paragraphs = [p.get_text(strip=True) for p in content_div.select("p")]
    paragraphs = [p for p in paragraphs if p]
    content = "\n\n".join(paragraphs)

    return {
        "chapter_num": chapter_num,
        "title": title,
        "content": content
    }

def crawl(url: str) -> dict:
    try:
        # Step 1: Fetch profile page
        html = fetch_html(url)
        if not html:
            return {
                "success": False,
                "error": "Failed to retrieve the landing page",
                "code": "REQUEST_FAILED"
            }

        if "cloudflare" in html.lower() or "captcha" in html.lower():
            return {
                "success": False,
                "error": "Cloudflare challenge or CAPTCHA encountered",
                "code": "BLOCKED"
            }

        soup = BeautifulSoup(html, "lxml")

        # Step 2: Extract metadata + chapter links
        meta = get_novel_metadata(soup, url)

        if not meta.get("title"):
            return {
                "success": False,
                "error": "Failed to parse metadata layout structure",
                "code": "STRUCTURE_CHANGED"
            }

        if not meta.get("chapter_links"):
            return {
                "success": False,
                "error": "No chapter links could be found",
                "code": "NO_CHAPTERS"
            }

        # Step 3: Crawl each chapter
        chapters = []
        for i, link in enumerate(meta["chapter_links"], 1):
            try:
                chapter = get_chapter_content(link, i)
                if chapter and chapter.get("content"):
                    chapters.append(chapter)
            except Exception as e:
                # Continue if a single chapter page fails, but raise if none succeed
                continue

        if not chapters:
            return {
                "success": False,
                "error": "No chapter content could be successfully extracted",
                "code": "PARSE_ERROR"
            }

        return {
            "success": True,
            "data": {
                "title": meta["title"],
                "author": meta["author"],
                "description": meta["description"],
                "cover_url": meta["cover_url"],
                "total_chapters": len(chapters),
                "chapters": chapters
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "code": "PARSE_ERROR"
        }