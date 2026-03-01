# server

Demo 后端服务（FastAPI + Python 3.11+）。

## 当前能力

- 统一鉴权：所有 `/api/*` 请求都要求 `auth` 请求头。
- 唯一用户：`auth` 值视为当前唯一用户标识。
- 基础数据：存放于 `data.toml`，支持 API 读写。
- 用户数据空间：`user-data/` 归当前 `auth` 用户专属，支持最多两层目录分类（如 `math/calculus.md` 或 `notes.md`）。

## 项目结构

```
apps/server/
├── main.py          # FastAPI 应用入口
├── data.toml        # 基础数据存储
├── user-data/       # 用户文档目录
└── pyproject.toml   # Python 项目配置
```

## 依赖安装

在仓库根目录已配置虚拟环境 `.venv`，依赖已安装。如需重新安装：

```bash
cd apps/server
pip install fastapi uvicorn[standard]
```

## 本地运行

在仓库根目录执行：

- `pnpm start:server`：启动后端（默认端口 `3001`）
- `pnpm dev:server`：热重载模式启动后端

健康检查：`GET /health`

API 文档：启动后访问 `http://localhost:3001/docs`

## API（统一要求 `auth` 头）

### 1) 读取基础数据

- `GET /api/base-data`
- 返回：`{ "content": "...toml内容..." }`

### 2) 写入基础数据

- `PUT /api/base-data`
- Body：`{ "content": "...toml内容..." }`

### 3) 读取用户文档（支持两层目录）

- `GET /api/user-doc?path=math/calculus.md`
- `GET /api/user-doc?path=notes.md`
- 返回：`{ "userId": "<auth>", "content": "...markdown..." }`

### 4) 写入用户文档（支持两层目录）

- `PUT /api/user-doc?path=math/calculus.md`
- `PUT /api/user-doc?path=notes.md`
- Body：`{ "content": "...markdown..." }`

## 路径规则

- 必须以 `.md` 结尾
- 最多支持两层目录：`category/topic.md` 或 `topic.md`
- 禁止路径穿越（`..`）

## OpenAI 兼容接口

本服务实现了 OpenAI API 兼容接口，支持标准 OpenAI SDK 调用。

### 认证

使用 `Authorization: Bearer <token>` 头部进行认证。

### 可用接口

#### 1) 列出模型

- `GET /v1/models`
- 返回配置的可用模型列表

#### 2) 聊天补全

- `POST /v1/chat/completions`
- 请求体：
```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "temperature": 0.7,
  "stream": false
}
```
- 支持流式响应（`stream: true`）

#### 3) 文本补全（传统）

- `POST /v1/completions`
- 请求体：
```json
{
  "model": "gpt-3.5-turbo",
  "prompt": "Once upon a time",
  "max_tokens": 50,
  "temperature": 0.7,
  "stream": false
}
```
- 支持流式响应（`stream: true`）

#### 4) 文本嵌入

- `POST /v1/embeddings`
- 请求体：
```json
{
  "model": "text-embedding-ada-002",
  "input": "The quick brown fox"
}
```

### 配置

AI 模型配置存储在 `config.toml`。示例：

```toml
[system]
session_timeout_minutes = 30
max_sessions_per_user = 10

[text_model]
name = "gpt-3.5-turbo"
endpoint = "https://api.openai.com/v1"
api_token = "sk-..."
description = "Fast text generation model"

[multimodal_model]
name = "gpt-4-vision-preview"
endpoint = "https://api.openai.com/v1"
api_token = "sk-..."
description = "Multimodal model with vision capabilities"
```

### 使用 OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:3001/v1",
    api_key="your-token"
)

# 聊天补全
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)

# 文本嵌入
embedding = client.embeddings.create(
    model="text-embedding-ada-002",
    input="Hello world"
)
```
