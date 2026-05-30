# 对话列表管理功能增强 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为侧边栏对话列表新增项目文件夹分组、批量管理能力，修复归档消息提示 bug。设计参考 ChatGPT 极简风格。

**Architecture:** 新增 `Folder` 表（一对多关联 Conversation），后端提供文件夹 CRUD + 批量操作 API。前端重构 Sidebar 组件，实现文件夹展开/折叠、多选批量模式。归档 bug 修复涉及 Sidebar.vue 中的消息提示逻辑。

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy async + SQLite, Vue 3 + Naive UI + Pinia + TypeScript

**Spec:** `docs/superpowers/specs/2026-05-30-conversation-folder-management-design.md`

---

### Task 1: 后端 — Folder 模型 + 迁移

**Files:**
- Create: `backend/app/models/folder.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/conversation.py`
- Create: `backend/alembic/versions/<hash>_add_folders_table.py`

- [ ] **Step 1: 创建 Folder ORM 模型**

```python
# backend/app/models/folder.py
"""Folder ORM 模型 — 对话分组文件夹。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    conversations: Mapped[list["Conversation"]] = relationship(  # noqa: F821
        "Conversation", back_populates="folder", lazy="selectin"
    )
```

- [ ] **Step 2: 修改 Conversation 模型新增 folder_id**

```python
# backend/app/models/conversation.py — 在 archived 字段后添加：
folder_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True
)

# 在 messages relationship 后添加：
folder: Mapped["Folder | None"] = relationship("Folder", back_populates="conversations")  # noqa: F821
```

- [ ] **Step 3: 更新 models/__init__.py**

```python
# backend/app/models/__init__.py — 在现有 imports 中添加：
from app.models.folder import Folder

# 在 __all__ 中添加：
"Folder",
```

- [ ] **Step 4: 生成并编写迁移脚本**

Run: `cd backend && uv run alembic revision --autogenerate -m "add folders table and folder_id to conversations"`

验证生成的迁移脚本包含 `folders` 表创建和 `conversations.folder_id` 列。如果没有自动生成正确内容，手动编写：

```python
def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.add_column("conversations", sa.Column("folder_id", sa.String(36), nullable=True))
    op.create_foreign_key(None, "conversations", "folders", ["folder_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(None, "conversations", type_="foreignkey")
    op.drop_column("conversations", "folder_id")
    op.drop_table("folders")
```

- [ ] **Step 5: 运行迁移并验证**

```bash
cd backend && uv run alembic upgrade head
```

验证：`uv run python -c "from app.models.folder import Folder; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/folder.py backend/app/models/__init__.py backend/app/models/conversation.py backend/alembic/versions/
git commit -m "feat: add Folder model and migration"
```

---

### Task 2: 后端 — Schemas 扩展

**Files:**
- Modify: `backend/app/schemas/chat.py`

- [ ] **Step 1: 新增 FolderResponse 和 BatchRequest schema**

在 `backend/app/schemas/chat.py` 文件末尾添加：

```python
class FolderResponse(BaseModel):
    id: str
    name: str
    conversation_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchRequest(BaseModel):
    ids: list[str]
    action: str  # "archive" | "delete" | "move"
    folder_id: str | None = None  # required when action == "move"
```

在 `ConversationResponse` 中添加 `folder_id` 字段：

```python
class ConversationResponse(BaseModel):
    # ... existing fields ...
    folder_id: str | None = None  # 新增
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/chat.py
git commit -m "feat: add FolderResponse, BatchRequest schemas and folder_id to ConversationResponse"
```

---

### Task 3: 后端 — Folder CRUD API + Batch 端点

**Files:**
- Modify: `backend/app/api/chat.py`

- [ ] **Step 1: 添加 Folder CRUD 端点**

在 `backend/app/api/chat.py` 中添加（在现有 router 定义之后）：

