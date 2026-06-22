# GBase 8a Assistant — 前端

GBase 8a 数据库 AI 助手的前端项目，基于 Vue 3 + TypeScript + Vite + Naive UI 构建。

## 技术栈

- **框架**：Vue 3（Composition API + `<script setup>`）
- **语言**：TypeScript
- **构建工具**：Vite
- **UI 组件库**：Naive UI
- **状态管理**：Pinia（Setup Store）
- **HTTP 客户端**：Axios
- **实时通信**：AG-UI SSE（`EventSource`）
- **代码规范**：ESLint + Prettier + vue-tsc

## 目录结构

```text
frontend/src/
├── api/                  # Axios 客户端与 API 封装
├── assets/               # 静态资源
├── components/           # 组件
│   ├── chat/             # 聊天相关：ChatPanel、MessageBubble、SQL 展示、图表/表格
│   └── layout/           # 布局：Sidebar、AppHeader 等
├── composables/          # 组合式函数
│   ├── useAGUIClient.ts  # AG-UI SSE 解码与状态处理
│   ├── useSSE.ts         # EventSource 连接管理
│   └── useTheme.ts       # 主题切换（浅色/深色/跟随系统）
├── router/               # Vue Router 路由定义
├── stores/               # Pinia Store
│   ├── chat.ts           # 会话、消息、流式状态
│   ├── connection.ts     # 数据库连接状态
│   └── theme.ts          # 主题状态
├── types/                # TypeScript 类型定义
├── utils/                # 工具函数
└── views/                # 页面级组件
    ├── ChatView.vue
    ├── KnowledgeView.vue
    ├── SqlEditorView.vue
    ├── SettingsView.vue
    └── ErrorCodeView.vue
```

## 环境变量

开发时可在 `frontend/.env.local` 中配置：

```bash
# API 基础地址（默认 /api）
VITE_API_BASE_URL=/api
```

## 开发命令

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 类型检查
npm run type-check

# 构建生产包
npm run build

# 代码检查
npm run lint
```

开发服务器默认运行在 `http://localhost:5173`，代理到后端 `http://localhost:8000`。

## 实时通信

聊天流式响应采用 **AG-UI** 标准 SSE 协议：

- `RUN_STARTED` / `RUN_FINISHED`：运行起止
- `STEP_STARTED` / `STEP_FINISHED`：步骤起止（思考、SQL 生成、执行等）
- `TEXT_DELTA`：回答文本 token
- `STATE_DELTA`：SQL、结果、图表配置等结构化状态
- `ERROR`：错误事件

详见 `src/composables/useAGUIClient.ts`。

## 主题系统

- 支持 **浅色 / 深色 / 跟随系统** 三种模式。
- 使用 CSS 变量实现 Naive UI 与自定义样式的统一切换。
- 主题状态持久化到 `localStorage`。

## 推荐开发工具

- [VS Code](https://code.visualstudio.com/) + [Vue - Official](https://marketplace.visualstudio.com/items?itemName=Vue.volar) 插件
- 浏览器安装 [Vue.js devtools](https://chromewebstore.google.com/detail/vuejs-devtools/nhdogjmejiglipccpnnnanhbledajbpd)
