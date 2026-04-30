# AIClusterSchedule Web UI

Next.js 14 App Router + TypeScript + Tailwind + React Flow + EventSource.

## 启动

```bash
cd webui
pnpm install          # 或 npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 pnpm dev
```

浏览器打开 http://localhost:3000。

## 页面

- `/` workflows 列表
- `/workflows/new` 创建
- `/workflows/[id]` 详情：6-step DAG + SSE 事件时间线 + 审批按钮 + 产物预览
- `/agents` 在线 agent 按 step 分组
- `/system/health` `/health` + `/metrics` 探针

## 产物预览支持

- `.md` / text/markdown → react-markdown
- `.json` → 格式化高亮
- `.png`/.jpg/.svg / image/* → 内嵌 `<img>`
- `.html` → 沙箱 iframe
- `.txt`/.py/.yml/.log 等文本 → `<pre>`
- 二进制 → 下载链接
