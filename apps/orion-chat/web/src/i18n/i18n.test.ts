import { describe, expect, it } from 'vitest'
import { tFor } from './index'

describe('tFor', () => {
  it('returns the locale string', () => {
    expect(tFor('zh-TW', 'sidebar.newChat')).toBe('開新對話')
    expect(tFor('ja', 'common.save')).toBe('保存')
    expect(tFor('zh-CN', 'common.delete')).toBe('删除')
  })

  it('interpolates params', () => {
    expect(tFor('en', 'sidebar.msgCount', { n: 3 })).toBe('3 msg')
    expect(tFor('zh-TW', 'sidebar.msgCount', { n: 5 })).toBe('5 則')
  })

  it('leaves placeholder when a param is missing', () => {
    expect(tFor('en', 'sidebar.msgCount')).toBe('{n} msg')
  })

  it('falls back to the key itself for unknown keys', () => {
    expect(tFor('en', 'totally.unknown.key')).toBe('totally.unknown.key')
  })
})
