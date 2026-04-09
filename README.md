# Phantom AutoDev

全自主需求开发程序 — 输入需求文档，自动完成从规划到部署的全流程。

## 原理

基于 Claude Code CLI 和 Ralph-loop 循环机制：
- **规划阶段**：Claude 分析需求文档，生成实施计划
- **开发阶段**：Claude 按计划编写代码，完成后循环自检（10-50次），确保功能完整
- **测试阶段**：自动编写并运行单元测试/Playwright测试，循环自检（2-5次）
- **部署阶段**：Docker 构建并本地运行验证

## 依赖

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) >= 2.0
- jq
- Docker

## 使用方法

```bash
# 基本用法
./phantom-dev.sh requirements.md

# 指定项目目录
./phantom-dev.sh requirements.md ./my-project

# 从中断处继续
./phantom-dev.sh requirements.md --resume
```

## 运行时状态

运行过程中，状态保存在项目目录的 `.phantom/` 下：
- `state.json` — 当前阶段和迭代次数
- `plan.md` — Claude 生成的实施计划
- `logs/` — 每次迭代的详细日志
