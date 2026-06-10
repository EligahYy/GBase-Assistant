# GBase Copilot 前端界面全面改造 — 设计文档

> 2026-06-10 | v3-react-agent 分支 | 基于原型 `gbase-copilot.html` 优化

## 设计目标

参考原型设计的交互模式和页面结构，将前端界面统一为 **OpenAI 极简高级风格**，提升视觉品质和交互体验。

## 全局设计规范

### 配色方案 — OpenAI Monochrome

所有页面统一纯黑白灰体系，**不使用任何渐变色**：

| Token | Light | Dark |
|-------|-------|------|
| 页面背景 | `#ffffff` / `#fafafa` | `#0a0a0a` |
| 面板/卡片 | `#ffffff` | `#141414` |
| 侧边栏 | `#fafafa` | `#0f0f0f` |
| 主文字 | `#111111` | `#f5f5f5` |
| 次要文字 | `#888888` | `#a3a3a3` |
| 边框 | `#e8e8e8` / `#ececec` | `rgba(255,255,255,0.06)` |
| 强调色（黑）| `#111111` | `#e5e5e5` |
| 成功 | `#16a34a` | 同 |
| 警告 | `#d97706` | 同 |
| 错误 | `#dc2626` | 同 |

### 字体体系

| 用途 | 字体 | 字重 |
|------|------|------|
| 品牌名 / 大标题 | Inter | 700-800, letter-spacing: -0.03em |
| 正文 / UI 文字 | Inter → system-ui 回退 | 400-600 |
| 代码 / SQL | JetBrains Mono | 400-500 |
| 中文回退 | PingFang SC, Microsoft YaHei | — |

### 圆角与阴影

- **圆角**：按钮/输入框 8-10px，卡片 12-14px，弹窗 16-18px
- **阴影**：极微弱的多层阴影，营造"浮起"感而非明显的投影
  - sm: `0 1px 2px rgba(0,0,0,0.04)`
  - md: `0 4px 20px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.03)`
  - lg: `0 20px 60px rgba(0,0,0,0.15)`（弹窗遮罩）

### 图标系统

- 全站统一使用 **@vicons/ionicons5** 线性图标
- 禁止使用 emoji 作为 UI 图标
- 常用图标映射：
  - AI/对话 → `ChatbubbleEllipsesOutline`
  - SQL 编辑器 → `CodeSlashOutline`
  - 错误码 → `AlertCircleOutline`
  - 知识库 → `BookOutline`
  - 设置 → `SettingsOutline`
  - 数据查询 → `GridOutline`
  - 搜索 → `SearchOutline`
  - 发送 → `SendOutline`
  - 文件夹 → `FolderOpenOutline`
  - 数据库 → `ServerOutline`
  - 上传 → `CloudUploadOutline`
  - 删除 → `TrashOutline`
  - 编辑 → `CreateOutline`

### 动效规范

| 动效 | 规格 |
|------|------|
| 打字机效果 | AI 回复逐字出现 + 闪烁光标 `@keyframes cursorBlink` |
| 思考动画 | 三点弹跳 `@keyframes signalDot`，1.4s 循环 |
| 弹窗入场 | `scale(0.95)→scale(1)` + `opacity 0→1`，200ms spring |
| 遮罩层 | `rgba(0,0,0,0.3)` + `backdrop-filter: blur(4px)` |
| 消息入场 | `translateY(8px)→0` + `opacity 0→1`，400ms |
| 页面切换 | `translateY(8px)→0` + `opacity 0→1`，350ms |
| 进度条 | 绿色渐变光带从左到右无限流动 |
| Hover 微交互 | 所有按钮/卡片 0.15-0.2s transition |
| 拖拽上传 | 拖入时边框从 `#e0e0e0` 变为 `#111`，背景微变 |

---

## 页面设计

### 1. AI 对话页（`/` → `HomeView.vue` + `ChatPanel.vue` + `MessageBubble.vue`）

