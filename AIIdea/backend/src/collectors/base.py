import abc
import httpx
import structlog

logger = structlog.get_logger()


class BaseCollector(abc.ABC):
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _fetch_json(self, url: str) -> dict | list:
        logger.debug("采集器抓取", url=url, collector=self.__class__.__name__)
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def _fetch_html(self, url: str) -> str:
        logger.debug("采集器抓取 HTML", url=url, collector=self.__class__.__name__)
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.text

    @abc.abstractmethod
    async def collect(self, limit: int = 30) -> list[dict]:
        pass

    async def close(self):
        await self.client.aclose()
