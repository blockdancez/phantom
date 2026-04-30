import structlog
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector

logger = structlog.get_logger()


class GitHubTrendingCollector(BaseCollector):
    async def collect(self, limit: int = 30) -> list[dict]:
        logger.info("GitHub Trending 采集开始", limit=limit)
        items = []

        try:
            html = await self._fetch_html("https://github.com/trending")
            soup = BeautifulSoup(html, "html.parser")

            for repo in soup.select("article.Box-row")[:limit]:
                name_el = repo.select_one("h2 a")
                desc_el = repo.select_one("p")
                stars_el = repo.select_one("span.d-inline-block.float-sm-right")

                if not name_el:
                    continue

                repo_path = name_el.get("href", "").strip("/")
                title = repo_path.replace("/", " / ")
                url = f"https://github.com/{repo_path}"
                description = desc_el.get_text(strip=True) if desc_el else ""
                stars_today = stars_el.get_text(strip=True) if stars_el else ""

                lang_el = repo.select_one("[itemprop='programmingLanguage']")
                language = lang_el.get_text(strip=True) if lang_el else ""

                items.append({
                    "source": "github_trending",
                    "title": title,
                    "url": url,
                    "content": description,
                    "raw_data": {
                        "language": language,
                        "stars_today": stars_today,
                        "repo_path": repo_path,
                    },
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            logger.exception("GitHub Trending 抓取失败")

        logger.info("GitHub Trending 采集完成", count=len(items))
        return items
