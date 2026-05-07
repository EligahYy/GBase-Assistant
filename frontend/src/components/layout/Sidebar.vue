<script setup lang="ts">
 
defineOptions({ name: 'AppSidebar' })
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
  AlertCircleOutline,
} from '@vicons/ionicons5'
import { NIcon, NDropdown, NModal, NInput, useMessage, useDialog } from 'naive-ui'
import { useChatStore } from '@/stores/chat'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps<{ open?: boolean; collapsed?: boolean }>()
const emit = defineEmits<{ toggle: []; 'update:collapsed': [boolean] }>()

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

function toggleCollapse() { emit('update:collapsed', !props.collapsed) }
function handleSidebarClick() { if (props.collapsed) toggleCollapse() }

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
  else if (key === 'tags') { tagEditingId.value = conv.id; tagEditingValue.value = (conv.tags || []).join(', '); showTagModal.value = true }
  else if (key === 'archive') { await chatStore.archiveConv(conv.id, !conv.archived); naiveMsg.success(conv.archived ? '已取消归档' : '已归档') }
  else if (key === 'delete') confirmDelete(conv)
}

async function confirmTags() {
  if (!tagEditingId.value) return
  const tags = tagEditingValue.value.split(/[,，]/).map(t => t.trim()).filter(Boolean)
  try { await chatStore.setConvTags(tagEditingId.value, tags); naiveMsg.success('标签已更新') } catch { naiveMsg.error('更新失败') }
  tagEditingId.value = null; showTagModal.value = false
}

function startRename(conv: { id: string; title: string | null }) {
  editingId.value = conv.id; editingTitle.value = conv.title || ''
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

function navigateTo(path: string) { router.push(path) }
</script>

<template>
  <aside class="sidebar" :class="{ 'is-open': open, collapsed }">
    <div v-if="open" class="overlay" @click="$emit('toggle')" />
    <button
      class="collapse-handle"
      :title="collapsed ? '展开侧边栏' : '收起侧边栏'"
      :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
      @click.stop="toggleCollapse"
    >
      <n-icon :component="ChevronBackOutline" size="14" class="handle-icon" />
    </button>
    <div class="sidebar-inner" @click="handleSidebarClick">
      <!-- Brand -->
      <div class="brand">
        <button class="menu-btn" @click.stop="$emit('toggle')">
          <n-icon :component="MenuOutline" size="18" />
        </button>
        <div class="brand-icon">G</div>
        <span v-if="!collapsed" class="brand-name">GBase 8a</span>
      </div>

      <!-- New Chat -->
      <button class="new-chat-btn" :class="{ collapsed }" @click.stop="chatStore.newConversation(); navigateTo('/')">
        <n-icon :component="AddOutline" size="16" />
        <span v-if="!collapsed">新对话</span>
      </button>

      <!-- Conversation List -->
      <template v-if="!collapsed">
        <div class="section-label">最近对话</div>
        <nav class="conv-list">
          <div
            v-for="(conv, idx) in chatStore.conversations"
            :key="conv.id"
            :class="['conv-item', { active: conv.id === chatStore.currentConversationId && route.path === '/' }]"
            :style="{ animationDelay: `${idx * 40}ms` }"
          >
            <template v-if="editingId === conv.id">
              <input ref="editInput" v-model="editingTitle" class="rename-input" @keydown="handleRenameKeydown" @blur="confirmRename" />
              <button class="action-btn confirm" @mousedown.prevent="confirmRename">
                <n-icon :component="CheckmarkOutline" size="14" />
              </button>
              <button class="action-btn cancel" @mousedown.prevent="cancelRename">
                <n-icon :component="CloseCircleOutline" size="14" />
              </button>
            </template>
            <template v-else>
              <button class="conv-main" @click="chatStore.loadConversation(conv.id); navigateTo('/')">
                <n-icon :component="ChatbubbleEllipsesOutline" size="15" class="conv-icon" />
                <div class="conv-text">
                  <span class="conv-title">{{ conv.title || '新对话' }}</span>
                  <div v-if="conv.tags && conv.tags.length" class="conv-tags">
                    <span v-for="tag in conv.tags.slice(0, 3)" :key="tag" class="tag-pill">{{ tag }}</span>
                  </div>
                </div>
              </button>
              <n-dropdown trigger="click" :options="menuOptions(conv)" @select="(key) => handleMenuSelect(key as string, conv)">
                <button class="action-btn more-btn" title="更多" @click.stop>
                  <n-icon :component="EllipsisHorizontalOutline" size="15" />
                </button>
              </n-dropdown>
            </template>
          </div>
          <div v-if="chatStore.conversations.length === 0" class="no-conv">暂无对话历史</div>
        </nav>
      </template>

      <!-- Bottom Nav -->
      <div class="bottom-nav" :class="{ collapsed }">
        <button :class="['nav-item', { active: route.path === '/tools/error-code', collapsed }]" @click.stop="navigateTo('/tools/error-code')">
          <n-icon :component="AlertCircleOutline" size="16" />
          <span v-if="!collapsed">错误码查询</span>
        </button>
        <button :class="['nav-item', { active: route.path === '/settings', collapsed }]" @click.stop="navigateTo('/settings')">
          <n-icon :component="SettingsOutline" size="16" />
          <span v-if="!collapsed">设置</span>
        </button>
      </div>
    </div>

    <n-modal v-model:show="showTagModal" preset="dialog" title="编辑标签" positive-text="确认" negative-text="取消" :show-icon="false"
      @positive-click="confirmTags" @negative-click="showTagModal = false">
      <n-input v-model:value="tagEditingValue" placeholder="输入标签，用逗号分隔" style="margin-top: 8px" />
    </n-modal>
  </aside>
</template>

<style scoped>
.sidebar {
  position: relative;
  flex-shrink: 0;
  width: var(--sidebar-width);
  height: 100%;
  background: var(--bg-deep);
  border-right: 1px solid var(--seam-1);
  transition: width var(--duration-normal) var(--ease-smooth);
}
/* Subtle top glow — like instrument panel edge light */
.sidebar::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent-dim), transparent);
}
.sidebar.collapsed { width: 72px; }

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 20px 14px;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed; top: 0; left: 0; z-index: 100;
    transform: translateX(-100%);
    transition: transform var(--duration-normal) var(--ease-smooth);
  }
  .sidebar.is-open { transform: translateX(0); }
  .sidebar.collapsed { width: var(--sidebar-width); }
  .collapse-handle { display: none; }
  .overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.6);
    backdrop-filter: blur(8px);
    z-index: 99;
  }
}

