# GBase Copilot Frontend Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the entire Vue 3 frontend to OpenAI minimalist style — monochrome palette, Inter font, Iconify icons, enhanced animations, and improved UX across all 5 pages.

**Architecture:** Incremental redesign working outward from the design token layer. Update CSS variables first (base.css), then global animations (main.css), then the shell (App.vue + Sidebar.vue), then each page view bottom-up. The existing component structure and Naive UI integration is preserved — this is a visual and UX refresh, not a rewrite.

**Tech Stack:** Vue 3 + Naive UI + Pinia + TypeScript, @vicons/ionicons5, CSS custom properties

**Source spec:** `docs/superpowers/specs/2026-06-10-frontend-redesign-design.md`

---

### Task 1: Update CSS Design Tokens

**Files:**
- Modify: `frontend/src/assets/base.css`

- [ ] **Step 1: Update font stack to Inter-first**

Replace the `--font-sans` and `--font-mono` variables:
```css
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
--font-mono: 'JetBrains Mono', 'SF Mono', SFMono-Regular, 'Fira Code', monospace;
```

- [ ] **Step 2: Tune geometry tokens for cleaner proportion**

```css
--radius-sm: 8px;
--radius-md: 10px;
--radius-lg: 14px;
--radius-xl: 18px;
--sidebar-width: 260px;
--header-height: 48px;
--max-content-width: 680px;
```

- [ ] **Step 3: Refine shadow tokens for subtle "floating" effect**

```css
--shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
--shadow-md: 0 4px 20px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.03);
--shadow-lg: 0 20px 60px rgba(0,0,0,0.15);
```

- [ ] **Step 4: Add new accent tokens for status cards**

```css
--accent-soft: rgba(0, 0, 0, 0.03);
--bg-hover: rgba(0,0,0,0.03);
--bg-active: rgba(0,0,0,0.05);
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/assets/base.css
git commit -m "style: update CSS tokens — Inter font, refined radius/shadow"
```

---

### Task 2: Add Global Animations

**Files:**
- Modify: `frontend/src/assets/main.css`

- [ ] **Step 1: Add new keyframe animations for typewriter, signal dots, and progress flow**

Add after the existing `@keyframes headerReveal` block:
```css
/* Typewriter cursor */
@keyframes cursorBlink {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0; }
}

/* Three-dot thinking indicator */
@keyframes signalDot {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* SQL execution progress bar */
@keyframes progressFlow {
  from { transform: translateX(-100%); }
  to   { transform: translateX(350%); }
}
```

- [ ] **Step 2: Add modal animation utility**

Add after existing animations:
```css
@keyframes modalIn {
  from { opacity: 0; transform: scale(0.95); }
  to   { opacity: 1; transform: scale(1); }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/assets/main.css
git commit -m "style: add typewriter, signal-dot, progress-flow, modal animations"
```

---

### Task 3: Update App Shell Branding

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Remove starfield background pseudo-element**

Delete the entire `.app-shell::before` block and its `html[data-theme="light"] .app-shell::before` variant (lines 89-128 in the style section). This removes the teal starfield dots that conflict with the OpenAI monochrome aesthetic.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.vue
git commit -m "style: remove starfield background from app shell"
```

---

### Task 4: Redesign Sidebar

**Files:**
- Modify: `frontend/src/components/layout/Sidebar.vue`

- [ ] **Step 1: Update brand area in expanded sidebar**

Replace the brand rendering (around line 316-319) to use Inter 700 and show "GBase Copilot":
```html
<div class="brand">
  <div class="brand-icon">G</div>
  <div class="brand-text">GBase Copilot</div>
