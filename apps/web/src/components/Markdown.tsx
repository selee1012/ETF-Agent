// 답변용 최소 마크다운 렌더러: 제목, 굵게·기울임, 링크, 목록, 표, 인용, 구분선.
// innerHTML을 쓰지 않고 React 요소로만 만든다(XSS 방지).
import type { ReactNode } from 'react'

const INLINE = /(\*\*[^*]+\*\*|_[^_]+_|\[[^\]]+\]\((?:https?:\/\/)[^)\s]+\))/g

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyBase}-${i}`
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
    if (/^\s*[-*]\s+/.test(line)) {
      const items: { text: string; nested: string[] }[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        const indent = /^\s+/.test(lines[i])
        const t = lines[i].replace(/^\s*[-*]\s+/, '')
        if (indent && items.length) items[items.length - 1].nested.push(t)
        else items.push({ text: t, nested: [] })
        i++
      }
      out.push(
        <ul key={key}>
          {items.map((it, j) => (
            <li key={j}>
              {inline(it.text, `${key}l${j}`)}
              {it.nested.length > 0 && (
                <ul>
                  {it.nested.map((n, k) => (
                    <li key={k}>{inline(n, `${key}l${j}n${k}`)}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>,
      )
      continue
    }
    const para: string[] = [lines[i++]] // 최소 한 줄은 소비한다(무한 루프 방지)
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\||>|---|\s*[-*]\s)/.test(lines[i]))
      para.push(lines[i++])
    out.push(<p key={key}>{inline(para.join(' '), key)}</p>)
  }
  return <div className="md">{out}</div>
}
