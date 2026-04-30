import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()

MARKET_PROMPT = """You are a market analyst specializing in US internet products. Analyze the market opportunity for:

Idea: {idea}
Context: {context}

Provide:
1. Target market size (TAM/SAM/SOM estimates)
2. Key competitors and their weaknesses
3. Unique value proposition opportunities
4. Revenue model suggestions
5. Go-to-market strategy for US market

Be specific and data-driven."""


@tool
async def analyze_market(idea: str, context: str = "") -> str:
    """Perform market analysis for a product idea, including TAM/SAM/SOM, competitors, and revenue models."""
    logger.info("工具_市场分析", idea=idea[:80])

    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
    prompt = MARKET_PROMPT.format(idea=idea, context=context)
    response = await llm.ainvoke(prompt)
    return response.content
