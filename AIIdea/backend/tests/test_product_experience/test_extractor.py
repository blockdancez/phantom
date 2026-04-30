"""Extractor tests — covers legacy 8 sections + new "借鉴启发" yaml blocks +
backward compatibility (old reports without yaml blocks parse cleanly,
new fields stay None)."""
from src.product_experience.extractor import (
    ParsedReport,
    apply_parsed_to_orm,
    parse_agent_report,
)


LEGACY_SAMPLE = """# 产品体验报告

## 概览
Toolify 是一个 AI 工具目录站。面向想找 AI 工具的从业者。

## 登录情况
google

## 功能盘点
- 工具搜索: 顶部 search bar | 支持中文关键字
- 排行榜: /ranking 页 | 按访问量排
- 新品提交: /submit 页 | 需要登录

## 优点
信息密度高。中文支持好。响应快。

## 缺点
搜索结果排序逻辑不透明。免费档广告偶尔挡住操作区。

## 商业模式
免费 + Pro 订阅。Pro 解锁更详细的 traffic 数据。

## 目标用户
做 AI 应用的独立开发者、AI 内容创作者。

## 综合体验分
7.2
"""


INSPIRATION_SAMPLE = """# 产品启发 brief

## 产品理念
Linear 把 issue tracker 重构成"工程师不嫌弃的工具"——快、键盘优先、不让流程吃掉时间。

## 目标用户画像
```yaml
persona: 5-50 人小型 SaaS 工程团队的 EM 或 staff engineer
scenarios:
  - 计划 sprint 时按 cycle 切片
  - 写 spec 时直接 link issue
  - 跨产品线追踪依赖
pain_points:
  - Jira 太重、加载慢
  - GitHub Issues 没有 cycle / triage 视图
why_this_product: 键盘速度 + 清爽 UI + 工程师 mental model
```

## 核心功能（含设计意图）
```yaml
- name: Cycle (sprint)
  priority: must
  where_seen: 主导航 / Cycles 页
  rationale: 把"时间盒"做成第一公民——sprint 是工程节奏的基本单位
- name: Triage queue
  priority: must
  where_seen: Inbox 页
  rationale: 让新 issue 进 backlog 前必经过审，防止 backlog 失控
- name: Slash commands
  priority: should
  where_seen: 任何 issue 编辑器
  rationale: 不离手键盘是工程师生产力的核心 promise
```

## 差异化机会
```yaml
- observation: Linear 的项目模板/checklist 比较弱，团队仍要自己拼 process
  opportunity: 内置基于团队规模的 SOP 模板（DevOps / On-call / Release flow）
  why_it_matters: 小团队往往没人专职做流程，开箱模板能省 10+ 小时配置
- observation: 跨工作区协作弱，多客户项目要切来切去
  opportunity: 引入"client workspace"概念，给外包/咨询场景一个原生位
  why_it_matters: SaaS 咨询 / 外包是个被忽略的 50k+ 团队的市场
```

## 创新切入点
```yaml
- angle: AI 增强
  hypothesis: 把"为什么这条 issue 阻塞"变成 LLM 总结的 inline 卡片
  examples:
    - 自动归纳 sprint blocker 走势
    - 一键生成 standup 文字稿
- angle: 工作流简化
  hypothesis: 大多数 issue 模板只用了 3-5 个字段，把字段配置压成"行业模板"开箱即用
  examples:
    - 给 Web 开发团队预置 Bug / Story / Spike 三种模板
    - 给 Mobile 团队预置 Crash / UX / Release Blocker 三种
```

---

## 附录：原始体验数据

## 概览
Linear 是为现代工程团队打造的项目管理工具。

## 登录情况
google

## 功能盘点
- Cycle 视图: 主导航 | sprint 时间盒
- Triage: Inbox | 新 issue 入口
- Roadmap: /roadmap | 季度规划

## 优点
键盘体验极佳。响应飞快。

## 缺点
模板少。免费档限制紧。

## 商业模式
免费 + 团队订阅 + 企业版。

## 目标用户
小型 SaaS 工程团队。

## 综合体验分
8.5
"""


# ---------------- 旧字段（向后兼容） ----------------


def test_parse_extracts_all_legacy_sections():
    r = parse_agent_report(LEGACY_SAMPLE)
    assert isinstance(r, ParsedReport)
    assert "Toolify" in (r.summary_zh or "")
    assert r.login_used == "google"
    assert r.overall_ux_score == 7.2
    assert len(r.feature_inventory) == 3
    assert r.feature_inventory[0]["name"] == "工具搜索"
    assert "信息密度" in (r.strengths or "")
    assert "搜索结果排序" in (r.weaknesses or "")
    assert "订阅" in (r.monetization_model or "")


