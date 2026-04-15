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
  MenuOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
} from '@vicons/ionicons5'
import { NIcon, NDropdown, NModal, NInput, useMessage, useDialog } from 'naive-ui'
import { useChatStore } from '@/stores/chat'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps<{
  open?: boolean
  collapsed?: boolean
}>()
const emit = defineEmits<{
  toggle: []
  'update:collapsed': [boolean]
}>()

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

onMounted(() => {
  chatStore.loadConversations()
})

function toggleCollapse() {
  emit('update:collapsed', !props.collapsed)
}

function handleSidebarClick() {
  if (props.collapsed) {
    toggleCollapse()
  }
}

function menuOptions(conv: { archived: boolean }): DropdownOption[] {
  return [
    { label: '重命名', key: 'rename' },
    { label: '编辑标签', key: 'tags' },
    { label: conv.archived ? '取消归档' : '归档', key: 'archive' },
    { label: '删除', key: 'delete' },
  ]
}

async function handleMenuSelect(
  key: string,
  conv: { id: string; title: string | null; tags: string[]; archived: boolean }
) {
  if (key === 'rename') {
    startRename(conv)
  } else if (key === 'tags') {
    tagEditingId.value = conv.id
    tagEditingValue.value = (conv.tags || []).join(', ')
    showTagModal.value = true
  } else if (key === 'archive') {
    try {
      await chatStore.archiveConv(conv.id, !conv.archived)
      naiveMsg.success(conv.archived ? '已取消归档' : '已归档')
    } catch {
      naiveMsg.error('操作失败')
    }
  } else if (key === 'delete') {
    confirmDelete(conv)
  }
}

async function confirmTags() {
  if (!tagEditingId.value) return
  const tags = tagEditingValue.value
    .split(/[,，]/)
    .map((t) => t.trim())
    .filter(Boolean)
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
  try {
    await chatStore.renameConv(editingId.value, title)
  } catch {
    naiveMsg.error('重命名失败')
  }
  editingId.value = null
}

function cancelRename() {
  editingId.value = null
}

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
      try {
        await chatStore.deleteConv(conv.id)
        naiveMsg.success('已删除')
      } catch {
        naiveMsg.error('删除失败')
      }
    },
  })
}

function navigateTo(path: string) {
  router.push(path)
}
</script>

<template>
  <aside class="sidebar" :class="{ 'is-open': open, collapsed }">
    <!-- 移动端遮罩 -->
    <div v-if="open" class="overlay" @click="$emit('toggle')" />

    <div class="sidebar-inner" @click="handleSidebarClick">
      <!-- Brand -->
      <div class="brand">
        <button class="menu-btn" @click.stop="$emit('toggle')">
          <n-icon :component="MenuOutline" size="18" />
        </button>
        <div class="brand-icon-wrap">
          <div class="brand-icon">G</div>
          <button class="collapse-btn logo-collapse" title="展开" @click.stop="toggleCollapse">
            <n-icon :component="ChevronForwardOutline" size="14" />
          </button>
        </div>
        <span v-if="!collapsed" class="brand-name">GBase 助手</span>
        <button v-if="!collapsed" class="collapse-btn side-collapse" title="收起" @click.stop="toggleCollapse">
          <n-icon :component="ChevronBackOutline" size="14" />
        </button>
      </div>

      <!-- New Chat -->
      <button class="new-chat-btn" :class="{ collapsed }" @click.stop="chatStore.newConversation(); navigateTo('/')">
        <n-icon :component="AddOutline" size="18" />
        <span v-if="!collapsed">新对话</span>
      </button>

      <!-- Conversation List (仅在展开时显示) -->
      <template v-if="!collapsed">
        <div class="section-label">最近对话</div>
        <nav class="conv-list">
          <div
            v-for="conv in chatStore.conversations"
            :key="conv.id"
            :class="['conv-item', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
          >
            <!-- Edit mode -->
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

            <!-- Normal mode -->
            <template v-else>
              <button class="conv-main" @click="chatStore.loadConversation(conv.id); navigateTo('/')">
                <n-icon :component="ChatbubbleEllipsesOutline" size="16" class="conv-icon" />
                <div class="conv-text">
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                  <div v-if="conv.tags && conv.tags.length" class="conv-tags">
                    <span v-for="tag in conv.tags.slice(0, 3)" :key="tag" class="tag-pill">{{ tag }}</span>
                  </div>
                </div>
              </button>
              <n-dropdown
                trigger="click"
                :options="menuOptions(conv)"
                @select="(key) => handleMenuSelect(key as string, conv)"
              >
                <button class="action-btn more-btn" title="更多" @click.stop>
                  <n-icon :component="EllipsisHorizontalOutline" size="16" />
                </button>
              </n-dropdown>
            </template>
          </div>
          <div v-if="chatStore.conversations.length === 0" class="no-conv">暂无对话历史</div>
        </nav>
      </template>

      <!-- Bottom Nav -->
      <div class="bottom-nav" :class="{ collapsed }">
        <button
          :class="['nav-item', { active: route.path === '/settings', collapsed }]"
          @click.stop="navigateTo('/settings')"
        >
          <n-icon :component="SettingsOutline" size="18" />
          <span v-if="!collapsed">设置</span>
        </button>
      </div>
    </div>

    <!-- Tag Edit Modal -->
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
      <n-input
        v-model:value="tagEditingValue"
        placeholder="输入标签，用逗号分隔"
        style="margin-top: 8px"
      />
    </n-modal>
  </aside>