#### 侧边栏（`Sidebar.vue`）
- 浅灰底 `#fafafa`，品牌区：黑色圆角方块 "G" + "GBase Copilot" (Inter 700)
- 新建会话按钮：黑底白字 `#111`，圆角 10px
- 文件夹/对话列表使用 Iconify 线性图标（folder / chatbubble 图标，无 emoji）
- 底部导航仅 4 项：SQL 编辑器 / 错误码查询 / 知识库 / 设置
- 移除「AI 问答」导航项（主页面本身就是 AI 对话）

#### 空状态（新对话）
- 居中大标题「今天我能帮你做什么？」
- 2×2 能力引导卡片：📊数据查询 / 🔧SQL优化 / 📖知识问答 / ⚠错误诊断
- 每张卡片：Iconify 图标 + 标题 + 描述，hover 边框加深 + 阴影提升
- 底部胶囊输入框 14px 圆角 + 微弱阴影

#### 消息气泡
- AI 消息：黑色方块头像 "G" + 文字 + hover 显示复制/点赞/点踩按钮
- 用户消息：右对齐，浅灰底 `#f4f4f4`，非对称圆角
- 思考中：圆角胶囊 + 三点弹跳动画 + "思考中" 文字
- 引用脚标：`[1]` 小徽章，hover 浮层显示来源文档名
- SQL 块：深色内嵌代码块 `#1a1a1a`，VS Code 风格语法高亮

#### 输入框
- 胶囊形：14px 圆角，`1.5px solid #e0e0e0` 边框
- focus 时边框加深 + 阴影增强
- 发送按钮：黑圆底 + 白色纸飞机图标（有内容时激活）
- 底部提示文字："GBase Copilot 可能生成不准确的 SQL，请验证后使用"

---

### 2. SQL 编辑器页（`/sql-editor` → `SqlEditorView.vue`）

#### 配色统一
- 页面整体浅色（白/浅灰），与聊天页视觉统一
- **仅代码编辑区使用深色内嵌面板** `#1a1a1a`，类似 GitHub 代码块
- 结果区和表结构面板保持浅色

#### 工具栏
- 数据库选择器（带 icon）+ 绿色运行按钮 `#16a34a` + 格式化/保存
- 快捷键提示：⌘Enter 运行

#### 代码编辑区
- 深色背景 `#1a1a1a`，JetBrains Mono 13px
- 行号灰色右对齐，语法高亮：关键字蓝/表名紫/字符串橙/数字绿
- 闪烁光标

#### 进度条
- 执行中显示：2px 高的绿色渐变光带从左到右流动
- 完成后隐藏

#### 结果区
- 浅色面板：表格/图表/原始 三视图切换
- 数据行数 + 耗时显示
- hover 行高亮

#### 表结构面板
- 可折叠表列表，展开显示列名 + 类型标签
- 主键列黄色钥匙图标，普通列灰色图标

---

### 3. 错误码查询页（`/tools/error-code` → `ErrorCodeView.vue`）

- 居中标题 + 搜索框（Iconify 搜索图标 + Enter 快捷键提示）
- 卡片列表：橙色 `ERR-1146` 标签 + 折叠/展开详情
- 展开状态：浅灰底解决方案区（带序号列表）
- 折叠状态：仅显示错误码 + 简要描述
- 展开/折叠箭头动画

---

### 4. 知识库管理页（`/knowledge` → `KnowledgeView.vue`）

- **左侧分类导航**：全部文档 / 项目文档 / 技术文档（带文档计数）
- **拖拽上传区**：虚线边框 + 上传图标 + hover 边框发光效果
- **文档表格**：文件名 + 大小 + 状态标签（已就绪🟢/向量化中⚫进度条/失败🔴）+ 操作按钮
- **重建向量索引卡片**：蓝色刷新图标 + 索引统计 + 「立即重建」按钮
  - 点击弹出密码输入弹窗 → 验证后调用 `POST /api/admin/reindex`（X-Admin-Token 头）
