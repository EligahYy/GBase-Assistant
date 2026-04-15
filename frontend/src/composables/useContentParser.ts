/**
 * 流式内容解析器：实时将含 ```sql...``` 的文本拆分为文字和 SQL 代码块段落。
 * 在流式输出过程中，遇到未闭合的代码块也能正确展示正在生成的 SQL。
 */

export interface ContentSegment {
  type: 'text' | 'sql'
  content: string
  /** false 表示代码块尚未闭合（流式中） */
  complete: boolean
}

/**
 * 解析包含 ```sql...``` 代码块的文本，返回按顺序排列的段落列表。
 * 支持流式输入（内容可能在 SQL 块中间截断）。
 */
export function parseContent(raw: string): ContentSegment[] {
  const segments: ContentSegment[] = []
  // 匹配完整的 ```sql ... ``` 块
  const completeRe = /```sql\n?([\s\S]*?)```/gi
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = completeRe.exec(raw)) !== null) {
    const before = raw.slice(lastIndex, match.index)
    if (before.trim()) segments.push({ type: 'text', content: before, complete: true })
    const sql = (match[1] ?? '').replace(/\n$/, '').trim()
    if (sql) segments.push({ type: 'sql', content: sql, complete: true })
    lastIndex = completeRe.lastIndex
  }

  const tail = raw.slice(lastIndex)
  if (!tail) return segments

  // 检查是否有一个未闭合的 ```sql 块（流式进行中）
  const openIdx = tail.indexOf('```sql')
  if (openIdx >= 0) {
    const before = tail.slice(0, openIdx)
    if (before.trim()) segments.push({ type: 'text', content: before, complete: true })
    // 去掉 ```sql\n 前缀，剩余就是正在流式输出的 SQL
    const partialSql = tail.slice(openIdx + 6).replace(/^\n/, '')
    if (partialSql) segments.push({ type: 'sql', content: partialSql, complete: false })
  } else {
    if (tail.trim()) segments.push({ type: 'text', content: tail, complete: true })
  }

  return segments
}