/* Brand — Signal beacon */
.brand {
  display: flex; align-items: center; gap: 12px;
  padding: 2px 2px 20px;
}
.menu-btn {
  display: none; align-items: center; justify-content: center;
  width: 32px; height: 32px; padding: 0;
  background: var(--bg-panel); border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  color: var(--text-4); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-smooth);
}
.menu-btn:hover { border-color: var(--seam-2); color: var(--text-1); }
@media (max-width: 768px) { .menu-btn { display: flex; } }

.brand-icon {
  flex-shrink: 0;
  width: 28px; height: 28px;
  background: var(--bg-panel);
  border: 1px solid var(--seam-2);
  color: var(--accent); border-radius: var(--radius-sm);
  font-size: 12px; font-weight: 700;
  font-family: var(--font-mono);
  display: flex; align-items: center; justify-content: center;
  position: relative; overflow: hidden;
}
.brand-icon::before {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, var(--accent), transparent 60%);
  opacity: 0.4;
}

.brand-name {
  font-size: 15px; font-weight: 600;
  color: var(--text-0); letter-spacing: -0.02em;
  white-space: nowrap;
}

/* Collapse handle — floating on seam */
.collapse-handle {
  position: absolute;
  top: 28px;
  right: -12px;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  background: var(--bg-panel);
  border: 1px solid var(--seam-2);
  border-radius: 50%;
  color: var(--text-3);
  cursor: pointer;
  z-index: 20;
  opacity: 0;
  box-shadow: var(--shadow-sm);
  transition:
    opacity var(--duration-fast) var(--ease-smooth),
    color var(--duration-fast) var(--ease-smooth),
    border-color var(--duration-fast) var(--ease-smooth),
    background var(--duration-fast) var(--ease-smooth),
    transform var(--duration-fast) var(--ease-smooth);
}
.sidebar:hover .collapse-handle,
.sidebar.collapsed .collapse-handle,
.collapse-handle:focus-visible {
  opacity: 1;
}
.collapse-handle:hover {
  background: var(--bg-surface);
  border-color: var(--accent-bright);
  color: var(--accent);
  box-shadow: 0 0 12px var(--accent-glow);
  transform: scale(1.1);
}
.collapse-handle:active {
  transform: scale(0.92);
}
.handle-icon {
  display: flex;
  transition: transform var(--duration-normal) var(--ease-spring);
}
.sidebar.collapsed .handle-icon {
  transform: rotate(180deg);
}

