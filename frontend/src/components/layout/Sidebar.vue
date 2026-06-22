<script setup lang="ts">
import { onMounted, ref, nextTick, computed } from 'vue'
import type { DropdownOption } from 'naive-ui'
import {
  AddOutline,
  ChatbubbleOutline,
  EllipsisHorizontalOutline,
  CheckmarkOutline,
  CloseCircleOutline,
  SettingsOutline,
  AlertCircleOutline,
  TerminalOutline,
  BookOutline,
  FolderOutline,
  CheckboxOutline,
  SquareOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
} from '@vicons/ionicons5'
import { NIcon, NDropdown, NModal, NInput, useMessage } from 'naive-ui'
import { useChatStore } from '@/stores/chat'
import { useRoute, useRouter } from 'vue-router'

defineOptions({ name: 'AppSidebar' })

const props = defineProps<{ collapsed?: boolean }>()
const emit = defineEmits<{ 'update:collapsed': [boolean] }>()

const chatStore = useChatStore()
const router = useRouter()
const route = useRoute()
const naiveMsg = useMessage()

const editingId = ref<string | null>(null)
const editingTitle = ref('')
const editInput = ref<HTMLInputElement | null>(null)
const showTagModal = ref(false)
const tagEditingId = ref<string | null>(null)
const tagEditingValue = ref('')

// ── 批量管理模式 ──
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

function selectAllUnclassified() {
  unclassifiedConversations.value.forEach(c => selectedIds.value.add(c.id))
  // trigger reactivity
  selectedIds.value = new Set(selectedIds.value)
}

// ── 文件夹状态 ──
const expandedFolders = ref<Set<string>>(new Set())

function toggleFolder(id: string) {
  const next = new Set(expandedFolders.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedFolders.value = next
}

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

let _confirmingFolder = false
async function confirmAddFolder() {
  if (_confirmingFolder) return
  const name = newFolderName.value.trim()
  if (!name) { isAddingFolder.value = false; return }
  _confirmingFolder = true
  newFolderName.value = ''
  isAddingFolder.value = false
  await chatStore.addFolder(name)
  _confirmingFolder = false
}

function cancelAddFolder() { isAddingFolder.value = false }

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

type DeleteConversationTarget = { id: string; title: string }

const deleteConvTarget = ref<DeleteConversationTarget | null>(null)
const deleteConvModalVisible = ref(false)
const deleteFolderTarget = ref<string | null>(null)
const isDeletingConv = ref(false)
let deleteConvCloseTimer: ReturnType<typeof setTimeout> | null = null

async function confirmDeleteFolder(id: string) {
  deleteFolderTarget.value = id
}

async function doDeleteFolder() {
  if (!deleteFolderTarget.value) return
  await chatStore.removeFolder(deleteFolderTarget.value)
  naiveMsg.success('已删除')
  deleteFolderTarget.value = null
}

// Computed: conversations NOT in any folder
const unclassifiedConversations = computed(() =>
  chatStore.conversations.filter(c => !c.folder_id)
)

// Folder children for rendering
function conversationsInFolder(folderId: string) {
  return chatStore.conversations.filter(c => c.folder_id === folderId)
}

// ── 批量操作 ──
const showMoveMenu = ref(false)

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
  showMoveMenu.value = false
  naiveMsg.success('已移动')
}

onMounted(() => {
  chatStore.loadConversations()
  chatStore.loadFolders()
})

function toggleCollapse() {
  emit('update:collapsed', !props.collapsed)
}

function menuOptions(conv: { archived: boolean }): DropdownOption[] {
  const options: DropdownOption[] = [
    { label: '重命名', key: 'rename' },
  ]
  if (chatStore.folders.length > 0) {
    options.push({
      label: '移动到文件夹',
      key: 'move-to-folder',
      children: chatStore.folders.map(f => ({ label: f.name, key: `move-${f.id}` })),
    })
  }
  options.push(
    { label: conv.archived ? '取消归档' : '归档', key: 'archive' },
    { label: '删除', key: 'delete' },
  )
  return options
}

async function handleMenuSelect(key: string, conv: any) {
  if (key === 'rename') startRename(conv)
  else if (key.startsWith('move-')) {
    const folderId = key.slice(5)
    await chatStore.moveConvToFolder(conv.id, folderId)
    naiveMsg.success('已移动')
  }
  else if (key === 'archive') {
    const wasArchived = conv.archived
    await chatStore.archiveConv(conv.id, !wasArchived)
    naiveMsg.success(wasArchived ? '已取消归档' : '已归档')
  }
  else if (key === 'delete') confirmDelete(conv)
}

