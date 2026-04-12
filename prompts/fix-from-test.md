# 任务：根据测试结果修复代码

上一轮测试发现了问题。请通过收集多维度的诊断信息来定位并修复问题。

## 第一步：收集诊断信息

依次检查以下信息源，不要只看测试输出：

### 1. 后端日志
```bash
# 查看服务运行日志（根据实际情况调整）
cat .phantom/logs/*.log 2>/dev/null | tail -50
# 或查看 nohup/pm2 日志
cat nohup.out 2>/dev/null | tail -50
```
关注：错误堆栈、未捕获异常、请求处理失败、端口绑定问题

### 2. Playwright 测试报告（如有前端测试）
```bash
# 查看测试报告
cat test-results/*/trace.zip 2>/dev/null || true
# 查看失败截图
ls test-results/*/screenshot*.png 2>/dev/null || true
# 查看 Playwright HTML 报告
npx playwright show-report 2>/dev/null || true
```

### 3. 浏览器控制台日志（如有前端）
在 Playwright 测试中添加控制台日志捕获：
```javascript
page.on('console', msg => console.log('[browser]', msg.type(), msg.text()));
page.on('pageerror', err => console.log('[browser error]', err.message));
```
如果现有测试没有这些，先添加再重新运行。

### 4. 网络请求记录（如有 API 调用）
```javascript
page.on('response', response => {
  if (!response.ok()) {
    console.log('[network]', response.status(), response.url());
  }
});
```

### 5. 服务健康检查
```bash
PORT=$(cat .phantom/port 2>/dev/null || echo "3000")
# 服务是否还在运行
curl -s http://localhost:$PORT/ || echo "服务未响应"
# 检查进程
ps aux | grep -E "node|python|go" | grep -v grep
```

## 第二步：分析问题根因

根据收集到的信息，判断问题属于哪类：
- **后端错误**：API 返回 500、数据库操作失败、逻辑错误
- **前端错误**：页面元素找不到、JS 报错、渲染异常
- **集成问题**：前后端接口不匹配、CORS、端口不对
- **环境问题**：依赖缺失、端口占用、服务未启动

## 第三步：修复并验证

1. 修复**源代码**（不是修改测试来适配错误代码）
2. 重新启动服务（如需要）
3. 重新运行失败的测试
4. 确认修复不影响其他测试

## 关键原则

- 先收集信息，再修复，不要盲猜
- 修复代码，不是修复测试
- 修复后必须重新运行测试验证
- 如果发现其他遗漏的功能，一并补充
