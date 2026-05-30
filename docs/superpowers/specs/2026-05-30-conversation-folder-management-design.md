# 对话列表管理功能增强

**日期**: 2026-05-30  
**状态**: 已确认

## 概述

重构侧边栏对话列表，新增项目文件夹分组、批量管理能力，修复归档消息提示 bug。设计参考 ChatGPT 极简风格。

## 数据模型

### 新增表：`folders`

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(36) PK | UUID |
| name | String(100) | 文件夹名称，不可空 |
| created_at | DateTime | |
| updated_at | DateTime | |

### 修改表：`conversations`

新增字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| folder_id | String(36) FK nullable | 外键 → folders.id，SET NULL on delete（但业务逻辑上层级联删除） |

关系：`Folder` 一对多 `Conversation`。删除文件夹时应用层先级联删除所有关联对话，再删除文件夹。

> 注：不使用数据库级 CASCADE，改为应用层显式处理，便于记录日志和未来扩展（如回收站）。

## API 端点

### 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/chat/folders` | 获取文件夹列表，含 `conversation_count` |
| `POST` | `/chat/folders` | 创建文件夹 `{name}` |
| `PATCH` | `/chat/folders/{id}` | 重命名 `{name}` |
| `DELETE` | `/chat/folders/{id}` | 删除文件夹，级联删除所有对话 |

### 修改

| 方法 | 路径 | 变更 |
|------|------|------|
| `GET` | `/chat/conversations` | 支持 `?folder_id=` 过滤，`?folder_id=null` 查未分类 |
| `PATCH` | `/chat/conversations/{id}` | 新增 `folder_id` 可更新字段 |
| `POST` | `/chat/conversations/batch` | **新增端点**，body: `{ids: [...], action: "archive"|"delete"|"move", folder_id?: string}` |

### 已有端点保持不变

`GET /chat/conversations/{id}`, `GET /chat/conversations/{id}/summary`, `DELETE /chat/conversations/{id}`, `POST /chat/feedback` 无变更。

## 前端设计

### 侧边栏结构

```
┌─────────────────────┐
│ GBase 助手      [←] │  品牌 + 收起按钮
│ [＋ 新建会话]        │  线框按钮
│                     │
│ 项目            [＋] │  分区标题 + 新建文件夹
│ ▸ 数据分析项目   12  │  折叠的文件夹（chevron + 名称 + 数量）
│ ▾ 运维监控        5  │  展开的文件夹
│   各部门销售统计     │    子级对话（缩进 20px）
│   用户留存分析       │
│ ▸ 日常查询        8  │
│                     │
│ 未分类              │
│   查询数据库连接状态  │
│   建表语句生成       │
└─────────────────────┘
```

### 交互行为

1. **文件夹**：点击展开/折叠，默认折叠。hover 时右侧出现「⋯」菜单（重命名、删除）
2. **新建文件夹**：「项目」行右侧「＋」按钮，弹出小型输入框就地创建
3. **批量管理**：顶部工具栏「管理」按钮进入多选模式，出现复选框 + 底部批量操作栏（移到文件夹、归档、删除）
4. **对话拖拽**：Phase 2（本次不做）
5. **对话右键菜单**：重命名、编辑标签、移动到文件夹、归档/取消归档、删除

### 归档 Bug 修复

**文件**: `frontend/src/components/layout/Sidebar.vue`

根因：`handleMenuSelect` 中 `conv.archived` 在 `archiveConv` 执行后被更新为新值，导致提示消息与实际操作相反。

```typescript
// 修复前
await chatStore.archiveConv(conv.id, !conv.archived)
naiveMsg.success(conv.archived ? '已取消归档' : '已归档')

// 修复后
const wasArchived = conv.archived
await chatStore.archiveConv(conv.id, !wasArchived)
naiveMsg.success(wasArchived ? '已取消归档' : '已归档')
```

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `backend/app/models/folder.py` | 新增 | Folder ORM 模型 |
| `backend/app/models/conversation.py` | 修改 | 新增 folder_id 外键 |
| `backend/app/schemas/chat.py` | 修改 | 新增 FolderResponse、BatchRequest schema |
| `backend/app/api/chat.py` | 修改 | 新增 folder CRUD + batch 端点，conversations 支持 folder_id 过滤 |
| `backend/app/services/conversation_service.py` | 修改 | 新增 folder 相关查询辅助函数 |
| `frontend/src/stores/chat.ts` | 修改 | 新增 folders 状态 + folder CRUD + 批量操作方法 |
| `frontend/src/components/layout/Sidebar.vue` | 重构 | 文件夹列表 + 展开折叠 + 批量模式 + 归档修复 |
| `frontend/src/api/chat.ts` | 修改 | 新增 folder + batch API 调用函数 |
| `backend/alembic/versions/` | 新增 | 数据库迁移脚本 |

## 视觉风格

参考 ChatGPT 侧边栏：
- 无 emoji，使用 SVG 图标（chevron、plus、ellipsis）
- 分区标题：11px、小写转大写、letter-spacing、低对比度灰色
- 对话项：「⋯」菜单仅在 hover 时出现
- 对话计数：浅灰色数字，安静不抢眼
- 文件夹：chevron 指示展开/折叠状态
- 批量管理栏：浮于底部，线框按钮

## 不在范围内（Phase 2+）

- 拖拽对话到文件夹
- 对话导出
- 文件夹颜色/图标自定义
- 回收站/软删除