</div>
```

Update the brand styles (around lines 646-673):
```css
.brand-text {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-0);
  letter-spacing: -0.03em;
}
```

- [ ] **Step 2: Remove "AI 问答" from bottom nav**

In the `navItems` array (around line 258-263), keep only 4 items:
```ts
const navItems = [
  { path: '/sql-editor', icon: CodeSlashOutline, label: 'SQL 编辑器' },
  { path: '/tools/error-code', icon: AlertCircleOutline, label: '错误码查询' },
  { path: '/knowledge', icon: LibraryOutline, label: '知识库' },
  { path: '/settings', icon: SettingsOutline, label: '设置' },
]
```

Import the new icon `CodeSlashOutline`:
```ts
import {
  AddOutline,
  ChatbubbleEllipsesOutline,
  EllipsisHorizontalOutline,
  CheckmarkOutline,
  CloseCircleOutline,
  SettingsOutline,
  AlertCircleOutline,
  CodeSlashOutline,
  LibraryOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
} from '@vicons/ionicons5'
```

- [ ] **Step 3: Ensure all sidebar items use Iconify icons (no emoji)**

The current sidebar already uses `<n-icon :component="ChatbubbleEllipsesOutline" />` for conversation items — verify no emoji icons exist. No changes needed here if clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout/Sidebar.vue
git commit -m "feat: redesign sidebar — GBase Copilot branding, remove AI nav, CodeSlash icon"
```

---

### Task 5: Redesign ChatPanel Empty State

**Files:**
- Modify: `frontend/src/components/chat/ChatPanel.vue`

- [ ] **Step 1: Import additional icons for category cards**

Add to the import block:
```ts
import {
  SendOutline, ServerOutline, SunnyOutline, MoonOutline,
  StopCircleOutline, BookOutline, SparklesOutline,
  GridOutline, SettingsOutline, AlertCircleOutline,
} from '@vicons/ionicons5'
```

- [ ] **Step 2: Replace the empty state template**

Replace the current empty state `<div v-if="chatStore.messages.length === 0" class="empty-state">` block with the 2×2 category card layout:

```html
<div v-if="chatStore.messages.length === 0" class="empty-state">
  <div class="empty-brand">
    <div class="monogram-wrap">
      <div class="monogram">G</div>
    </div>
    <h2 class="empty-title">今天我能帮你做什么？</h2>
    <p class="empty-sub">GBase 8a MPP 数据库专家助手 — 用自然语言查询数据、优化 SQL、诊断问题</p>
  </div>
  <div class="hint-grid">
    <button class="hint-card" @click="inputText = '查询每个部门薪资最高的 3 名员工'">
      <n-icon :component="GridOutline" size="20" />
      <div class="hint-card-title">数据查询</div>
      <div class="hint-card-desc">用自然语言生成并执行 GBase SQL</div>
    </button>
    <button class="hint-card" @click="inputText = '帮我优化这条 SQL 的查询性能'">
      <n-icon :component="SettingsOutline" size="20" />
      <div class="hint-card-title">SQL 优化</div>
      <div class="hint-card-desc">执行计划分析与分布键优化建议</div>
    </button>
    <button class="hint-card" @click="inputText = 'GBase 8a 支持窗口函数吗？'">
      <n-icon :component="BookOutline" size="20" />
      <div class="hint-card-title">知识问答</div>
      <div class="hint-card-desc">基于官方手册回答 GBase 8a 问题</div>
    </button>
    <button class="hint-card" @click="inputText = '错误码 1146 怎么解决？'">
      <n-icon :component="AlertCircleOutline" size="20" />
      <div class="hint-card-title">错误诊断</div>
      <div class="hint-card-desc">错误码查询与解决方案</div>
    </button>
  </div>
</div>
```

- [ ] **Step 3: Update empty state styles**

Replace the empty state and hint card CSS to support the new 2×2 card layout:

```css
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - var(--header-height) - 200px);
  padding: 40px 20px;
  text-align: center;
  animation: fadeIn 0.5s var(--ease-out-expo) both;
}
.empty-brand {
  margin-bottom: 36px;
}
.monogram-wrap {
  margin: 0 auto 24px;
  animation: fadeInUp 0.4s 0.1s var(--ease-out-expo) both;
}
.monogram {
  width: 72px; height: 72px;
  background: #111; color: #fff;
  border-radius: 18px;
  font-size: 34px; font-weight: 800;
  font-family: 'Inter', var(--font-sans);
  display: flex; align-items: center; justify-content: center;
  letter-spacing: -2px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.empty-title {
  font-size: 28px; font-weight: 700;
  color: var(--text-0); letter-spacing: -0.03em;
  margin-bottom: 10px;
  animation: fadeInUp 0.4s 0.2s var(--ease-out-expo) both;
}
.empty-sub {
  font-size: 14px; color: var(--text-3);
  line-height: 1.6; max-width: 360px;
  animation: fadeInUp 0.4s 0.25s var(--ease-out-expo) both;
}

.hint-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  max-width: 520px; width: 100%;
  animation: fadeInUp 0.4s 0.3s var(--ease-out-expo) both;
}
@media (max-width: 640px) {
  .hint-grid { grid-template-columns: 1fr; }
}
.hint-card {
  padding: 18px 20px;
  background: #fff;
  border: 1px solid #eee;
  border-radius: 14px;
  text-align: left;
  cursor: pointer;
  font-family: var(--font-sans);
  transition: all 0.15s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,0.03);
  display: flex; flex-direction: column; gap: 6px;
}
.hint-card:hover {
  border-color: #ccc;
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.hint-card .n-icon { color: var(--text-2); }
.hint-card-title {
  font-size: 14px; font-weight: 600; color: #111;
}
.hint-card-desc {
  font-size: 11px; color: #999; line-height: 1.4;
}
```

