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
 * 解析包含代码块的文本，返回按顺序排列的段落列表。
 * 支持 ```sql / ```SQL / ``` 等多种代码块标记，支持流式输入。
 */
export function parseContent(raw: string): ContentSegment[] {
  const segments: ContentSegment[] = []
  // 匹配完整的 ```sql ... ``` 或 ``` ... ``` 块（不区分大小写）
  const completeRe = /```(?:sql)?\n?([\s\S]*?)```/gi
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = completeRe.exec(raw)) !== null) {
    const before = raw.slice(lastIndex, match.index).trim()
    if (before) segments.push({ type: 'text', content: before, complete: true })
    const sql = (match[1] ?? '').replace(/\n$/, '').trim()
    if (sql) segments.push({ type: 'sql', content: sql, complete: true })
    lastIndex = completeRe.lastIndex
  }

  const tail = raw.slice(lastIndex)
  if (!tail) return segments

  // 检查是否有一个未闭合的代码块（流式进行中）
  const openIdx = tail.search(/```(?:sql)?\n?/i)
  if (openIdx >= 0) {
    const before = tail.slice(0, openIdx).trim()
    if (before) segments.push({ type: 'text', content: before, complete: true })
    const m = tail.slice(openIdx).match(/```(?:sql)?\n?/i)
    const prefixLen = m ? m[0].length : 6
    const partialSql = tail.slice(openIdx + prefixLen).replace(/^\n/, '')
    if (partialSql) segments.push({ type: 'sql', content: partialSql, complete: false })
  } else {
    const trimmedTail = tail.trim()
    if (trimmedTail) segments.push({ type: 'text', content: trimmedTail, complete: true })
  }

  return segments
}