async function confirmTags() {
  if (!tagEditingId.value) return
  const tags = tagEditingValue.value.split(/[,，]/).map(t => t.trim()).filter(Boolean)
  try {
    await chatStore.setConvTags(tagEditingId.value, tags)
    naiveMsg.success('标签已更新')
  } catch {
    naiveMsg.error('更新失败')
  }
  tagEditingId.value = null
  showTagModal.value = false
}

function startRename(conv: { id: string; title: string | null }) {
  editingId.value = conv.id
  editingTitle.value = conv.title || ''
  nextTick(() => editInput.value?.focus())
}

async function confirmRename() {
  if (!editingId.value) return
  const title = editingTitle.value.trim()
  if (!title) { cancelRename(); return }
  try { await chatStore.renameConv(editingId.value, title) } catch { naiveMsg.error('重命名失败') }
  editingId.value = null
}

function cancelRename() { editingId.value = null }
function handleRenameKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') confirmRename()
  else if (e.key === 'Escape') cancelRename()
}

function clearDeleteConvCloseTimer() {
  if (deleteConvCloseTimer) {
    clearTimeout(deleteConvCloseTimer)
    deleteConvCloseTimer = null
  }
}

function closeDeleteConvModal() {
  deleteConvModalVisible.value = false
  clearDeleteConvCloseTimer()
  deleteConvCloseTimer = setTimeout(() => {
    if (!deleteConvModalVisible.value) {
      deleteConvTarget.value = null
    }
    deleteConvCloseTimer = null
  }, 240)
}

function handleDeleteConvModalShow(show: boolean) {
  if (show) {
    deleteConvModalVisible.value = true
    return
  }
  closeDeleteConvModal()
}

function confirmDelete(conv: { id: string; title: string | null }) {
  clearDeleteConvCloseTimer()
  deleteConvTarget.value = {
    id: conv.id,
    title: conv.title?.trim() || '未命名对话',
  }
  deleteConvModalVisible.value = true
}

async function doDeleteConv() {
  if (!deleteConvTarget.value || isDeletingConv.value) return
  const target = deleteConvTarget.value
  isDeletingConv.value = true
  closeDeleteConvModal()
  try {
    await chatStore.deleteConv(target.id)
    naiveMsg.success('已删除')
  } catch {
    naiveMsg.error('删除失败')
    clearDeleteConvCloseTimer()
    deleteConvTarget.value = target
    deleteConvModalVisible.value = true
  } finally {
    isDeletingConv.value = false
  }
}

function navigateTo(path: string) {
  router.push(path)
}

