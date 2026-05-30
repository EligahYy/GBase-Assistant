import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import SettingsView from '../views/SettingsView.vue'
import ErrorCodeView from '../views/ErrorCodeView.vue'
import SqlEditorView from '../views/SqlEditorView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/sql-editor', name: 'sql-editor', component: SqlEditorView },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/tools/error-code', name: 'error-code', component: ErrorCodeView },
  ],
})

export default router