```python
# ── Folder CRUD ──

@router.get("/folders", response_model=list[FolderResponse])
async def list_folders(db: AsyncSession = Depends(get_db)):
    """获取文件夹列表，含对话计数。"""
    from app.models.folder import Folder
    from sqlalchemy import func

    result = await db.execute(
        select(
            Folder,
            func.count(Conversation.id).label("conversation_count"),
        )
        .outerjoin(Conversation, Conversation.folder_id == Folder.id)
        .group_by(Folder.id)
        .order_by(Folder.updated_at.desc())
    )
    rows = result.all()
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            conversation_count=count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )
        for folder, count in rows
    ]


@router.post("/folders", response_model=FolderResponse)
async def create_folder(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """创建文件夹。payload: {"name": "文件夹名"}"""
    from app.models.folder import Folder

    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="文件夹名称不能为空")
    if len(name) > 100:
        raise HTTPException(status_code=422, detail="文件夹名称不能超过100个字符")

    folder = Folder(name=name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        conversation_count=0,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """重命名文件夹。payload: {"name": "新名称"}"""
    from app.models.folder import Folder

    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="文件夹名称不能为空")
    folder.name = name[:100]
    await db.commit()
    return {"ok": True}


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)):
    """删除文件夹及其中所有对话。"""
    from app.models.folder import Folder

    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")

    # 级联删除关联对话
    convs_result = await db.execute(
        select(Conversation).where(Conversation.folder_id == folder_id)
    )
    for conv in convs_result.scalars().all():
        await db.delete(conv)
    await db.delete(folder)
    await db.commit()
    return {"ok": True}
```

- [ ] **Step 2: 添加批量操作端点**

```python
@router.post("/conversations/batch")
async def batch_operate_conversations(
    payload: BatchRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """批量操作对话。action: archive | delete | move"""
    from app.models.folder import Folder

    if not payload.ids:
        raise HTTPException(status_code=422, detail="ids 不能为空")

    if payload.action == "move":
        if not payload.folder_id:
            raise HTTPException(status_code=422, detail="move 操作需要 folder_id")
        # 验证文件夹存在
        f_result = await db.execute(select(Folder).where(Folder.id == payload.folder_id))
        if not f_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="目标文件夹不存在")

    result = await db.execute(
        select(Conversation).where(Conversation.id.in_(payload.ids))
    )
    convs = result.scalars().all()

    if payload.action == "archive":
        for c in convs:
            c.archived = True
    elif payload.action == "delete":
        for c in convs:
            await db.delete(c)
    elif payload.action == "move":
        for c in convs:
            c.folder_id = payload.folder_id

    await db.commit()
    return {"ok": True, "affected": len(convs)}
```

- [ ] **Step 3: 修改 conversations 列表支持 folder_id 过滤**

修改 `GET /conversations` 端点：

```python
@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    folder_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.archived.is_(False))
    )
    if folder_id is not None:
        if folder_id == "":
            # 查询未分类的对话
            stmt = stmt.where(Conversation.folder_id.is_(None))
        else:
            stmt = stmt.where(Conversation.folder_id == folder_id)
    stmt = stmt.order_by(Conversation.updated_at.desc()).limit(50)
    result = await db.execute(stmt)
    convs = result.scalars().all()
    return [serialize_conversation(c) for c in convs]
```

- [ ] **Step 4: 修改 PATCH conversations 支持 folder_id**

在 `update_conversation` 的 payload 处理中添加：

```python
if "folder_id" in payload:
    fid = payload["folder_id"]
    if fid is not None and fid != "":
        # 验证文件夹存在
        from app.models.folder import Folder
        f_result = await db.execute(select(Folder).where(Folder.id == fid))
        if not f_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="文件夹不存在")
        conv.folder_id = fid
    else:
        conv.folder_id = None  # 移回未分类
```

- [ ] **Step 5: 运行测试验证**

```bash
cd backend && TESTING=1 uv run pytest -x -q --tb=short
```

Expected: all 177 tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat.py
git commit -m "feat: add folder CRUD, batch operations, and folder_id filter endpoints"
```

---

### Task 4: 前端 — API 层扩展

**Files:**
- Modify: `frontend/src/api/chat.ts`

- [ ] **Step 1: 添加文件夹和批量操作 API 接口**

在 `frontend/src/api/chat.ts` 中添加：

```typescript
// ── Folder types ──

export interface FolderResponse {
  id: string
  name: string
  conversation_count: number
  created_at: string
  updated_at: string
}

// ── Folder API ──

export async function listFolders(): Promise<FolderResponse[]> {
  const { data } = await apiClient.get<FolderResponse[]>('/chat/folders')
  return data
}

export async function createFolder(name: string): Promise<FolderResponse> {
  const { data } = await apiClient.post<FolderResponse>('/chat/folders', { name })
  return data
}