/* New Chat Button */
.new-chat-btn {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--seam-2);
  background: var(--bg-panel);
  color: var(--text-1);
  font-size: 13px; font-weight: 500; font-family: var(--font-sans);
  cursor: pointer; margin-bottom: 20px;
  transition: all var(--duration-fast);
  position: relative; overflow: hidden;
}
.new-chat-btn:hover {
  border-color: var(--seam-3);
  background: var(--bg-surface);
}
.new-chat-btn:active { transform: scale(0.98); }
.new-chat-btn svg { width: 14px; height: 14px; color: var(--accent); }
.new-chat-btn.collapsed {
  padding: 0; width: 40px; height: 40px; margin: 0 auto 20px;
}

/* Section Label */
.section-label {
  font-size: 10px; font-weight: 700;
  color: var(--text-4); letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 12px 10px 6px;
}

/* Conversation List */
.conv-list {
  flex: 1; overflow-y: auto;
  display: flex; flex-direction: column; gap: 1px;
  min-height: 0;
  padding: 0 2px;
}

.conv-item {
  display: flex; align-items: center; gap: 6px;
  padding: 2px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-3);
  font-size: 13px; font-weight: 500;
  transition: all var(--duration-fast);
  width: 100%;
  animation: slideInLeft var(--duration-normal) var(--ease-out-expo) both;
  border: 1px solid transparent;
}
.conv-item:hover {
  background: var(--bg-surface);
  color: var(--text-1);
  border-color: var(--seam-1);
}
.conv-item.active {
  background: linear-gradient(90deg, var(--accent-dim), transparent);
  color: var(--accent);
  border-color: var(--accent-bright);
}
.conv-item.active::before {
  content: ''; position: absolute; left: 0; top: 6px; bottom: 6px;
  width: 2.5px; background: var(--accent);
  border-radius: 0 3px 3px 0;
  box-shadow: 0 0 8px var(--accent-glow);
}

.conv-main {
  display: flex; align-items: center; gap: 8px;
  flex: 1; min-width: 0;
  padding: 8px 10px;
  background: none; border: none;
  color: inherit; font: inherit;
  cursor: pointer; text-align: left;
  border-radius: var(--radius-sm);
}
.conv-icon { flex-shrink: 0; opacity: 0.35; font-size: 14px; }
.conv-item.active .conv-icon { opacity: 0.7; }
.conv-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.conv-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-tags { display: flex; align-items: center; gap: 4px; flex-wrap: nowrap; overflow: hidden; }
.tag-pill {
  font-size: 10px; font-weight: 500;
  color: var(--text-4); background: var(--bg-panel);
  padding: 1px 5px; border-radius: 4px; white-space: nowrap;
  border: 1px solid var(--seam-1);
}

/* Actions */
.action-btn {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; padding: 0;
  background: none; border: none; border-radius: 5px;
  color: var(--text-4); cursor: pointer;
  transition: all var(--duration-fast);
  opacity: 0;
}
.conv-item:hover .action-btn,
.conv-item.active .action-btn { opacity: 1; }
.action-btn:hover { color: var(--text-1); background: var(--bg-active); }
.action-btn.confirm:hover { color: var(--success); background: rgba(34,197,94,0.1); }
.action-btn.cancel:hover { color: var(--error); background: rgba(239,68,68,0.1); }

.rename-input {
  flex: 1; min-width: 0; padding: 6px 10px;
  font-size: 13px; font-family: var(--font-sans);
  border: 1px solid var(--accent); border-radius: var(--radius-sm);
  outline: none; background: var(--bg-panel);
  color: var(--text-0);
  box-shadow: 0 0 0 3px var(--accent-dim);
}

.no-conv {
  text-align: center; color: var(--text-4);
  font-size: 12px; padding: 28px 0;
}

/* Bottom Nav */
.bottom-nav {
  border-top: 1px solid var(--seam-1);
  margin-top: 8px; padding-top: 8px;
}
.bottom-nav.collapsed { display: flex; justify-content: center; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 9px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-3);
  font-size: 13px; font-weight: 500; font-family: var(--font-sans);
  cursor: pointer;
  transition: all var(--duration-fast);
}
.nav-item:hover { background: var(--bg-surface); color: var(--text-1); border-color: var(--seam-1); }
.nav-item.active { background: var(--accent-dim); color: var(--accent); }
.nav-item.collapsed { justify-content: center; padding: 0; width: 40px; height: 40px; }
</style>
