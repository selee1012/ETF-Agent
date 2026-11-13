// 답변용 최소 마크다운 렌더러: 제목, 굵게·기울임, 인라인 코드, 링크, 목록(순서 없음·번호), 표, 인용,
// 구분선, 코드 블록.
// innerHTML을 쓰지 않고 React 요소로만 만든다(XSS 방지).
import type { ReactNode } from 'react'

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|_[^_]+_|\[[^\]]+\]\((?:https?:\/\/)[^)\s]+\))/g
const LIST_ITEM = /^(\s*)([-*]|\d{1,3}[.)])\s+(.*)$/
const BLOCK_START = /^(#{1,6}\s|\||>|---|```|\s*([-*]|\d{1,3}[.)])\s)/

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyBase}-${i}`
    if (/^`[^`]+`$/.test(part)) return <code key={key}>{part.slice(1, -1)}</code>
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={key}>{part.slice(2, -2)}</strong>
    if (/^_[^_]+_$/.test(part)) return <em key={key}>{part.slice(1, -1)}</em>
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
    if (link)
      return (
        <a key={key} href={link[2]} target="_blank" rel="noreferrer noopener">
          {link[1]}
        </a>
      )
    return part
  })
}

type ListItem = { text: string; nested: { ordered: boolean; items: string[] } | null }

function List({ ordered, items, k }: { ordered: boolean; items: ListItem[]; k: string }) {
  const Tag = ordered ? 'ol' : 'ul'
  return (
    <Tag>
      {items.map((it, j) => (
        <li key={j}>
          {inline(it.text, `${k}l${j}`)}
          {it.nested && (
            <List
              ordered={it.nested.ordered}
              items={it.nested.items.map((t) => ({ text: t, nested: null }))}
              k={`${k}l${j}n`}
            />
          )}
        </li>
      ))}
    </Tag>
  )
}

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((c) => c.trim())
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${i}`
    if (!line.trim()) {
      i++
      continue
    }
    if (/^```/.test(line)) {
      const code: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++])
      i++ // 닫는 ``` (스트리밍 중이면 아직 없을 수 있다)
      out.push(
        <pre key={key}>
          <code>{code.join('\n')}</code>
        </pre>,
      )
      continue
    }
    if (/^\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\|\s*-/.test(lines[i + 1])) {
      const head = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(cells(lines[i++]))
      out.push(
        <div className="table-wrap" key={key}>
          <table>
            <thead>
              <tr>
                {head.map((h, j) => (
                  <th key={j}>{inline(h, `${key}h${j}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, ci) => (
                    <td key={ci}>{inline(c, `${key}r${ri}c${ci}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      out.push(
        <p className={`md-h md-h${heading[1].length}`} key={key}>
          {inline(heading[2], key)}
        </p>,
      )
      i++
      continue
    }
    if (/^---+\s*$/.test(line)) {
      out.push(<hr key={key} />)
      i++
      continue
    }
    if (/^>\s?/.test(line)) {
      const quote: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ''))
      out.push(<blockquote key={key}>{inline(quote.join(' '), key)}</blockquote>)
      continue
    }
    const first = LIST_ITEM.exec(line)
    if (first) {
      const ordered = /\d/.test(first[2])
      const items: ListItem[] = []
      while (i < lines.length) {
        const cur = lines[i]
        const m = LIST_ITEM.exec(cur)
        if (!m) {
          // 항목 사이 빈 줄: 뒤에 같은 목록의 항목이 이어지면 건너뛴다. 여기서 끊으면 항목마다
          // 새 목록이 돼 번호가 전부 1로 보인다.
          if (!cur.trim()) {
            let j = i + 1
            while (j < lines.length && !lines[j].trim()) j++
            const next = LIST_ITEM.exec(lines[j] ?? '')
            if (next && (next[1].length > 0 || /\d/.test(next[2]) === ordered)) {
              i = j
              continue
            }
            break
          }
          // 들여쓴 이어지는 문장은 직전 항목에 붙인다
          if (/^\s{2,}\S/.test(cur) && items.length) {
            const parent = items[items.length - 1]
            if (parent.nested?.items.length) {
              parent.nested.items[parent.nested.items.length - 1] += ` ${cur.trim()}`
            } else {
              parent.text += ` ${cur.trim()}`
            }
            i++
            continue
          }
          break
        }
        const isOrdered = /\d/.test(m[2])
        if (m[1].length > 0 && items.length) {
          const parent = items[items.length - 1]
          parent.nested ??= { ordered: isOrdered, items: [] }
          parent.nested.items.push(m[3])
        } else if (isOrdered === ordered) {
          items.push({ text: m[3], nested: null })
        } else {
          break // 종류가 다른 목록은 새 목록으로
        }
        i++
      }
      out.push(<List key={key} ordered={ordered} items={items} k={key} />)
      continue
    }
    const para: string[] = [lines[i++]] // 최소 한 줄은 소비한다(무한 루프 방지)
    while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i])) para.push(lines[i++])
    out.push(<p key={key}>{inline(para.join(' '), key)}</p>)
  }
  return <div className="md">{out}</div>
}
