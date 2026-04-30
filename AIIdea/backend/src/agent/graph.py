import structlog
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage

from src.agent.state import AgentState
from src.agent.tools import all_tools
from src.agent.prompts import SYSTEM_PROMPT

logger = structlog.get_logger()


def create_agent_graph():
    llm = ChatOpenAI(model="gpt-4o", temperature=0.3).bind_tools(all_tools)

    async def agent_node(state: AgentState):
        logger.debug("Agent 节点调用", message_count=len(state["messages"]))
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    tool_node = ToolNode(all_tools)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


async def run_analysis_agent(session) -> dict:
    logger.info("分析 Agent 开始")

    graph = create_agent_graph()

    initial_state = {
        "messages": [
            {"role": "user", "content": "基于我们采集到的数据，挖掘出最有潜力的互联网产品创意。请搜索各类信号、归纳趋势、生成创意并验证最佳的那一个。最终输出请使用中文。"}
        ],
        "collected_data": "",
        "trend_analysis": "",
        "market_insights": "",
        "tech_assessment": "",
        "generated_ideas": [],
        "final_idea": {},
    }

    config = {"configurable": {"session": session}}
    result = await graph.ainvoke(initial_state, config=config)

    final_message = result["messages"][-1].content
    logger.info("分析 Agent 结束", result_length=len(final_message))

    return {
        "analysis": final_message,
        "message_count": len(result["messages"]),
        "trace": [
            {"role": m.type, "content": m.content[:200] if hasattr(m, "content") else "tool_call"}
            for m in result["messages"]
        ],
    }