- [ ] **Step 4: Update header brand to "GBase Copilot"**

In the header model-label area, update the empty brand text and any references from "GBase 助手" to "GBase Copilot".

- [ ] **Step 5: Remove old hints array**

Remove the `hints` reactive array (lines 178-183) since we now use inline button actions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/ChatPanel.vue
git commit -m "feat: ChatGPT-style empty state with 2×2 category cards"
```

---

### Task 6: Enhance MessageBubble with Typewriter and Hover Actions

**Files:**
- Modify: `frontend/src/components/chat/MessageBubble.vue`

- [ ] **Step 1: Add typewriter cursor for streaming text**

In the assistant text segment rendering (around line 174), add a cursor element when streaming and the last segment is text:

```html
<span v-if="message.isStreaming && segments.length > 0 && segments[segments.length - 1].type === 'text'" class="stream-cursor"></span>
```

The existing `.stream-cursor` CSS (lines 392-401) already handles the blinking cursor. Ensure it's positioned after the last text segment.

- [ ] **Step 2: Add hover action buttons (copy / thumbs-up / thumbs-down)**

Add action buttons that appear on hover over the assistant message bubble. Insert after the text content div, within the `.msg-content`:

```html
<div v-if="!isUser && !isTyping" class="msg-actions">
  <button class="action-btn" title="复制" @click="copyContent">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
  </button>
  <button class="action-btn" title="点赞" @click="$emit('feedback', 'accepted')">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/></svg>
  </button>
  <button class="action-btn" title="点踩" @click="$emit('feedback', 'rejected')">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V4H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/></svg>
  </button>
</div>
```

Add the copy function to script:
```ts
import { useMessage } from 'naive-ui'
const naiveMsg = useMessage()

function copyContent() {
  const text = props.message.content
  navigator.clipboard.writeText(text).then(() => {
    naiveMsg.success('已复制')
  }).catch(() => {
    naiveMsg.warning('复制失败')
  })
}
```

Add the actions CSS:
```css
.msg-actions {
  display: flex; align-items: center; gap: 2px;
  margin-top: 6px; opacity: 0;
  transition: opacity 0.15s ease;
}
.msg-row:hover .msg-actions { opacity: 1; }
.msg-actions .action-btn {
  display: flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; padding: 0;
  background: none; border: none; border-radius: 6px;
  color: var(--text-4); cursor: pointer;
  transition: all 0.15s;
}
.msg-actions .action-btn:hover {
  color: var(--text-1); background: var(--bg-hover);
}
```

- [ ] **Step 3: Improve footnote/reference display**

Update the sources block to show numbered references like `[1]` that are more visually distinct. Update the `.sources-summary` to show clickable footnote badges.

In the template, update the sources block (around line 218):
```html
<details v-if="!isUser && !isTyping && sourceList.length" class="sources-block">
  <summary class="sources-summary">
    <span class="sources-label">引用来源</span>
    <span class="sources-count">{{ sourceList.length }}</span>
  </summary>
  <ul class="sources-list">
    <li v-for="(src, i) in sourceList" :key="`${src}-${i}`" class="sources-item">
      <span class="source-index">[{{ i + 1 }}]</span> {{ src }}
    </li>
  </ul>
