"""把 agent 输出的 markdown 报告解析成 ParsedReport dataclass。

容错优先 —— 任意 section 缺失都允许（写 None / 空 list），不抛异常。
scheduler 调用方再决定如何把 ParsedReport 落表。

新版报告（2026-04-30）增加 5 个"借鉴启发"字段：
- ``product_thesis`` (text section)
- ``target_user_profile`` / ``core_features`` /
  ``differentiation_opportunities`` / ``innovation_angles`` (yaml blocks)

旧 8 段保持向后兼容；老报告无新字段时这些字段保持 None / [].
"""
import re
from dataclasses import dataclass, field
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


SECTION_RE = re.compile(r"^##\s+(.+?)$", re.MULTILINE)
# 三个反引号 + 可选语言标签 + 内容 + 三个反引号
YAML_BLOCK_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)\n```", re.DOTALL)


@dataclass
class ParsedReport:
    # 旧字段（向后兼容）
    summary_zh: str | None = None
    login_used: str | None = None
    feature_inventory: list[dict[str, Any]] = field(default_factory=list)
    strengths: str | None = None
    weaknesses: str | None = None
    monetization_model: str | None = None
    target_user: str | None = None
    overall_ux_score: float | None = None
    # 借鉴启发字段（新版）
    product_thesis: str | None = None
    core_features: list[dict[str, Any]] | None = None
    target_user_profile: dict[str, Any] | None = None
    differentiation_opportunities: list[dict[str, Any]] | None = None
    innovation_angles: list[dict[str, Any]] | None = None


def _split_sections(md: str) -> dict[str, str]:
    """返回 {section_title_normalized: section_body_text}。"""
    matches = list(SECTION_RE.finditer(md))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        out[title] = md[start:end].strip()
    return out


def _parse_yaml_block(body: str | None) -> Any:
    """从 markdown 段落里提取 ```yaml 块并 safe_load。容错：找不到 / 解析失败 → None。"""
    if not body:
        return None
    m = YAML_BLOCK_RE.search(body)
    raw = m.group(1) if m else body  # 没有 fenced block 时尝试整段当 yaml
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        logger.warning(
            "extractor_yaml_parse_failed",
            error_type=type(exc).__name__,
            head=raw[:200],
        )
        return None
    return loaded if loaded else None


def _parse_feature_inventory(body: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        rest = line.lstrip("-").strip()
        # 期望 "<name>: <where> | <notes>"
        name, sep, after = rest.partition(":")
        if not sep:
            items.append({"name": rest, "where_found": "", "notes": ""})
            continue
        where, sep2, notes = after.strip().partition("|")
        items.append(
            {
                "name": name.strip(),
                "where_found": where.strip(),
                "notes": notes.strip() if sep2 else "",
            }
        )
    return items


def _parse_score(body: str) -> float | None:
    """Parse "## 综合体验分" body. Score is on a 0-10 scale; legacy 0-100 / 10."""
    m = re.search(r"-?\d+(?:\.\d+)?", body)
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    if v > 10:
        v = v / 10
    return max(0.0, min(10.0, v))


def _as_list_of_dict(value: Any) -> list[dict[str, Any]] | None:
    """yaml.safe_load 可能返 list[dict] / list[str] / dict / None。"""
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, dict)] or None


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def parse_agent_report(md: str) -> ParsedReport:
    sections = _split_sections(md)

    login_section = sections.get("登录情况")
    login_used = None
    if login_section:
        first_line = login_section.splitlines()[0].strip().lower()
        login_used = first_line or None

    # 新字段（yaml 块）
    target_profile_raw = _parse_yaml_block(sections.get("目标用户画像"))
    core_features_raw = _parse_yaml_block(sections.get("核心功能（含设计意图）") or sections.get("核心功能"))
    differentiation_raw = _parse_yaml_block(sections.get("差异化机会"))
    innovation_raw = _parse_yaml_block(sections.get("创新切入点"))

    return ParsedReport(
        # 旧字段
        summary_zh=sections.get("概览") or None,
        login_used=login_used,
        feature_inventory=_parse_feature_inventory(sections.get("功能盘点", "")),
        strengths=sections.get("优点") or None,
        weaknesses=sections.get("缺点") or None,
        monetization_model=sections.get("商业模式") or None,
        target_user=sections.get("目标用户") or None,
        overall_ux_score=_parse_score(sections.get("综合体验分", "")),
        # 新字段
        product_thesis=sections.get("产品理念") or None,
        target_user_profile=_as_dict(target_profile_raw),
        core_features=_as_list_of_dict(core_features_raw),
        differentiation_opportunities=_as_list_of_dict(differentiation_raw),
        innovation_angles=_as_list_of_dict(innovation_raw),
    )


# 入库点共用的 ORM 写入 helper —— jobs.py / pipeline.py 两处共享，
# 新增/重命名字段时只动这里一处。
_PARSED_TO_ORM_FIELDS = (
    "summary_zh",
    "feature_inventory",
    "strengths",
    "weaknesses",
    "monetization_model",
    "target_user",
    "overall_ux_score",
    "product_thesis",
    "core_features",
    "target_user_profile",
    "differentiation_opportunities",
    "innovation_angles",
)


def apply_parsed_to_orm(report, parsed: ParsedReport) -> None:
    """把 ParsedReport 的字段覆盖到 ProductExperienceReport ORM 实例上。

    None 表示"未识别"，**不**覆盖（保留原值）。空 list 视为已识别但无内容
    （旧字段 ``feature_inventory`` 历史就用 ``[]`` 占位，新字段沿用同语义）。
    """
    for f in _PARSED_TO_ORM_FIELDS:
        v = getattr(parsed, f, None)
        if v is None:
            continue
        setattr(report, f, v)