const navItems = [
  { path: '/sql-editor', icon: TerminalOutline, label: 'SQL 编辑器' },
  { path: '/tools/error-code', icon: AlertCircleOutline, label: '错误码查询' },
  { path: '/knowledge', icon: BookOutline, label: '知识库' },
  { path: '/settings', icon: SettingsOutline, label: '设置' },
]
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: props.collapsed }">
    <!-- Collapsed: icon-only narrow bar -->
    <template v-if="props.collapsed">
      <div class="collapsed-inner">
        <!-- Toggle expand -->
        <button class="collapsed-btn" @click="toggleCollapse" title="展开侧边栏">
          <n-icon :component="ChevronForwardOutline" size="16" />
        </button>

        <!-- New chat -->
        <button
          class="collapsed-btn primary"
          @click="chatStore.newConversation(); navigateTo('/')"
          title="新建会话"
        >
          <n-icon :component="AddOutline" size="16" />
        </button>

        <!-- Conversation dots -->
        <div class="collapsed-convs">
          <button
            v-for="conv in chatStore.conversations.slice(0, 8)"
            :key="conv.id"
            :class="['conv-dot', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
            :title="conv.title || '新对话'"
            @click="chatStore.loadConversation(conv.id); navigateTo('/')"
          />
        </div>

        <!-- Bottom nav icons -->
        <div class="collapsed-nav">
          <button
            v-for="item in navItems"
            :key="item.path"
            :class="['collapsed-btn', { active: route.path === item.path }]"
            :title="item.label"
            @click="navigateTo(item.path)"
          >
            <n-icon :component="item.icon" size="16" />
          </button>
        </div>
      </div>
    </template>

    <!-- Expanded: full sidebar -->
    <template v-else>
      <div class="sidebar-inner">
        <!-- Header -->
        <div class="sidebar-header">
          <div class="brand">
            <div class="brand-icon">G</div>
            <span class="brand-text">GBase Copilot</span>
          </div>
          <button class="collapse-btn" @click="toggleCollapse" title="收起侧边栏">
            <n-icon :component="ChevronBackOutline" size="16" />
          </button>
        </div>

        <!-- New Chat -->
        <button
          class="new-chat-btn"
          @click="chatStore.newConversation(); navigateTo('/')"
        >
          <n-icon :component="AddOutline" size="16" />
          <span>新建会话</span>
        </button>

        <!-- 项目文件夹 -->
        <div class="section-label-row">
          <span class="section-label">项目</span>
          <button class="add-folder-btn" @click="startAddFolder" title="新建文件夹">
            <n-icon :component="AddOutline" size="14" />
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
              <n-icon
                :component="ChevronForwardOutline"
                :class="['folder-chevron', { expanded: expandedFolders.has(folder.id) }]"
                size="12"
              />

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
                <n-icon :component="FolderOutline" size="16" class="folder-icon" />
                <span class="folder-name">{{ folder.name }}</span>
                <div class="folder-actions">
                  <button class="folder-action-btn" @click.stop="chatStore.activeFolderId = folder.id; chatStore.newConversation(); navigateTo('/')" title="在此文件夹新建对话">
                    <n-icon :component="AddOutline" size="14" />
                  </button>
                  <n-dropdown trigger="click" :options="[
                    { label: '重命名', key: 'rename' },
                    { label: '删除文件夹', key: 'delete' },
                  ]" @select="(key: string) => {
                    if (key === 'rename') startRenameFolder(folder.id, folder.name)
                    else if (key === 'delete') confirmDeleteFolder(folder.id)
                  }">
                    <button class="folder-action-btn" @click.stop>
                      <n-icon :component="EllipsisHorizontalOutline" size="14" />
                    </button>
                  </n-dropdown>
                </div>
              </template>
            </div>

            <!-- 展开的对话子列表 -->
            <div v-if="expandedFolders.has(folder.id)" class="folder-children">
              <div
                v-for="conv in conversationsInFolder(folder.id)"
                :key="conv.id"
                :class="['conv-item', 'conv-child', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
              >
                <button class="conv-main" @click="chatStore.loadConversation(conv.id); navigateTo('/')">
                  <n-icon :component="ChatbubbleOutline" size="13" class="conv-icon" />
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                </button>
                <n-dropdown v-if="!batchMode" trigger="click" :options="menuOptions(conv)" @select="(key: string) => handleMenuSelect(key, conv)">
                  <button class="action-btn more-btn" @click.stop>
                    <n-icon :component="EllipsisHorizontalOutline" size="14" />
                  </button>
                </n-dropdown>
              </div>
              <div v-if="conversationsInFolder(folder.id).length === 0" class="empty-folder">
                暂无对话
              </div>
            </div>
          </div>
        </nav>

        <!-- 未分类 -->
        <div class="section-label-row">
          <span class="section-label">未分类</span>
          <div style="display:flex;gap:4px;">
            <button v-if="batchMode" class="manage-toggle-btn" @click="selectAllUnclassified">全选</button>
            <button v-if="!batchMode" class="manage-toggle-btn" @click="toggleBatchMode">管理</button>
            <button v-else class="manage-toggle-btn active" @click="toggleBatchMode">完成</button>
          </div>
        </div>
        <nav class="conv-list">
          <div
            v-for="(conv, idx) in unclassifiedConversations"
            :key="conv.id"
            :class="['conv-item', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
            :style="{ animationDelay: `${idx * 30}ms` }"
          >
            <template v-if="editingId === conv.id">
              <input
                ref="editInput"
                v-model="editingTitle"
                class="rename-input"
                @keydown="handleRenameKeydown"
                @blur="confirmRename"
              />
              <button class="action-btn confirm" @mousedown.prevent="confirmRename">
                <n-icon :component="CheckmarkOutline" size="14" />
              </button>
              <button class="action-btn cancel" @mousedown.prevent="cancelRename">
                <n-icon :component="CloseCircleOutline" size="14" />
              </button>
            </template>
            <template v-else>
              <div v-if="batchMode" class="conv-checkbox" @click="toggleSelect(conv.id)">
                <n-icon
                  :component="selectedIds.has(conv.id) ? CheckboxOutline : SquareOutline"
                  :class="['checkbox-icon', { selected: selectedIds.has(conv.id) }]"
                  size="18"
                />
              </div>
              <button
                class="conv-main"
                @click="!batchMode && (chatStore.loadConversation(conv.id), navigateTo('/'))"
              >
                <n-icon :component="ChatbubbleOutline" size="14" class="conv-icon" />
                <div class="conv-text">
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                  <div v-if="conv.tags && conv.tags.length" class="conv-tags">
                    <span v-for="tag in conv.tags.slice(0, 3)" :key="tag" class="tag-pill">{{ tag }}</span>
                  </div>
                </div>
              </button>
              <n-dropdown v-if="!batchMode" trigger="click" :options="menuOptions(conv)" @select="(key) => handleMenuSelect(key as string, conv)">
                <button class="action-btn more-btn" title="更多" @click.stop>
                  <n-icon :component="EllipsisHorizontalOutline" size="14" />
                </button>
              </n-dropdown>
            </template>
          </div>
          <div v-if="chatStore.conversations.length === 0" class="no-conv">暂无对话历史</div>
        </nav>

        <!-- 批量操作栏 -->
        <div v-if="batchMode && selectedIds.size > 0" class="batch-bar">
          <span class="batch-count">已选 <strong>{{ selectedIds.size }}</strong> 项</span>
          <n-dropdown v-if="chatStore.folders.length > 0" trigger="click" :options="chatStore.folders.map(f => ({ label: f.name, key: f.id }))" @select="(key: string) => batchMove(key)">
            <button class="batch-btn">移到文件夹</button>
          </n-dropdown>
          <button v-else class="batch-btn" disabled style="opacity:0.4;cursor:not-allowed;" title="暂无可用的文件夹">移到文件夹</button>
          <button class="batch-btn" @click="batchArchive">归档</button>
          <button class="batch-btn danger" @click="batchDelete">删除</button>
        </div>

        <!-- Bottom Nav -->
        <div class="bottom-nav">
          <button
            v-for="item in navItems"
            :key="item.path"
            :class="['nav-item', { active: route.path === item.path }]"
            @click="navigateTo(item.path)"
          >
            <n-icon :component="item.icon" size="16" />
            <span>{{ item.label }}</span>
          </button>
        </div>
      </div>
    </template>
  </aside>

  <n-modal
    v-model:show="showTagModal"
    preset="dialog"
    title="编辑标签"
    positive-text="确认"
    negative-text="取消"
    :show-icon="false"
    @positive-click="confirmTags"
    @negative-click="showTagModal = false"
  >
    <n-input v-model:value="tagEditingValue" placeholder="输入标签，用逗号分隔" style="margin-top: 8px" />
  </n-modal>

  <!-- Delete Conversation Modal -->
  <n-modal
    :show="deleteConvModalVisible"
    :on-update:show="handleDeleteConvModalShow"
    transform-origin="center"
  >
    <div class="delete-modal">
      <div class="delete-modal-body">
        <div class="delete-modal-icon">
          <n-icon :component="AlertCircleOutline" size="24" />
        </div>
        <div class="delete-modal-title">确认删除对话？</div>
        <div class="delete-modal-desc">此操作将永久删除「{{ deleteConvTarget?.title }}」及其所有历史记录，且无法恢复。</div>
      </div>
      <div class="delete-modal-actions">
        <button class="delete-modal-btn cancel" :disabled="isDeletingConv" @click="closeDeleteConvModal">取消</button>
        <button class="delete-modal-btn confirm" :disabled="isDeletingConv" @click="doDeleteConv">
          {{ isDeletingConv ? '删除中...' : '确认删除' }}
        </button>
      </div>
    </div>
  </n-modal>

  <!-- Delete Folder Modal -->
  <n-modal
    :show="deleteFolderTarget !== null"
    :on-update:show="(v: boolean) => { if (!v) deleteFolderTarget = null }"
    transform-origin="center"
  >
    <div class="delete-modal">
      <div class="delete-modal-body">
        <div class="delete-modal-icon">
          <n-icon :component="AlertCircleOutline" size="24" />
        </div>
        <div class="delete-modal-title">确认删除文件夹？</div>
        <div class="delete-modal-desc">文件夹中的所有对话也会被删除，确定继续？</div>
      </div>
      <div class="delete-modal-actions">
        <button class="delete-modal-btn cancel" @click="deleteFolderTarget = null">取消</button>
        <button class="delete-modal-btn confirm" @click="doDeleteFolder">确认删除</button>
      </div>
    </div>
  </n-modal>