</template>

<style scoped>
.sidebar {
  position: relative;
  flex-shrink: 0;
  width: var(--sidebar-width);
  height: 100%;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  transition: width 0.25s ease, background 0.2s ease;
}
.sidebar.collapsed {
  width: 68px;
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 14px 12px;
}

/* 移动端 */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    z-index: 100;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: var(--shadow-lg);
  }
  .sidebar.is-open {
    transform: translateX(0);
  }
  .sidebar.collapsed {
    width: var(--sidebar-width);
  }
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    z-index: 99;
  }
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 2px 16px;
}
.menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
}
.menu-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
@media (max-width: 768px) {
  .menu-btn { display: flex; }
}
.brand-icon-wrap {
  position: relative;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
}
.brand-icon {
  width: 40px;
  height: 40px;
  background: var(--accent);
  color: var(--text-inverse);
  border-radius: 10px;
  font-size: 16px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.collapse-btn {
  padding: 0;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: opacity 0.2s ease, background 0.15s ease, color 0.15s ease;
}
.logo-collapse {
  position: absolute;
  inset: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  opacity: 0;
}
.sidebar.collapsed .brand-icon-wrap:hover .logo-collapse {
  opacity: 1;
}
.side-collapse {
  width: 28px;
  height: 28px;
  margin-left: auto;
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-muted);
  border: 1px solid var(--border);
  opacity: 1;
}
.side-collapse:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.brand-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  margin-bottom: 14px;
  transition: all 0.15s ease;
}
.new-chat-btn:hover {
  background: var(--bg-hover);
  border-color: var(--border-strong);
}
.new-chat-btn.collapsed {
  padding: 0;
  width: 40px;
  height: 40px;
  margin: 0 auto 14px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 6px 6px 8px;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  transition: background 0.12s ease, color 0.12s ease;
  width: 100%;
}
.conv-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.conv-item.active {
  background: var(--bg-selected);
  color: var(--text-primary);
  font-weight: 500;
}

.conv-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  background: none;
  border: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
  text-align: left;
  border-radius: 6px;
}
.conv-icon {
  flex-shrink: 0;
  opacity: 0.55;
  font-size: 16px;
}
.conv-item.active .conv-icon {
  opacity: 0.85;
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
  color: var(--text-muted);
  background: var(--bg-active);
  padding: 1px 5px;
  border-radius: 4px;
  white-space: nowrap;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  background: none;
  border: none;
  border-radius: 6px;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s ease;
  opacity: 0;
}
.conv-item:hover .action-btn,
.conv-item.active .action-btn {
  opacity: 1;
}
.action-btn:hover {
  color: var(--text-primary);
  background: var(--bg-active);
}
.action-btn.confirm:hover {
  color: var(--success);
  background: rgba(16, 185, 129, 0.1);
}
.action-btn.cancel:hover {
  color: var(--error);
  background: rgba(239, 68, 68, 0.1);
}

.rename-input {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  font-size: 13px;
  font-family: var(--font-sans);
  border: 1px solid #93c5fd;
  border-radius: 6px;
  outline: none;
  background: var(--bg-primary);
  color: var(--text-primary);
}
.rename-input:focus {
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}

.no-conv {
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
  padding: 24px 0;
}

.bottom-nav {
  border-top: 1px solid var(--border);
  margin-top: 8px;
  padding-top: 8px;
}
.bottom-nav.collapsed {
  display: flex;
  justify-content: center;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  font-family: var(--font-sans);
  cursor: pointer;
  transition: all 0.12s ease;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--bg-selected);
  color: var(--text-primary);
}
.nav-item.collapsed {
  justify-content: center;
  padding: 0;
  width: 40px;
  height: 40px;
}
</style>