</details>
```

Add the source index style:
```css
.source-index {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 20px; height: 18px;
  background: var(--bg-deep); color: var(--text-2);
  border-radius: 4px; font-size: 10px; font-weight: 700;
  font-family: var(--font-mono); margin-right: 4px;
  border: 1px solid var(--seam-1);
}
```

- [ ] **Step 4: Update assistant avatar to black rounded square "G"**

Replace the SVG avatar icon in the assistant avatar div (around line 144):
```html
<div v-if="!isUser" class="avatar assistant-avatar">G</div>
```

Update the style:
```css
.assistant-avatar {
  background: #111; color: #fff;
  border: none;
  font-size: 13px; font-weight: 700;
  font-family: 'Inter', var(--font-sans);
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/MessageBubble.vue
git commit -m "feat: typewriter cursor, hover actions, footnote badges, black G avatar"
```

---

### Task 7: Redesign SQL Editor with Dark Code Panel

**Files:**
- Modify: `frontend/src/views/SqlEditorView.vue`

- [ ] **Step 1: Add dark-themed SQL textarea**

Replace the current `.sql-textarea` textarea with a dark-themed code editor area. Update the textarea style:

```css
.sql-textarea {
  width: 100%;
  min-height: 200px;
  max-height: 420px;
  padding: 18px 20px;
  border: none;
  background: #1a1a1a;
  color: #e0e0e0;
  font-family: 'JetBrains Mono', var(--font-mono);
  font-size: 13px;
  line-height: 1.8;
  resize: vertical;
  outline: none;
  border-radius: 0 0 12px 12px;
}
.sql-textarea::placeholder {
  color: #666;
}
```

Update the `.input-card` to have the dark code panel feel:
```css
.input-card {
  background: #1a1a1a;
  border: 1px solid #e0e0e0;
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.input-card:focus-within {
  border-color: #aaa;
}
.input-header {
  background: #fafafa;
  border-bottom: 1px solid #eee;
  /* keep existing styles */
}
```

- [ ] **Step 2: Add progress bar during execution**

Add a progress bar element that shows during query execution:

In template, add between the input card and result card:
```html
<div v-if="isExecuting" class="exec-progress">
  <div class="exec-progress-bar"></div>
</div>
```

In style:
```css
.exec-progress {
  height: 3px;
  background: #eee;
  border-radius: 2px;
  overflow: hidden;
}
.exec-progress-bar {
  height: 100%;
  width: 30%;
  background: linear-gradient(90deg, transparent, #16a34a, transparent);
  border-radius: 2px;
  animation: progressFlow 1.5s infinite linear;
}
```

- [ ] **Step 3: Style the execute button green**

Update `.header-btn.primary`:
```css
.header-btn.primary {
  background: #16a34a;
  border-color: #16a34a;
  color: #fff;
}
.header-btn.primary:hover:not(:disabled) {
  background: #15803d;
  border-color: #15803d;
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/SqlEditorView.vue
git commit -m "feat: dark SQL code panel, green execute button, progress bar"
```

---

### Task 8: Redesign Error Code Page Cards

**Files:**
- Modify: `frontend/src/views/ErrorCodeView.vue`

- [ ] **Step 1: Add expand/collapse to result cards**

Add a `expandedIndex` ref and toggle logic:
```ts
const expandedIndex = ref<number | null>(null)
function toggleExpand(index: number) {
  expandedIndex.value = expandedIndex.value === index ? null : index
}
```

- [ ] **Step 2: Update result card template for collapsible sections**

Replace the `.card-body` section in the result card with collapsible content:

```html
<section class="card-body" v-show="expandedIndex === index">
  <div class="body-block">
    <h3 class="block-title">描述</h3>
    <p class="block-text">{{ item.description }}</p>
  </div>
  <div v-if="item.solution" class="body-block">
    <h3 class="block-title">解决方案</h3>
    <pre class="block-pre">{{ item.solution }}</pre>
  </div>
  <div v-if="item.keywords?.length" class="kw-list">
    <span v-for="kw in item.keywords" :key="kw" class="kw-tag">#{{ kw }}</span>
  </div>
</section>
```

Add a click handler on the card header:
```html
<header class="card-head" @click="toggleExpand(index)" style="cursor:pointer;">
```

Add expand indicator icon:
```html
<n-icon
  :component="expandedIndex === index ? ChevronUpOutline : ChevronDownOutline"
  size="16"
  style="color:var(--text-3);flex-shrink:0;margin-top:1px;"
/>
```

Import `ChevronUpOutline, ChevronDownOutline` from `@vicons/ionicons5`.

- [ ] **Step 3: Add orange error code badge styling**

Update `.code-label` style:
```css
.code-label {
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--text-0);
  letter-spacing: 0.02em;
  background: #fef7ed;
  color: #d97706;
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid #fde68a;
}
```

- [ ] **Step 4: Add animation for expand/collapse**

Add a transition to the `.card-body`:
```css
.card-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  animation: fadeIn 0.2s ease both;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/ErrorCodeView.vue
git commit -m "feat: collapsible error cards, orange code badges, expand animation"
```

---

### Task 9: Redesign Knowledge Base with Drag Upload and Password-Protected Reindex

**Files:**
- Modify: `frontend/src/views/KnowledgeView.vue`

- [ ] **Step 1: Add drag-upload visual feedback zone**

Replace the current upload toolbar with a prominent drag-drop zone:

```html
<div class="upload-zone" @dragover.prevent @drop.prevent>
  <div class="upload-icon-wrap">
    <n-icon :component="CloudUploadOutline" size="24" />
  </div>
  <div class="upload-title">点击或拖拽文件到此处上传</div>
  <div class="upload-hint">支持 PDF, Markdown, TXT, DOCX（最大 50MB）</div>
  <n-upload
    multiple directory-dnd
    accept=".pdf,.md,.txt,.docx"
    :custom-request="handleUpload"
    :show-file-list="false"
  >
    <n-button size="small" style="margin-top:12px;">选择文件</n-button>
  </n-upload>
</div>
```

Add CSS:
```css
.upload-zone {
  border: 2px dashed #e0e0e0;
  border-radius: 14px;
  padding: 36px;
  text-align: center;
  background: #fff;
  transition: all 0.2s;
  cursor: pointer;
}
.upload-zone:hover {
  border-color: #111;
  background: #fafafa;
}
.upload-icon-wrap {
  width: 48px; height: 48px;
  background: #f9f9f9; border: 1px solid #eee;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 14px; color: #999;
}
.upload-title {
  font-size: 15px; font-weight: 600; color: #111; margin-bottom: 4px;
}
.upload-hint {
  font-size: 11px; color: #bbb;
}
```

- [ ] **Step 2: Add password-protected reindex card with modal**

Replace the "全量重建索引" button with a card:

```html
<div class="reindex-card">
  <div class="reindex-card-left">
    <div class="reindex-icon-wrap">
      <n-icon :component="RefreshOutline" size="18" />
    </div>
    <div>
      <div class="reindex-card-title">重建向量索引</div>
      <div class="reindex-card-desc">重新解析知识库文档并更新 Qdrant 向量索引</div>
      <div class="reindex-card-meta">
        当前索引: 知识库 {{ indexState.total_documents }} 条
        <template v-if="indexState.total_chunks"> · {{ indexState.total_chunks }} 分块</template>
      </div>
    </div>
  </div>
  <n-button @click="showReindexAllModal = true">立即重建</n-button>
</div>
```

CSS:
```css
.reindex-card {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border: 1px solid #eee;
  border-radius: 14px; padding: 16px 18px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}
.reindex-card-left { display: flex; align-items: flex-start; gap: 12px; }
.reindex-icon-wrap {
  width: 36px; height: 36px;
  background: #eff6ff; border: 1px solid #bfdbfe;
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  color: #3b82f6; flex-shrink: 0;
}
.reindex-card-title { font-size: 13px; font-weight: 600; color: #111; margin-bottom: 2px; }
.reindex-card-desc { font-size: 10px; color: #aaa; }
.reindex-card-meta { font-size: 9px; color: #16a34a; margin-top: 2px; font-family: monospace; }
```

- [ ] **Step 3: Add password input to the reindex modal**

Replace the existing simple n-modal for `showReindexAllModal` with a custom modal that includes password:

```html
<n-modal v-model:show="showReindexAllModal" preset="dialog" title="重建向量索引" :show-icon="false"
  positive-text="确认重建" negative-text="取消"
  @positive-click="handleReindexAllWithPassword"
>
  <p style="margin-bottom:12px;font-size:13px;color:#888;">此操作将重新解析所有文档并重建向量索引，可能需要几分钟。</p>
  <n-input
    v-model:value="reindexPassword"
    type="password"
    placeholder="输入管理密码"
    show-password-on="click"
  />
</n-modal>
```

Add the password ref and update the handler:
```ts
const reindexPassword = ref('')

async function handleReindexAllWithPassword() {
  if (!reindexPassword.value.trim()) {
    msg.warning('请输入管理密码')
    return
  }
  try {
    await reindexAll(reindexPassword.value)
    showReindexAllModal.value = false
    reindexPassword.value = ''
    msg.success('全量重建已触发')
    load()
  } catch (e: any) {
    msg.error(e.message || '重建失败，请检查密码是否正确')
  }
}
```

- [ ] **Step 4: Update the reindexAll API call to pass admin token**

Update the API module (`frontend/src/api/knowledge.ts`) to accept an optional password:

Find the `reindexAll` function. If it calls the admin API, pass the token as a header:
```ts
export async function reindexAll(token?: string): Promise<void> {
  await api.post('/admin/reindex', {}, {
    headers: token ? { 'X-Admin-Token': token } : {},
  })
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/KnowledgeView.vue frontend/src/api/knowledge.ts
git commit -m "feat: drag-upload zone, password-protected reindex with modal"
```

---

### Task 10: Redesign Settings Page

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Remove left tab navigation, flatten to vertical scroll**

Remove the `settings-nav` aside and `activeTab` logic. Replace the tab-based layout with a flat vertical scroll layout where all sections are visible:

```html
<main class="settings-main">
  <!-- General -->
  <section class="settings-section">
    <div class="section-label">通用设置</div>
    <!-- Theme, Language, Model cards... -->
  </section>

  <!-- System Status -->
  <section class="settings-section">
    <div class="section-label">系统状态</div>
    <div class="status-grid">...</div>
  </section>

  <!-- Connections -->
  <section class="settings-section">
    <div class="section-label">数据库连接</div>
    <!-- Connection cards... -->
  </section>

  <!-- Feedback -->
  <section class="settings-section">
    <div class="section-label">SQL 反馈统计</div>
    <!-- Feedback stats grid... -->
  </section>
</main>
```

Remove: `type TabKey`, `activeTab` ref, `tabs` array, the `<aside class="settings-nav">` block, and the `v-if="activeTab === 'xxx'"` conditions on sections.

- [ ] **Step 2: Redesign setting items as individual cards with status indicators**

Replace the monolithic `.setting-card` with individual cards per setting item:

```html
<!-- Theme Card -->
<div class="setting-item-card">
  <div class="setting-item-left">
    <div class="setting-item-icon">
      <n-icon :component="SunnyOutline" size="16" />
    </div>
    <div>
      <div class="setting-item-title">外观主题</div>
      <div class="setting-item-status">当前：浅色模式</div>
    </div>
  </div>
  <div class="theme-toggle-group">
    <button :class="['toggle-btn', { active: theme === 'light' }]" @click="theme = 'light'">浅色</button>
    <button :class="['toggle-btn', { active: theme === 'dark' }]" @click="theme = 'dark'">深色</button>
  </div>
</div>

<!-- Language Card -->
<div class="setting-item-card">
  <div class="setting-item-left">
    <div class="setting-item-icon">
      <n-icon :component="GlobeOutline" size="16" />
    </div>
    <div>
      <div class="setting-item-title">界面语言</div>
      <div class="setting-item-status">当前：简体中文</div>
    </div>
  </div>
  <n-select ... />
</div>

<!-- Model Card -->
<div class="setting-item-card">
  <div class="setting-item-left">
    <div class="setting-item-icon" style="background:#f5f3ff;border-color:#ddd6fe;">
      <n-icon :component="SparklesOutline" size="16" color="#7c3aed" />
    </div>
    <div>
      <div class="setting-item-title">默认模型</div>
      <div class="setting-item-status">
        当前：<code>deepseek-chat</code>
        <span class="status-indicator ok">可用</span>
      </div>
    </div>
  </div>
  <n-select ... />
</div>
```

Add the card CSS:
```css
.setting-item-card {
  display: flex; align-items: center; justify-content: space-between;
  background: #fff; border: 1px solid #eee;
  border-radius: 12px; padding: 14px 16px;
  margin-bottom: 6px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}
.setting-item-left { display: flex; align-items: flex-start; gap: 12px; }
.setting-item-icon {
  width: 36px; height: 36px;
  background: #f9f9f9; border: 1px solid #eee;
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  color: #888; flex-shrink: 0;
}
.setting-item-title { font-size: 13px; font-weight: 600; color: #111; margin-bottom: 2px; }
.setting-item-status { font-size: 10px; color: #aaa; }
.setting-item-status code { color: #111; font-family: monospace; font-weight: 500; }
.status-indicator {
  display: inline-flex; align-items: center; gap: 3px;
  margin-left: 6px; font-size: 10px; font-weight: 500;
}
.status-indicator.ok { color: #16a34a; }
.status-indicator::before {
  content: ''; width: 5px; height: 5px;
  background: currentColor; border-radius: 50%;
}

.theme-toggle-group {
  display: flex; background: #f4f4f4;
  border-radius: 7px; padding: 1px;
}
.toggle-btn {
  padding: 4px 12px; font-size: 11px; font-weight: 500;
  border: none; background: transparent; color: #aaa;
  border-radius: 6px; cursor: pointer; transition: all 0.15s;
}
.toggle-btn.active {
  background: #fff; color: #111; font-weight: 600;
  box-shadow: 0 1px 1px rgba(0,0,0,0.04);
}
```

- [ ] **Step 3: Add system status 2×2 grid from health endpoint**

```html
<div class="status-grid-2x2">
  <div v-for="(value, key) in health?.dependencies || {}" :key="key" class="status-cell">
    <span class="status-dot" :style="{ background: statusColor(value, key) }"></span>
    <span class="status-name">{{ {
      database: 'SQLite 数据库',
      llm_api: 'LLM API',
      vector_db: 'Qdrant 向量库',
      gbase_connections: 'GBase 连接',
    }[key] || key }}</span>
    <span class="status-value" :style="{ color: statusColor(value, key) }">{{ statusLabel(value, key) }}</span>
  </div>
</div>
```

Note: Remove `default_model` from the status grid display filter.

CSS:
```css
.status-grid-2x2 {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
}
```

- [ ] **Step 4: Redesign connection cards with status indicators and action buttons**

Each connection card should show: icon (green/red based on status), name, host:port, version, mode, status badge, action buttons (测试/同步/Schema/编辑/删除).

Adjust the existing `.connection-card` template to match the design spec's card layout with icon + info + actions pattern.

- [ ] **Step 5: Remove admin token card**

Delete the admin token section entirely — this is now handled in the Knowledge Base page's reindex modal.

- [ ] **Step 6: Update imports for new icons**

Add to imports: `SunnyOutline, GlobeOutline, SparklesOutline`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat: flat settings layout, status grid, card-style items, remove admin token"
```

---

### Task 11: Backend — ADMIN_TOKEN Default

**Files:**
- Modify: `backend/app/api/admin.py`

(Already completed in the design phase — this is noted for tracking.)

- [ ] **Step 1: Verify the change is in place**

Check that `_verify_admin_token` defaults to `"123456"`:
```python
admin_token = os.getenv("ADMIN_TOKEN", "123456")
```

- [ ] **Step 2: Run admin tests**

```bash
cd backend && python -m pytest tests/ -k admin -v
```

- [ ] **Step 3: Commit if not already committed**

```bash
git add backend/app/api/admin.py
git commit -m "feat: default ADMIN_TOKEN to 123456, always require auth"
```

---

### Task 12: Integration Verification

**Files:** All modified files

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v
```

Expected: All 182 tests pass.

- [ ] **Step 2: Build frontend to check for compilation errors**

```bash
cd frontend && npm run build
```

Fix any TypeScript compilation errors.

- [ ] **Step 3: Manual visual verification checklist**

- [ ] All pages load without console errors
- [ ] Sidebar shows "GBase Copilot" + only 4 nav items (no AI 问答)
- [ ] Chat empty state shows 2×2 category cards with Iconify icons
- [ ] AI messages have black "G" avatar + hover action buttons
- [ ] SQL editor has dark code panel + green run button
- [ ] Error code cards are collapsible with orange badges
- [ ] Knowledge base has drag-upload zone + password reindex modal
- [ ] Settings page is flat scroll with 2×2 status grid + card items
- [ ] Theme toggle works (light/dark)
- [ ] All icons are Iconify linear (no emoji anywhere)

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A && git commit -m "chore: integration fixes after frontend redesign"
```
