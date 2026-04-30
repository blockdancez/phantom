# Phantom

Phantom 是一组围绕 AI 驱动的软件研发流水线的子项目集合，聚合在同一个仓库中维护。

## 子项目

| 目录 | 说明 |
| --- | --- |
| `AIIdea/` | 创意/产品立项阶段：从 idea 到产品候选 |
| `AIRequirement/` | 需求阶段：把 idea 转化为结构化需求 |
| `AIPlan/` | 规划阶段 agent |
| `AIDesign/` | 设计阶段 agent |
| `AIDevelop/` | 开发阶段：phantom CLI、prompts、工具脚本 |
| `AIDevTest/` | 测试阶段 agent |
| `AIDeploy/` | 部署阶段（占位） |
| `AIJuicer/` | 任务/集群调度与编排平台（FastAPI + Web UI） |

## 历史

部分子项目原本独立托管在以下仓库中，已在 2026-04-30 合并进本仓库（保留各原仓库作为历史快照）：

- `AIIdea/` ← `git@github.com:blockdancez/ai-idea.git`
- `AIJuicer/` ← `git@github.com:blockdancez/ai-juicer.git`
- `AIDevelop/` ← `git@github.com:blockdancez/phantom.git`（旧版仅含 AIDevelop）
- `AIRequirement/` ← 原独立本地仓库