export async function updateFolder(id: string, name: string): Promise<void> {
  await apiClient.patch(`/chat/folders/${id}`, { name })
}

export async function deleteFolder(id: string): Promise<void> {
  await apiClient.delete(`/chat/folders/${id}`)
}

// ── Batch operations ──

export async function batchOperateConversations(
  ids: string[],
  action: 'archive' | 'delete' | 'move',
  folderId?: string
): Promise<{ affected: number }> {
  const { data } = await apiClient.post<{ affected: number }>('/chat/conversations/batch', {
    ids,
    action,
    folder_id: folderId ?? null,
  })
  return data
}
```

同时更新 `ConversationResponse` 接口添加 `folder_id`：

```typescript
export interface ConversationResponse {
  // ... existing fields ...
  folder_id: string | null  // 新增
}
```

更新 `updateConversation` 函数签名支持 `folder_id`：

```typescript
export async function updateConversation(
  id: string,
  payload: { title?: string; archived?: boolean; tags?: string[]; folder_id?: string | null }
): Promise<void> {
  await apiClient.patch(`/chat/conversations/${id}`, payload)
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/chat.ts
git commit -m "feat: add folder and batch operation API functions"
```

---

### Task 5: 前端 — Chat Store 扩展

**Files:**
- Modify: `frontend/src/stores/chat.ts`

- [ ] **Step 1: 添加 folders 状态和操作方法**

在 `frontend/src/stores/chat.ts` 的 store 中添加：

```typescript
import { listFolders, createFolder, updateFolder, deleteFolder, batchOperateConversations, type FolderResponse } from '@/api/chat'

// 在现有 refs 之后添加：
const folders = ref<FolderResponse[]>([])

// 文件夹 CRUD 方法：
async function loadFolders() {
  try {
    folders.value = await listFolders()
  } catch {
    // ignore
  }
}

async function addFolder(name: string) {
  const folder = await createFolder(name)
  folders.value.unshift(folder)
  return folder
}

async function renameFolder(id: string, name: string) {
  await updateFolder(id, name)
  const f = folders.value.find(f => f.id === id)
  if (f) f.name = name
}

async function removeFolder(id: string) {
  await deleteFolder(id)
  folders.value = folders.value.filter(f => f.id !== id)
  // 重新加载对话列表，因为文件夹中的对话被删除了
  await loadConversations()
}

// 批量操作：
async function batchOperate(ids: string[], action: 'archive' | 'delete' | 'move', folderId?: string) {
  await batchOperateConversations(ids, action, folderId)
  await Promise.all([loadConversations(), loadFolders()])
  // 如果当前对话被删除或归档，清空
  if (action === 'delete' && currentConversationId.value && ids.includes(currentConversationId.value)) {
    newConversation()
  }
}

// 在 return 中添加：
folders,
loadFolders,
addFolder,
renameFolder,
removeFolder,
batchOperate,
```

- [ ] **Step 2: 修改 loadConversations 支持 folder_id 过滤**

修改 `loadConversations`:

```typescript
async function loadConversations(folderId?: string | null) {
  try {
    const params: Record<string, string> = {}
    if (folderId !== undefined) {
      params.folder_id = folderId ?? ''
    }
    conversations.value = await listConversations(params)
  } catch {
    // ignore
  }
}
```

对应的 API 函数也需要更新以支持参数：

```typescript
// 在 frontend/src/api/chat.ts 中：
export async function listConversations(params?: Record<string, string>): Promise<ConversationResponse[]> {
  const query = params ? '?' + new URLSearchParams(params).toString() : ''
  const { data } = await apiClient.get<ConversationResponse[]>(`/chat/conversations${query}`)
  return data
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/chat.ts frontend/src/api/chat.ts
git commit -m "feat: extend chat store with folder state and batch operations"
```

---

### Task 6: 前端 — Sidebar 重构（文件夹 + 批量管理 + 归档修复）

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.vue`

- [ ] **Step 1: 修复归档 Bug**

找到 `handleMenuSelect` 中的 archive 分支，在 `Sidebar.vue` 中修改：

```typescript
// 修复前（line ~61-63）：
else if (key === 'archive') {
  await chatStore.archiveConv(conv.id, !conv.archived)
  naiveMsg.success(conv.archived ? '已取消归档' : '已归档')
}

// 修复后：
else if (key === 'archive') {
  const wasArchived = conv.archived
  await chatStore.archiveConv(conv.id, !wasArchived)
  naiveMsg.success(wasArchived ? '已取消归档' : '已归档')
}
```

- [ ] **Step 2: 添加 folders 加载和批量管理状态**

修改现有 `import { onMounted, ref, nextTick } from 'vue'` 为 `import { onMounted, ref, nextTick, computed } from 'vue'`。

在 `<script setup>` 中添加：

```typescript
// 批量管理模式
const batchMode = ref(false)
const selectedIds = ref<Set<string>>(new Set())

function toggleBatchMode() {
  batchMode.value = !batchMode.value
  if (!batchMode.value) selectedIds.value.clear()
}

function toggleSelect(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function selectAll() {
  const visibleIds = chatStore.conversations.map(c => c.id)
  selectedIds.value = new Set(visibleIds)
}

async function batchArchive() {
  await chatStore.batchOperate([...selectedIds.value], 'archive')
  selectedIds.value.clear()
  batchMode.value = false
  naiveMsg.success('已归档')
}

async function batchDelete() {
  await chatStore.batchOperate([...selectedIds.value], 'delete')
  selectedIds.value.clear()
  batchMode.value = false
  naiveMsg.success('已删除')
}

async function batchMove(folderId: string) {
  await chatStore.batchOperate([...selectedIds.value], 'move', folderId)
  selectedIds.value.clear()
  batchMode.value = false
  naiveMsg.success('已移动')
}

// 文件夹展开状态
const expandedFolders = ref<Set<string>>(new Set())

function toggleFolder(id: string) {
  const next = new Set(expandedFolders.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedFolders.value = next
}

// 新建文件夹
const newFolderName = ref('')
const isAddingFolder = ref(false)

function startAddFolder() {
  isAddingFolder.value = true
  newFolderName.value = ''
  nextTick(() => {
    const input = document.querySelector('.folder-name-input') as HTMLInputElement
    input?.focus()
  })
}

async function confirmAddFolder() {
  const name = newFolderName.value.trim()
  if (!name) { isAddingFolder.value = false; return }
  await chatStore.addFolder(name)
  isAddingFolder.value = false
}

function cancelAddFolder() { isAddingFolder.value = false }

// 文件夹右键/菜单操作
const folderMenuId = ref<string | null>(null)
const editingFolderId = ref<string | null>(null)
const editingFolderName = ref('')

function startRenameFolder(id: string, name: string) {
  editingFolderId.value = id
  editingFolderName.value = name
  nextTick(() => {
    const input = document.querySelector('.folder-rename-input') as HTMLInputElement
    input?.focus()
  })
}

async function confirmRenameFolder() {
  if (!editingFolderId.value) return
  const name = editingFolderName.value.trim()
  if (!name) { editingFolderId.value = null; return }
  await chatStore.renameFolder(editingFolderId.value, name)
  editingFolderId.value = null
}

function cancelRenameFolder() { editingFolderId.value = null }

async function confirmDeleteFolder(id: string) {
  dialog.warning({
    title: '删除文件夹',
    content: '文件夹中的所有对话也会被删除，确定继续？',
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await chatStore.removeFolder(id)
      naiveMsg.success('已删除')
    },
  })
}

// 加载文件夹
onMounted(() => {
  chatStore.loadFolders()
})
```

- [ ] **Step 3: 重构模板 — 文件夹区域**

在「新建会话」按钮之后、「最近对话」之前插入文件夹区域：

```html
<!-- 新建会话按钮保持不变 -->

<!-- 项目文件夹 -->
<div class="section-label-row">
  <span class="section-label">项目</span>
  <button class="add-folder-btn" @click="startAddFolder" title="新建文件夹">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
  </button>
</div>

<!-- 新建文件夹输入框 -->
<div v-if="isAddingFolder" class="folder-input-row">
  <input
    v-model="newFolderName"
    class="folder-name-input"
    placeholder="文件夹名称"
    maxlength="100"
    @keydown.enter="confirmAddFolder"
    @keydown.escape="cancelAddFolder"
    @blur="confirmAddFolder"
  />
</div>

<!-- 文件夹列表 -->
<nav class="folder-list">
  <div v-for="folder in chatStore.folders" :key="folder.id" class="folder-group">
    <div class="folder-item" @click="toggleFolder(folder.id)">
      <svg
        :class="['folder-chevron', { expanded: expandedFolders.has(folder.id) }]"
        width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
      ><path d="M9 18l6-6-6-6"/></svg>

      <!-- 编辑模式 -->
      <template v-if="editingFolderId === folder.id">
        <input
          v-model="editingFolderName"
          class="folder-rename-input"
          maxlength="100"
          @keydown.enter="confirmRenameFolder"
          @keydown.escape="cancelRenameFolder"
          @blur="confirmRenameFolder"
          @click.stop
        />
      </template>
      <template v-else>
        <span class="folder-name">{{ folder.name }}</span>
        <span class="folder-count">{{ folder.conversation_count }}</span>
      </template>

      <!-- ⋯ 菜单 (hover 显示) -->
      <n-dropdown trigger="click" :options="[
        { label: '重命名', key: 'rename' },
        { label: '删除文件夹', key: 'delete' },
      ]" @select="(key) => {
        if (key === 'rename') startRenameFolder(folder.id, folder.name)
        else if (key === 'delete') confirmDeleteFolder(folder.id)
      }">
        <button class="folder-more-btn" @click.stop>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
        </button>
      </n-dropdown>
    </div>

    <!-- 展开后的子对话列表 -->
    <div v-if="expandedFolders.has(folder.id)" class="folder-children">
      <div
        v-for="conv in chatStore.conversations.filter(c => c.folder_id === folder.id)"
        :key="conv.id"
        :class="['conv-item', 'conv-child', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
      >
        <button class="conv-main" @click="chatStore.loadConversation(conv.id); navigateTo('/')">
          <span class="conv-title">{{ conv.title || '新对话' }}</span>
        </button>
      </div>
      <div v-if="chatStore.conversations.filter(c => c.folder_id === folder.id).length === 0" class="empty-folder">
        暂无对话
      </div>
    </div>
  </div>
</nav>
```

- [ ] **Step 4: 重构模板 — 未分类 + 批量管理栏**

```html
<!-- 未分类 -->
<div class="section-label-row">
  <span class="section-label">未分类</span>
  <button v-if="!batchMode" class="manage-toggle-btn" @click="toggleBatchMode">管理</button>
  <button v-else class="manage-toggle-btn active" @click="toggleBatchMode">完成</button>
</div>

<nav class="conv-list">
  <div
    v-for="(conv, idx) in unclassifiedConversations"
    :key="conv.id"
    :class="['conv-item', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
  >
    <!-- 批量模式下的复选框 -->
    <div v-if="batchMode" class="conv-checkbox" @click="toggleSelect(conv.id)">
      <svg v-if="selectedIds.has(conv.id)" width="18" height="18" viewBox="0 0 24 24" fill="#1a1a1a" stroke="#1a1a1a" stroke-width="2"><path d="M9 12l2 2 4-4"/><rect x="3" y="3" width="18" height="18" rx="4"/></svg>
      <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="4"/></svg>
    </div>
    <!-- 原有对话项内容 -->
    <button class="conv-main" @click="!batchMode && (chatStore.loadConversation(conv.id), navigateTo('/'))">
      <span class="conv-title">{{ conv.title || '新对话' }}</span>
    </button>
    <!-- 原有⋯菜单 (非批量模式) -->
    <n-dropdown v-if="!batchMode" trigger="click" :options="menuOptions(conv)" @select="(key) => handleMenuSelect(key as string, conv)">
      <button class="action-btn more-btn" @click.stop>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg>
      </button>
    </n-dropdown>
  </div>
</nav>

<!-- 批量操作栏 -->
<div v-if="batchMode && selectedIds.size > 0" class="batch-bar">
  <span class="batch-count">已选 {{ selectedIds.size }} 项</span>
  <button class="batch-btn" @click="showMoveMenu = true">移到文件夹</button>
  <button class="batch-btn" @click="batchArchive">归档</button>
  <button class="batch-btn danger" @click="batchDelete">删除</button>
</div>
```

- [ ] **Step 5: 添加 computed 和 CSS**

添加 computed 属性：

```typescript
const unclassifiedConversations = computed(() =>
  chatStore.conversations.filter(c => !c.folder_id)
)
```

添加 CSS 样式（在原有 `<style scoped>` 中追加）：

```css
/* ── Section Label Row ── */
.section-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 8px 6px;
}

.add-folder-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 4px;
  color: var(--text-4);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.add-folder-btn:hover { color: var(--text-1); background: var(--bg-hover); }

/* ── Folder Input ── */
.folder-input-row {
  padding: 4px 8px 8px;
}
.folder-name-input,
.folder-rename-input {
  width: 100%;
  padding: 6px 10px;
  font-size: 13px;
  border: 1px solid var(--seam-2);
  border-radius: 6px;
  outline: none;
  background: var(--bg-surface);
  color: var(--text-0);
  font-family: var(--font-sans);
}

/* ── Folder List ── */
.folder-list { padding: 0 2px; }

.folder-group { margin-bottom: 1px; }

.folder-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-2);
  transition: all var(--duration-fast);
}
.folder-item:hover { background: var(--bg-hover); color: var(--text-1); }

.folder-chevron {
  flex-shrink: 0;
  transition: transform var(--duration-fast);
  opacity: 0.5;
}
.folder-chevron.expanded { transform: rotate(90deg); }

.folder-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}

.folder-count {
  font-size: 11px;
  color: var(--text-4);
}

.folder-more-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 4px;
  color: var(--text-4);
  cursor: pointer;
  flex-shrink: 0;
}
.folder-item:hover .folder-more-btn { display: flex; }
.folder-more-btn:hover { background: var(--bg-hover); color: var(--text-1); }

/* ── Folder Children ── */
.folder-children { padding-left: 18px; }

.conv-child {
  padding: 4px 8px;
}
.conv-child .conv-title { font-size: 12px; }

.empty-folder {
  font-size: 11px;
  color: var(--text-4);
  padding: 6px 10px;
  text-align: center;
}

/* ── Batch Mode ── */
.manage-toggle-btn {
  font-size: 11px;
  padding: 2px 8px;
  background: none;
  border: 1px solid var(--seam-1);
  border-radius: 4px;
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
  font-family: var(--font-sans);
}
.manage-toggle-btn:hover { border-color: var(--seam-2); color: var(--text-1); }
.manage-toggle-btn.active { background: var(--bg-hover); color: var(--text-0); border-color: var(--seam-2); }

.conv-checkbox {
  display: flex;
  align-items: center;
  padding: 0 4px;
  cursor: pointer;
  flex-shrink: 0;
}

.batch-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--bg-surface);
  border-top: 1px solid var(--seam-1);
  margin-top: 8px;
  border-radius: 0 0 var(--radius-sm) var(--radius-sm);
}

.batch-count {
  font-size: 12px;
  color: var(--text-3);
  flex: 1;
}

.batch-count strong { color: var(--text-0); }

.batch-btn {
  font-size: 12px;
  padding: 4px 12px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-1);
  border-radius: 6px;
  color: var(--text-2);
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all var(--duration-fast);
}
.batch-btn:hover { border-color: var(--seam-2); color: var(--text-0); }
.batch-btn.danger { color: var(--error); border-color: var(--error); }
.batch-btn.danger:hover { background: var(--error); color: #fff; }
```

- [ ] **Step 6: 验证前端编译**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

修复所有类型错误。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/layout/Sidebar.vue
git commit -m "feat: redesign sidebar with folders, batch mode, and archive fix"
```

---

### Task 7: 集成验证与最终提交

- [ ] **Step 1: 运行完整后端测试**

```bash
cd backend && TESTING=1 uv run pytest -x -q --tb=short
```
Expected: all tests pass

- [ ] **Step 2: 运行数据库迁移验证**

```bash
cd backend && uv run alembic upgrade head && uv run alembic check
```
Expected: no pending migrations

- [ ] **Step 3: 手动验证 UI**

启动前后端：`make dev-backend` + `make dev-frontend`，验证：
- 新建文件夹 → 出现在侧边栏
- 重命名文件夹 → 立即更新
- 删除文件夹 → 二次确认 → 级联删除
- 文件夹展开/折叠
- 批量模式 → 多选 → 批量归档/删除/移动
- 归档操作 → 提示 "已归档"（不是 "已取消归档"）
- 切换对话 → 不再丢失消息（上一轮的修复）

- [ ] **Step 4: 最终 Commit**

```bash
git add -A
git commit -m "chore: final verification and cleanup for folder management"
```