</template>

<style scoped>
/* ── Sidebar base ── */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  background: var(--bg-raised);
  border-right: 1px solid var(--seam-1);
  z-index: 100;
  transition: width var(--duration-normal) var(--ease-smooth);
  width: var(--sidebar-width);
}
.sidebar.collapsed {
  width: 48px;
}

/* ── Collapsed mode ── */
.collapsed-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  padding: 12px 0;
  gap: 8px;
}

.collapsed-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
  flex-shrink: 0;
}
.collapsed-btn .n-icon {
  opacity: 0.8;
}
.collapsed-btn:hover {
  background: var(--bg-hover);
  color: var(--text-1);
  border-color: var(--seam-1);
}
.collapsed-btn.primary {
  background: var(--text-0);
  border-color: var(--text-0);
  color: var(--bg-void);
}
.collapsed-btn.primary:hover {
  background: var(--text-1);
  border-color: var(--text-1);
}
.collapsed-btn.active {
  color: var(--text-0);
  background: var(--bg-hover);
}

.collapsed-convs {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px 0;
  overflow-y: auto;
  min-height: 0;
}

.conv-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--seam-1);
  border: none;
  cursor: pointer;
  padding: 0;
  transition: all var(--duration-fast);
  position: relative;
}
.conv-dot:hover {
  background: var(--text-3);
  transform: scale(1.3);
}
.conv-dot.active {
  background: var(--text-0);
}
.conv-dot.active::after {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  border: 1px solid var(--text-0);
  opacity: 0.3;
}

