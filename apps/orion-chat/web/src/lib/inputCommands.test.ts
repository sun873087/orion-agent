import { describe, expect, it } from 'vitest'
import {
  applyMention,
  buildSendPrefix,
  buildSlashCommands,
  detectMention,
  filterMentions,
  filterSlash,
  isClientCommand,
  slashQuery,
} from './inputCommands'

describe('slash commands', () => {
  it('buildSlashCommands gates client commands behind a session', () => {
    const skills = [{ name: 'research', description: 'deep dive' }]
    const withSession = buildSlashCommands(skills, true)
    const draft = buildSlashCommands(skills, false)
    expect(withSession.some((c) => c.name === '/compact')).toBe(true)
    expect(withSession.some((c) => c.name === '/research')).toBe(true)
    // draft 沒 session — 只剩 skills
    expect(draft.every((c) => c.kind === 'skill')).toBe(true)
    expect(draft).toHaveLength(1)
  })

  it('slashQuery only matches a leading single-line / token', () => {
    expect(slashQuery('/com')).toBe('com')
    expect(slashQuery('/')).toBe('')
    expect(slashQuery('/compact now')).toBeNull() // 打了空白 → 收起
    expect(slashQuery('hi /compact')).toBeNull()
    expect(slashQuery('/a\nb')).toBeNull()
  })

  it('filterSlash matches by name substring', () => {
    const cmds = buildSlashCommands([{ name: 'research' }], true)
    expect(filterSlash(cmds, 'con').map((c) => c.name)).toEqual(['/context'])
    expect(filterSlash(cmds, 'rese').map((c) => c.name)).toEqual(['/research'])
  })

  it('isClientCommand recognises built-ins', () => {
    expect(isClientCommand('/compact')).toBe(true)
    expect(isClientCommand('/research')).toBe(false)
  })
})

describe('@ mentions', () => {
  it('detects bare / skill: / file: prefixes', () => {
    expect(detectMention('hi @foo', 7)?.mode).toBe('any')
    expect(detectMention('@skill:re', 9)).toMatchObject({
      mode: 'skill',
      query: 're',
    })
    expect(detectMention('see @file:a.py', 14)).toMatchObject({
      mode: 'file',
      query: 'a.py',
    })
  })

  it('returns null when there is whitespace after @ or @ is mid-word', () => {
    expect(detectMention('@foo bar', 8)).toBeNull() // 游標在空白後
    expect(detectMention('a@foo', 5)).toBeNull() // @ 前非空白(email 樣)
  })

  it('filterMentions merges skills+files for bare @, narrows by prefix', () => {
    const skills = [{ name: 'research' }, { name: 'reviewer' }]
    const files = ['report.md', 'main.py']
    const any = detectMention('@re', 3)!
    // 混合:skills 先、files 後;report.md 也含 "re"
    expect(filterMentions(any, skills, files).map((i) => i.value)).toEqual([
      'research',
      'reviewer',
      'report.md',
    ])
    const onlyFile = detectMention('@file:re', 8)!
    expect(filterMentions(onlyFile, skills, files).map((i) => i.value)).toEqual(
      ['report.md'],
    )
  })

  it('applyMention replaces the @token with a canonical token + space', () => {
    const ctx = detectMention('look @re here', 8)! // query 're' at idx 5..8
    const r = applyMention('look @re here', ctx, {
      kind: 'skill',
      value: 'research',
      label: 'research',
    })
    expect(r.text).toBe('look @skill:research  here')
    expect(r.cursor).toBe('look @skill:research '.length)
  })
})

describe('buildSendPrefix', () => {
  it('summarises referenced skills and files for the LLM', () => {
    const prefix = buildSendPrefix(
      'use @skill:research and @file:main.py @skill:research',
    )
    expect(prefix).toContain('research')
    expect(prefix).toContain('main.py')
    // 去重:research 只列一次
    expect(prefix.match(/research/g)).toHaveLength(1)
  })

  it('is empty without references', () => {
    expect(buildSendPrefix('just a normal message')).toBe('')
  })
})
