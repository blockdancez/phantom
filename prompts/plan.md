# 任务：分析需求并制定实施计划

你是一个全自主开发代理。你的任务是分析以下需求文档，制定详细的实施计划。
全程自主决策，不要向用户提问，遇到需要选择的地方直接选择最佳方案。

## 需求文档

{{REQUIREMENTS}}

## 规划方法论

### 第一步：文件结构设计

在定义任务之前，先规划出所有需要创建或修改的文件，明确每个文件的职责：

- 每个文件只做一件事，有清晰的接口
- 一起变化的文件放在一起，按职责拆分而非按技术层拆分
- 倾向小而专注的文件，而非大而杂的文件

### 第二步：任务分解（Bite-sized）

将实现拆解为 2-5 分钟的小步骤，每步只做一个动作：

```
- [ ] 写失败测试
- [ ] 运行确认失败
- [ ] 写最小实现让测试通过
- [ ] 运行确认通过
- [ ] 提交
```

### 第三步：每个任务的格式

每个任务必须包含：

1. **涉及的文件** — 精确路径，标注 Create / Modify
2. **完整代码** — 每步给出实际代码块，不留 TODO / TBD / 占位符
3. **运行命令** — 精确的测试或验证命令，以及预期输出
4. **提交命令** — git add + commit
5. **Acceptance（验收契约）** — 一组**可重放的脚本**，独立 reviewer 会照着跑：
   - 每条是 `command` + `expect`（期望的退出码、输出片段、HTTP 状态、文件存在等）
   - 例：`curl -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/api/todos` → `expect: 200`
   - 例：`test -f src/server.js && grep -q "process.env.PORT" src/server.js` → `expect: exit 0`
   - 验收契约不是测试套件，是"这步真的做完了"的硬证据

### 关键原则

- **TDD**：先写测试，再写实现
- **DRY**：不重复代码
- **YAGNI**：不过度设计，只实现需求要求的功能
- **频繁提交**：每完成一个小功能就 git commit
- **无占位符**：每个步骤包含完整的可运行代码，禁止 "TBD"、"TODO"、"类似上面" 等
- **后端项目必须有结构化日志系统**：日志需满足可观测性、可搜索性、可分析性

## 输出要求

将完整的实施计划写入文件 `.phantom/plan.md`，格式如下：

```markdown
# 实施计划

## 技术栈
- ...

## 项目结构
```
path/to/file.js   — 职责说明
path/to/test.js   — 测试说明
```

## 任务列表

### Task 1: [组件名]

**文件:**
- Create: `exact/path/to/file.js`
- Test: `tests/path/test.js`

- [ ] **Step 1: 写失败测试**
（完整测试代码）

- [ ] **Step 2: 运行测试确认失败**
Run: `npm test`
Expected: FAIL

- [ ] **Step 3: 写最小实现**
（完整实现代码）

- [ ] **Step 4: 运行测试确认通过**
Run: `npm test`
Expected: PASS

- [ ] **Step 5: 提交**
`git add ... && git commit -m "feat: ..."`

**Acceptance:**
- `test -f src/xxx.js` → exit 0
- `npm test -- xxx` → exit 0, 输出含 "PASS"
- `curl -s -o /dev/null -w "%{http_code}" http://localhost:$PORT/xxx` → `200`

### Task 2: [下一个组件]
...
```

完成后，确保 `.phantom/plan.md` 文件已创建且内容完整。
