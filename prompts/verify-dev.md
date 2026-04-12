# 验证：用实际运行证明代码完成

你刚刚进行了一轮代码开发。现在请通过**实际操作**验证，不要只是"想一想"。

## 第一步：需求逐条核对

对照需求文档，逐条列出每个功能点，标注：
- ✅ 已实现（指出对应文件和代码位置）
- ❌ 未实现或有问题

如果有 ❌ → 立即修复，修复后重新核对。

## 第二步：代码扫描

运行以下命令检查代码质量：
```bash
# 检查 TODO/FIXME/占位符
grep -rn "TODO\|FIXME\|XXX\|HACK\|PLACEHOLDER\|NotImplemented" --include="*.py" --include="*.js" --include="*.ts" --include="*.go" --include="*.java" . || echo "无占位符"
```

如果发现占位符 → 立即实现完整逻辑。

## 第三步：安装依赖并运行

先分配一个空闲端口，避免与其他项目冲突：
```bash
# 找空闲端口并保存
python3 -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1]); s.close()" > .phantom/port
PORT=$(cat .phantom/port)
```

然后启动项目：
```bash
# 根据项目类型执行（选择适用的）
# Node.js: PORT=$PORT npm start
# Python: PORT=$PORT python app.py
# Go: PORT=$PORT go run .
```

- 如果安装失败 → 修复依赖配置
- 如果启动失败 → 修复代码错误
- 如果启动成功 → 继续下一步

## 第四步：功能验证（仅限 API/Web 项目）

启动服务后，用 curl 验证每个端点（使用 .phantom/port 中的端口）：
```bash
PORT=$(cat .phantom/port)
curl -s http://localhost:$PORT/endpoint | head -20
```

逐个端点测试，记录：
- ✅ 返回正确
- ❌ 返回错误（附错误信息）

测试完后关闭服务进程。

## 第五步：结论

如果所有步骤都通过（无 ❌），输出：PHASE_COMPLETE

如果有任何失败，修复后**从第三步重新开始验证**，不要直接输出 PHASE_COMPLETE。
