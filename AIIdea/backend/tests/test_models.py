from sqlalchemy import inspect
from src.models.source_item import SourceItem
from src.models.analysis_result import AnalysisResult


def test_source_item_has_required_columns():
    mapper = inspect(SourceItem)
    columns = {c.key for c in mapper.column_attrs}
    required = {"id", "source", "title", "url", "content", "raw_data",
                "category", "tags", "score", "collected_at", "processed", "created_at"}
    assert required.issubset(columns)


def test_analysis_result_has_required_columns():
    mapper = inspect(AnalysisResult)
    columns = {c.key for c in mapper.column_attrs}
    required = {"id", "idea_title", "idea_description", "market_analysis",
                "tech_feasibility", "overall_score", "source_item_ids",
                "agent_trace", "created_at"}
    assert required.issubset(columns)