.collapsed-nav {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--seam-1);
  width: 32px;
}

/* ── Expanded mode ── */
.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px 12px 12px;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 4px 16px;
  min-height: 40px;
  border-bottom: 1px solid var(--seam-1);
  margin-bottom: 12px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.brand-icon {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  background: var(--text-0);
  color: var(--bg-void);
  border-radius: var(--radius-md);
  font-size: 15px;
  font-weight: 700;
  font-family: var(--font-mono);
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: -0.5px;
}
.brand-text {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-0);
  letter-spacing: -0.03em;
}

.collapse-btn {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: transparent;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.collapse-btn:hover {
  background: var(--bg-hover);
  border-color: var(--seam-2);
  color: var(--text-1);
}

/* ── New Chat Button ── */
.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--text-0);
  background: var(--text-0);
  color: var(--bg-void);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  margin-bottom: 12px;
  transition: all var(--duration-fast);
}
.new-chat-btn:hover {
  border-color: var(--text-1);
  background: var(--text-1);
}
.new-chat-btn:active {
  transform: scale(0.98);
}
.new-chat-btn .n-icon {
  color: currentColor;
  flex-shrink: 0;
}

/* ── Section Label ── */
.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-4);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 4px 6px 6px;
}

/* ── Conversation List ── */
.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  padding: 0 2px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  transition: all var(--duration-fast);
  width: 100%;
  animation: slideInLeft var(--duration-normal) var(--ease-out-expo) both;
  border: 1px solid transparent;
  position: relative;
}
.conv-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.conv-item.active {
  background: var(--bg-hover);
  color: var(--text-0);
}
.conv-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 2.5px;
  background: var(--text-0);
  border-radius: 0 3px 3px 0;
}

.conv-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 7px 8px;
  background: none;
  border: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-align: left;
  border-radius: var(--radius-sm);
}
.conv-icon {
  flex-shrink: 0;
  color: var(--text-4);
  opacity: 1;
}
.conv-item.active .conv-icon {
  color: var(--text-2);
}
.conv-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.conv-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}
.conv-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
  overflow: hidden;
}
.tag-pill {
  font-size: 10px;
  font-weight: 500;
  color: var(--text-3);
  background: var(--bg-surface);
  padding: 1px 5px;
  border-radius: 4px;
  white-space: nowrap;
  border: 1px solid var(--seam-1);
}

/* ── Actions ── */
.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 5px;
  color: var(--text-4);
  cursor: pointer;
  transition: all var(--duration-fast);
  opacity: 0;
  flex-shrink: 0;
}
.conv-item:hover .action-btn,
.conv-item.active .action-btn {
  opacity: 1;
}
.action-btn:hover {
  color: var(--text-1);
  background: var(--bg-active);
}
.action-btn.confirm:hover {
  color: var(--success);
  background: rgba(22, 163, 74, 0.08);
}
.action-btn.cancel:hover {
  color: var(--error);
  background: rgba(220, 38, 38, 0.08);
}

