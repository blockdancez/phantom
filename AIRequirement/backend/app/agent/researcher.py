import re

import httpx
import structlog

logger = structlog.get_logger()


class Researcher:
    def __init__(self, tavily_api_key: str):
        self.api_key = tavily_api_key
        self.base_url = "https://api.tavily.com"

    def extract_keywords(self, idea: str) -> list[str]:
        clean = re.sub(r"[^\w\s]", "", idea)
        words = clean.split()
        stopwords = {
            "一个", "的", "和", "是", "在", "了", "不", "有", "我", "这", "他", "她",
            "a", "an", "the", "is", "are", "for", "to", "and", "of", "with",
        }
        keywords = [w for w in words if w not in stopwords and len(w) > 1]
        return keywords[:10]

    async def _search(self, query: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": 10,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", [])

    async def research(self, idea: str) -> dict:
        logger.info("竞品调研开始", idea=idea[:100])

        keywords = self.extract_keywords(idea)
        query = f"{idea} 竞品分析 类似产品 competitors"

        try:
            raw_results = await self._search(query)
        except Exception as e:
            logger.error("竞品调研失败", error=str(e), exc_info=True)
            raw_results = []

        competitors = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "summary": r.get("content", "")[:500],
            }
            for r in raw_results
        ]

        logger.info("竞品调研完成", competitor_count=len(competitors))

        return {
            "keywords": keywords,
            "competitors": competitors,
            "query": query,
        }
