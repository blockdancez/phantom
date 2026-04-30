# 需求：简单的 Todo API

## 功能需求

构建一个简单的 Todo 待办事项 REST API。

### 接口列表

1. `GET /todos` - 获取所有待办事项
2. `POST /todos` - 创建新的待办事项
3. `GET /todos/:id` - 获取单个待办事项
4. `PUT /todos/:id` - 更新待办事项
5. `DELETE /todos/:id` - 删除待办事项

### 数据模型

```json
{
  "id": "string (uuid)",
  "title": "string (必填)",
  "completed": "boolean (默认 false)",
  "created_at": "datetime"
}
```

### 技术要求

- 使用 Node.js + Express
- 内存存储（不需要数据库）
- 返回 JSON 格式
- 端口：3000

### 非功能需求

- 代码结构清晰
- 包含 package.json
- 包含 Dockerfile