.rename-input {
  flex: 1;
  min-width: 0;
  padding: 5px 8px;
  font-size: 12px;
  font-family: var(--font-sans);
  border: 1px solid var(--seam-2);
  border-radius: var(--radius-sm);
  outline: none;
  background: var(--bg-surface);
  color: var(--text-0);
}

.no-conv {
  text-align: center;
  color: var(--text-4);
  font-size: 12px;
  padding: 28px 0;
}

/* ── Bottom Nav ── */
.bottom-nav {
  border-top: 1px solid var(--seam-1);
  margin-top: auto;
  padding-top: 8px;
  padding-bottom: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast);
  text-align: left;
}
.nav-item .n-icon {
  flex-shrink: 0;
  color: var(--text-4);
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.nav-item:hover .n-icon {
  color: var(--text-2);
}
.nav-item.active {
  background: var(--bg-hover);
  color: var(--text-0);
  font-weight: 600;
}
.nav-item.active .n-icon {
  color: var(--text-0);
}

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
.folder-input-row { padding: 4px 8px 8px; }

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
  gap: 7px;
  min-height: 34px;
  padding: 6px 7px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-2);
  transition: all var(--duration-fast);
}
.folder-item:hover,
.folder-item:focus-within {
  background: var(--bg-hover);
  color: var(--text-1);
  border-color: var(--seam-1);
}

.folder-chevron {
  flex-shrink: 0;
  transition: transform var(--duration-fast);
  color: var(--text-4);
}
.folder-chevron.expanded { transform: rotate(90deg); }

.folder-icon {
  flex-shrink: 0;
  color: var(--text-3);
  opacity: 0.86;
}

.folder-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}

.folder-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transform: translateX(2px);
  transition: opacity var(--duration-fast), transform var(--duration-fast);
  flex-shrink: 0;
}
.folder-item:hover .folder-actions,
.folder-item:focus-within .folder-actions {
  opacity: 1;
  transform: translateX(0);
}
.folder-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 6px;
  color: var(--text-4);
  cursor: pointer;
  flex-shrink: 0;
  transition: all var(--duration-fast);
}
.folder-action-btn:hover { background: var(--bg-active); color: var(--text-1); }

/* ── Folder Children ── */
.folder-children { padding-left: 18px; }

.conv-child { padding: 4px 8px; }
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
.checkbox-icon {
  color: var(--seam-2);
  transition: color var(--duration-fast);
}
.checkbox-icon.selected {
  color: var(--text-0);
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
  z-index: 5;
}

.batch-count {
  font-size: 12px;
  color: var(--text-3);
  flex: 1;
}
.batch-count strong { color: var(--text-0); }

.batch-btn {
  font-size: 12px;
  padding: 5px 12px;
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

/* ── Delete Modal ── */
.delete-modal {
  background: var(--bg-header);
  border-radius: 18px;
  overflow: hidden;
  width: 380px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  animation: modalIn 0.25s cubic-bezier(0.34,1.56,0.64,1) both;
}
.delete-modal-body {
  padding: 32px 24px 20px;
  text-align: center;
}
.delete-modal-icon {
  width: 52px; height: 52px;
  background: rgba(220, 38, 38, 0.08); border: 1px solid rgba(220, 38, 38, 0.18);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 16px;
  color: var(--error);
}
.delete-modal-title {
  font-size: 17px; font-weight: 700;
  color: var(--text-brand); letter-spacing: -0.01em;
  margin-bottom: 8px;
}
.delete-modal-desc {
  font-size: 13px; color: #888; line-height: 1.5;
  max-width: 280px; margin: 0 auto;
}
.delete-modal-actions {
  display: flex; border-top: 1px solid var(--seam-1);
}
.delete-modal-btn {
  flex: 1; padding: 14px;
  font-size: 14px; font-weight: 500;
  background: none; border: none; cursor: pointer;
  transition: background 0.15s;
}
.delete-modal-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}
.delete-modal-btn.cancel {
  color: var(--text-3); border-right: 1px solid var(--seam-1);
}
.delete-modal-btn.cancel:hover { background: var(--bg-hover); }
.delete-modal-btn.confirm {
  color: var(--error); font-weight: 600;
}
.delete-modal-btn.confirm:hover { background: rgba(220, 38, 38, 0.08); }

/* ── Mobile ── */
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    width: var(--sidebar-width) !important;
  }
  .sidebar.collapsed {
    transform: translateX(-100%);
  }
  .sidebar:not(.collapsed) {
    transform: translateX(0);
  }
}
</style>
