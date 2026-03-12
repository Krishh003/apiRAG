"""
Playwright Scraper — runs in a completely separate subprocess to avoid
Windows asyncio event loop conflicts with FastAPI.
"""

import json
import logging
import subprocess
import sys
import tempfile
import os
from typing import List, Dict

logger = logging.getLogger(__name__)

META_DOC_PAGES = [
    ("WhatsApp", "Messaging",        "https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages"),
    ("WhatsApp", "Media",            "https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media"),
    ("WhatsApp", "Webhooks",         "https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components"),
    ("WhatsApp", "Phone Numbers",    "https://developers.facebook.com/docs/whatsapp/cloud-api/reference/phone-numbers"),
    ("WhatsApp", "Templates",        "https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates"),
    ("WhatsApp", "Business Profile", "https://developers.facebook.com/docs/whatsapp/business-management-api/business-profiles"),
    ("Meta",     "Pages",            "https://developers.facebook.com/docs/graph-api/reference/page"),
    ("Meta",     "Posts",            "https://developers.facebook.com/docs/graph-api/reference/post"),
    ("Meta",     "Comments",         "https://developers.facebook.com/docs/graph-api/reference/comment"),
    ("Meta",     "Ad Campaigns",     "https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group"),
    ("Meta",     "Ad Sets",          "https://developers.facebook.com/docs/marketing-api/reference/ad-campaign"),
    ("Meta",     "Ads",              "https://developers.facebook.com/docs/marketing-api/reference/adgroup"),
    ("Meta",     "Ad Insights",      "https://developers.facebook.com/docs/marketing-api/reference/adgroup/insights"),
    ("Instagram","Media",            "https://developers.facebook.com/docs/instagram-api/reference/ig-media"),
    ("Instagram","Publishing",       "https://developers.facebook.com/docs/instagram-api/reference/ig-user/media"),
    ("Instagram","Insights",         "https://developers.facebook.com/docs/instagram-api/reference/ig-user/insights"),
    ("Instagram","Comments",         "https://developers.facebook.com/docs/instagram-api/reference/ig-comment"),
]


class PlaywrightScraper:

    def scrape_all_sync(self, platforms: list = None, custom_pages: List = None) -> List[Dict]:
        """
        Runs the scraper in a completely separate Python process.
        This fully isolates Playwright from FastAPI's event loop.
        Results are written to a temp file and read back.
        """
        if custom_pages:
            pages_to_scrape = custom_pages
        else:
            target = set(platforms) if platforms else {"WhatsApp", "Meta", "Instagram"}
            pages_to_scrape = [
                (p, c, u) for p, c, u in META_DOC_PAGES if p in target
            ]

        if not pages_to_scrape:
            return []

        # Write the worker script to a temp file
        worker_script = self._build_worker_script()
        input_data = json.dumps(pages_to_scrape)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(worker_script)
            script_path = f.name

        output_path = script_path + "_output.json"

        try:
            logger.info(f"Launching Playwright subprocess for {len(pages_to_scrape)} pages...")
            result = subprocess.run(
                [sys.executable, script_path, input_data, output_path],
                timeout=600,  # 10 min max
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"Playwright subprocess failed:\n{result.stderr}")
                return []

            if not os.path.exists(output_path):
                logger.error("Playwright subprocess produced no output file")
                return []

            with open(output_path, "r", encoding="utf-8") as f:
                blocks = json.load(f)

            logger.info(f"Playwright subprocess returned {len(blocks)} blocks")
            return blocks

        except subprocess.TimeoutExpired:
            logger.error("Playwright subprocess timed out after 10 minutes")
            return []
        except Exception as e:
            logger.error(f"Playwright subprocess error: {e}")
            return []
        finally:
            # Clean up temp files
            for path in [script_path, output_path]:
                try:
                    if os.path.exists(path):
                        os.unlink(path)
                except Exception:
                    pass

    def scrape_url(self, url: str, platform: str, category: str) -> List[Dict]:
        """Scrape a single URL."""
        return self.scrape_all_sync(custom_pages=[(platform, category, url)])

    def _build_worker_script(self) -> str:
        """
        Returns a self-contained Python script that runs Playwright
        and writes results to a JSON file.
        Runs as its own process — completely isolated from FastAPI.
        """
        return '''
import sys
import json
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def extract_blocks(html, platform, category, url):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.select("nav, footer, script, style, .sidebar, header"):
        tag.decompose()

    blocks = []

    # Try heading-based extraction first (h1 through h4 for broader coverage)
    headings = soup.find_all(["h1", "h2", "h3", "h4"])

    for heading in headings:
        title = heading.get_text(strip=True)
        if not title or len(title) < 3:
            continue
        content_parts = [title]
        sibling = heading.find_next_sibling()
        char_count = 0
        while sibling and char_count < 3000:
            if sibling.name in ["h1", "h2", "h3", "h4"]:
                break
            text = sibling.get_text(separator=" ", strip=True)
            if text:
                content_parts.append(text)
                char_count += len(text)
            sibling = sibling.find_next_sibling()
        raw_text = "\\n".join(content_parts)
        if len(raw_text) > 100:
            blocks.append({
                "platform": platform,
                "category": category,
                "source_url": url,
                "raw_text": raw_text[:4000],
                "heading": title,
            })

    # Fallback 1: try container-based extraction (article, main, role=main)
    if not blocks:
        containers = soup.select("article, main, [role='main'], .content, .documentation, .api-content, .doc-content")
        for container in containers:
            text = container.get_text(separator="\\n", strip=True)
            if len(text) > 200:
                for i in range(0, len(text), 2000):
                    chunk = text[i:i+2000].strip()
                    if len(chunk) > 200:
                        blocks.append({
                            "platform": platform,
                            "category": category,
                            "source_url": url,
                            "raw_text": chunk,
                            "heading": f"{platform} {category} block {i//2000+1}",
                        })
                break  # use first matching container

    # Fallback 2: full page text chunking
    if not blocks:
        full_text = soup.get_text(separator="\\n", strip=True)
        for i in range(0, len(full_text), 2000):
            chunk = full_text[i:i+2000].strip()
            if len(chunk) > 200:
                blocks.append({
                    "platform": platform,
                    "category": category,
                    "source_url": url,
                    "raw_text": chunk,
                    "heading": f"{platform} {category} block {i//2000+1}",
                })

    return blocks


def main():
    pages_to_scrape = json.loads(sys.argv[1])
    output_path = sys.argv[2]
    all_blocks = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        for platform, category, url in pages_to_scrape:
            print(f"Scraping [{platform}] {url}", flush=True)
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector(
                        "main, [role='main'], article",
                        timeout=12000,
                    )
                except Exception:
                    pass
                time.sleep(3)
                html = page.content()

                # DEBUG — save first page HTML to inspect
                if not all_blocks:
                    with open(output_path + "_debug.html", "w", encoding="utf-8") as dbg:
                        dbg.write(html)
                    print(f"  DEBUG: saved HTML ({len(html)} chars)", flush=True)

                blocks = extract_blocks(html, platform, category, url)
                all_blocks.extend(blocks)
                print(f"  -> {len(blocks)} blocks, HTML size: {len(html)}", flush=True)
            except Exception as e:
                print(f"  ERROR: {e}", flush=True)
            finally:
                page.close()
            time.sleep(1.5)

        context.close()
        browser.close()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_blocks, f, ensure_ascii=False)

    print(f"Done. {len(all_blocks)} total blocks written.", flush=True)


if __name__ == "__main__":
    main()
'''