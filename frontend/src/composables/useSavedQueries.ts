import { ref } from 'vue'

export interface SavedQuery {
  id: string
  name: string
  sql: string
  createdAt: number
}

const STORAGE_KEY = 'gbase:saved_queries'

function load(): SavedQuery[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw)
  } catch {
    return []
  }
}

function save(list: SavedQuery[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
}

const queries = ref<SavedQuery[]>(load())

export function useSavedQueries() {
  function add(name: string, sql: string): SavedQuery {
    const item: SavedQuery = {
      id: crypto.randomUUID(),
      name: name.trim() || '未命名查询',
      sql,
      createdAt: Date.now(),
    }
    queries.value.unshift(item)
    save(queries.value)
    return item
  }

  function remove(id: string) {
    queries.value = queries.value.filter(q => q.id !== id)
    save(queries.value)
  }

  function rename(id: string, name: string) {
    const q = queries.value.find(x => x.id === id)
    if (q) {
      q.name = name.trim() || q.name
      save(queries.value)
    }
  }

  return {
    queries,
    add,
    remove,
    rename,
  }
}

/**
 * 从 SQL 中提取 {{variable}} 形式的参数
 */
export function extractParams(sql: string): string[] {
  const regex = /\{\{(\s*\w+\s*)\}\}/g
  const params: string[] = []
  const seen = new Set<string>()
  let m: RegExpExecArray | null
  while ((m = regex.exec(sql)) !== null) {
    const name = m[1]?.trim()
    if (name && !seen.has(name)) {
      seen.add(name)
      params.push(name)
    }
  }
  return params
}

/**
 * 将参数替换为实际值
 */
export function applyParams(sql: string, values: Record<string, string>): string {
  return sql.replace(/\{\{(\s*\w+\s*)\}\}/g, (_, name) => {
    const key = name.trim()
    const val = values[key]
    if (val === undefined) return `{{${key}}}`
    // Quote if not numeric
    const isNum = !isNaN(Number(val)) && val.trim() !== ''
    return isNum ? val : `'${val.replace(/'/g, "\\'")}'`
  })
}
