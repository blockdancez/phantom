# AIDesign

AIJuicer 流水线 `design` step 的 worker。

收到任务后：
1. 从 `ctx.project_name` 拼出工作目录 `/Users/lapsdoor/phantom/<project_name>/`（可用 `PHANTOM_PROJECTS_BASE` env 覆盖）
2. `cd` 进去跑 `phantom` CLI 对应模式
3. 把产物上传给 scheduler

## 安装

```bash
cd AIDesign
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

前置：phantom CLI 已装到 PATH（`PhantomCLI/install.sh`）；AIJuicer scheduler + Redis 已起。

## 跑测试

```bash
.venv/bin/pytest -v
```

## 启动

```bash
export AIJUICER_SERVER=http://127.0.0.1:8000
# AI 后端透传给 phantom（按需）
export PHANTOM_GENERATOR_BACKEND=claude
export PHANTOM_CODE_REVIEWER_BACKEND=codex

bash scripts/service.sh start
tail -f logs/ai-design.log
```

或前台跑：`.venv/bin/python -m ai_design.agent`
