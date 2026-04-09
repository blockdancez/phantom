# 任务：Docker 构建与本地部署验证

你是一个全自主部署代理。你的任务是将项目 Docker 化并在本地验证运行。

## 工作目录

{{PROJECT_DIR}}

## 你的任务

1. **创建 Dockerfile**（如果不存在）
   - 选择合适的基础镜像
   - 多阶段构建（如适用）
   - 正确的依赖安装和构建步骤
   - 暴露正确的端口

2. **创建 docker-compose.yml**（如果项目有多个服务或需要数据库）
   - 定义所有必要的服务
   - 配置网络和卷
   - 设置环境变量

3. **构建镜像**
   ```bash
   docker build -t phantom-project .
   # 或
   docker compose build
   ```

4. **运行容器**
   ```bash
   docker run -d --name phantom-test -p 8080:8080 phantom-project
   # 或
   docker compose up -d
   ```

5. **验证部署**
   - 等待服务启动（检查健康检查或轮询端口）
   - 发送测试请求验证服务正常响应
   - 检查容器日志确认无错误

6. **清理**
   - 停止并删除测试容器
   - 输出最终部署状态

## 输出要求

如果构建和运行都成功，输出：PHASE_COMPLETE
如果失败，修复问题后重试。