- 上传中的进度条动画

---

### 5. 系统设置页（`/settings` → `SettingsView.vue`）

去掉左侧标签导航，改为纵向滚动布局：

#### 通用设置
- 外观主题：太阳图标 + "当前：浅色模式" + 浅色/深色分段按钮
- 界面语言：地球图标 + "当前：简体中文" + 下拉选择
- 默认模型：AI 图标 + 当前模型名 + 状态（🟢可用）+ 下拉选择
- **系统状态 2×2 网格**：SQLite / LLM API / Qdrant / GBase 连接（各带状态点+文字）

#### 数据库连接
- 连接卡片：数据库图标 + 名称 + 地址:端口 · 版本 · 模式 + 状态标签 + 操作按钮（测试/同步/Schema/编辑/删除）
- 连接失败卡片：红色数据库图标 + 错误信息 + 「重新测试」按钮
- SQLite 本地开发卡片：绿色图标 + 路径 + SQLite 标签
- 新增连接表单：可展开/折叠的连接创建表单

#### 系统管理
- SQL 反馈统计：总反馈/已接受🟢/已修改🟡/已拒绝🔴 四个彩色统计卡片

---

## 弹窗交互

| 弹窗 | 场景 | 动效 |
|------|------|------|
| 删除确认 | 删除对话/文件夹 | 红色警告图标 + scale弹入 + 毛玻璃遮罩 |
| 重命名 | 输入框内联编辑 | 闪烁光标 + Enter/Esc 快捷键 |
| 移动到文件夹 | 批量操作 | 已选 N 项 + 文件夹列表单选 |
| 快捷键面板 | 帮助入口 | ⌘K 新建 / ⌘B 侧边栏 / Esc 停止 |
| 密码验证 | 重建索引 | 锁图标 + 密码输入 + 确认/取消 |

**统一弹窗动效**：`scale(0.95)→scale(1)` + `opacity 0→1`，200ms spring 缓动，遮罩 `rgba(0,0,0,0.3)` + `backdrop-filter: blur(4px)`

---

## 后端调整

### `backend/app/api/admin.py`
- `_verify_admin_token()`：默认 `ADMIN_TOKEN` 改为 `"123456"`（可通过 `.env` 覆盖）
- 移除 debug 模式自动放行逻辑，始终校验 token

---

## 实施范围

| 文件 | 改动类型 |
|------|----------|
| `frontend/src/assets/base.css` | 更新 CSS 变量（字体/圆角/阴影） |
| `frontend/src/assets/main.css` | 新增动画 keyframes |
| `frontend/src/App.vue` | 名称改为 GBase Copilot |
| `frontend/src/components/layout/Sidebar.vue` | emoji→Iconify 图标，移除 AI 问答导航 |
| `frontend/src/views/HomeView.vue` | 无改动（透传 ChatPanel） |
| `frontend/src/components/chat/ChatPanel.vue` | 空状态 2×2 卡片 + 输入框样式 + 品牌更新 |
| `frontend/src/components/chat/MessageBubble.vue` | 打字机效果 + 头像 + hover 操作 + 引用脚标 |
| `frontend/src/views/SqlEditorView.vue` | 浅色统一 + 深色代码内嵌 + 进度条 + 结果区 |
| `frontend/src/views/ErrorCodeView.vue` | 卡片列表 + 展开/折叠动画 |
| `frontend/src/views/KnowledgeView.vue` | 拖拽上传区 + 文档表格 + 重建索引弹窗 |
| `frontend/src/views/SettingsView.vue` | 去掉左侧标签导航 + 系统状态网格 + 连接卡片 + 反馈统计 |
| `backend/app/api/admin.py` | ADMIN_TOKEN 默认值 `123456` |
