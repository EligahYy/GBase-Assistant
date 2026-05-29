<script setup lang="ts">
import { onMounted, ref, nextTick } from 'vue'
import type { DropdownOption } from 'naive-ui'
import {
  AddOutline,
  ChatbubbleEllipsesOutline,
  EllipsisHorizontalOutline,
  CheckmarkOutline,
  CloseCircleOutline,
  SettingsOutline,
  AlertCircleOutline,
  TerminalOutline,
  GridOutline,
  SpeedometerOutline,
  LibraryOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
} from '@vicons/ionicons5'
import { NIcon, NDropdown, NModal, NInput, useMessage, useDialog } from 'naive-ui'
import { useChatStore } from '@/stores/chat'
import { useRoute, useRouter } from 'vue-router'

defineOptions({ name: 'AppSidebar' })

const props = defineProps<{ collapsed?: boolean }>()
const emit = defineEmits<{ 'update:collapsed': [boolean] }>()

const chatStore = useChatStore()
const router = useRouter()
const route = useRoute()
const naiveMsg = useMessage()
const dialog = useDialog()

const editingId = ref<string | null>(null)
const editingTitle = ref('')
const editInput = ref<HTMLInputElement | null>(null)
const showTagModal = ref(false)
const tagEditingId = ref<string | null>(null)
const tagEditingValue = ref('')

onMounted(() => { chatStore.loadConversations() })

function toggleCollapse() {
  emit('update:collapsed', !props.collapsed)
}

function menuOptions(conv: { archived: boolean }): DropdownOption[] {
  return [
    { label: '重命名', key: 'rename' },
    { label: '编辑标签', key: 'tags' },
    { label: conv.archived ? '取消归档' : '归档', key: 'archive' },
    { label: '删除', key: 'delete' },
  ]
}

async function handleMenuSelect(key: string, conv: any) {
  if (key === 'rename') startRename(conv)
  else if (key === 'tags') {
    tagEditingId.value = conv.id
    tagEditingValue.value = (conv.tags || []).join(', ')
    showTagModal.value = true
  }
  else if (key === 'archive') {
    await chatStore.archiveConv(conv.id, !conv.archived)
    naiveMsg.success(conv.archived ? '已取消归档' : '已归档')
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

function confirmDelete(conv: { id: string; title: string | null }) {
  dialog.warning({
    title: '删除对话',
    content: `确定删除「${conv.title || '新对话'}」？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try { await chatStore.deleteConv(conv.id); naiveMsg.success('已删除') } catch { naiveMsg.error('删除失败') }
    },
  })
}

function navigateTo(path: string) {
  router.push(path)
}

const navItems = [
  { path: '/data-browser', icon: GridOutline, label: '数据浏览' },
  { path: '/sql-editor', icon: TerminalOutline, label: 'SQL 编辑器' },
  { path: '/insights', icon: SpeedometerOutline, label: '性能洞察' },
  { path: '/tools/error-code', icon: AlertCircleOutline, label: '错误码查询' },
  { path: '/knowledge', icon: LibraryOutline, label: '知识库' },
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
            <span class="brand-text">GBase</span>
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

        <!-- Conversation List -->
        <div class="section-label">最近对话</div>
        <nav class="conv-list">
          <div
            v-for="(conv, idx) in chatStore.conversations"
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
              <button
                class="conv-main"
                @click="chatStore.loadConversation(conv.id); navigateTo('/')"
              >
                <n-icon :component="ChatbubbleEllipsesOutline" size="14" class="conv-icon" />
                <div class="conv-text">
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                  <div v-if="conv.tags && conv.tags.length" class="conv-tags">
                    <span v-for="tag in conv.tags.slice(0, 3)" :key="tag" class="tag-pill">{{ tag }}</span>
                  </div>
                </div>
              </button>
              <n-dropdown trigger="click" :options="menuOptions(conv)" @select="(key) => handleMenuSelect(key as string, conv)">
                <button class="action-btn more-btn" title="更多" @click.stop>
                  <n-icon :component="EllipsisHorizontalOutline" size="14" />
                </button>
              </n-dropdown>
            </template>
          </div>
          <div v-if="chatStore.conversations.length === 0" class="no-conv">暂无对话历史</div>
        </nav>

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
</template>

<style scoped>
/* ── Sidebar base ── */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  background: var(--bg-surface);
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
  font-weight: 600;
  color: var(--text-0);
  letter-spacing: -0.01em;
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
  border: 1px solid var(--seam-1);
  background: var(--bg-panel);
  color: var(--text-1);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  margin-bottom: 12px;
  transition: all var(--duration-fast);
}
.new-chat-btn:hover {
  border-color: var(--seam-2);
  background: var(--bg-raised);
}
.new-chat-btn:active {
  transform: scale(0.98);
}
.new-chat-btn .n-icon {
  color: var(--text-2);
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
  opacity: 0.4;
}
.conv-item.active .conv-icon {
  opacity: 0.7;
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
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.nav-item.active {
  background: var(--bg-hover);
  color: var(--text-0);
  font-weight: 600;
}

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