def test_parse_returns_partial_when_score_missing():
    bad = LEGACY_SAMPLE.replace("## 综合体验分\n7.2\n", "")
    r = parse_agent_report(bad)
    assert r.overall_ux_score is None
    assert r.summary_zh is not None


def test_parse_score_legacy_100_scale_is_normalized():
    legacy = LEGACY_SAMPLE.replace("## 综合体验分\n7.2\n", "## 综合体验分\n82\n")
    r = parse_agent_report(legacy)
    assert r.overall_ux_score == 8.2


def test_legacy_report_keeps_new_fields_none():
    """老报告（无 yaml 块）解析仍 OK，新字段全部 None / [] —— 向后兼容关键不变量。"""
    r = parse_agent_report(LEGACY_SAMPLE)
    assert r.product_thesis is None
    assert r.core_features is None
    assert r.target_user_profile is None
    assert r.differentiation_opportunities is None
    assert r.innovation_angles is None


# ---------------- 新字段（借鉴启发 brief） ----------------


def test_parse_inspiration_brief_extracts_all_new_fields():
    r = parse_agent_report(INSPIRATION_SAMPLE)
    assert r.product_thesis and "Linear" in r.product_thesis
    # target_user_profile is dict
    assert isinstance(r.target_user_profile, dict)
    assert "工程团队" in r.target_user_profile["persona"]
    assert len(r.target_user_profile["scenarios"]) == 3
    # core_features list
    assert len(r.core_features or []) == 3
    assert r.core_features[0]["priority"] == "must"
    assert r.core_features[0]["name"] == "Cycle (sprint)"
    # differentiation_opportunities list
    assert len(r.differentiation_opportunities or []) == 2
    assert "checklist" in r.differentiation_opportunities[0]["observation"]
    # innovation_angles list
    assert len(r.innovation_angles or []) == 2
    assert r.innovation_angles[0]["angle"] == "AI 增强"
    # 旧字段附录仍解析
    assert "Linear 是" in (r.summary_zh or "")
    assert r.overall_ux_score == 8.5


def test_parse_yaml_failure_returns_none_not_crash():
    """LLM 输出语法错的 yaml 块，不应让整个 parse 崩溃。"""
    broken = INSPIRATION_SAMPLE.replace(
        "persona: 5-50",
        "persona: 5-50\n  bad_indent: [unclosed",  # 语法错
    )
    r = parse_agent_report(broken)
    # 只有 target_user_profile 受影响，其他字段照常
    assert r.target_user_profile is None
    assert r.product_thesis is not None
    assert r.core_features is not None


def test_apply_parsed_to_orm_preserves_existing_when_none():
    """apply_parsed_to_orm 只覆盖非 None；原有值在 parsed 字段为 None 时保留。"""

    class _Row:
        summary_zh = "原有概要"
        product_thesis = "原有理念"
        core_features = None
        target_user_profile = None
        differentiation_opportunities = None
        innovation_angles = None
        feature_inventory = []
        strengths = None
        weaknesses = None
        monetization_model = None
        target_user = None
        overall_ux_score = None

    row = _Row()
    parsed = ParsedReport(
        product_thesis=None,  # 不覆盖
        core_features=[{"name": "新功能", "priority": "must"}],
    )
    apply_parsed_to_orm(row, parsed)
    assert row.product_thesis == "原有理念"  # 保留原值
    assert row.core_features == [{"name": "新功能", "priority": "must"}]


def test_apply_parsed_to_orm_writes_all_inspiration_fields():
    class _Row:
        product_thesis = None
        core_features = None
        target_user_profile = None
        differentiation_opportunities = None
        innovation_angles = None
        summary_zh = None
        feature_inventory = []
        strengths = None
        weaknesses = None
        monetization_model = None
        target_user = None
        overall_ux_score = None

    row = _Row()
    parsed = parse_agent_report(INSPIRATION_SAMPLE)
    apply_parsed_to_orm(row, parsed)
    assert "Linear" in row.product_thesis
    assert len(row.core_features) == 3
    assert row.target_user_profile["persona"]
    assert len(row.differentiation_opportunities) == 2
    assert len(row.innovation_angles) == 2
    assert row.overall_ux_score == 8.5
