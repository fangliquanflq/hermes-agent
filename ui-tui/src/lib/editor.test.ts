import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'

import { beforeEach, describe, expect, it } from 'vitest'

import { readStableEditorFile, resolveEditor } from './editor.js'

const exe = (dir: string, name: string): string => {
  const path = join(dir, name)

  writeFileSync(path, '#!/bin/sh\nexit 0\n')
  chmodSync(path, 0o755)

  return path
}

describe('resolveEditor', () => {
  let dir: string

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'editor-test-'))
  })

  it('honors $VISUAL above all else', () => {
    expect(resolveEditor({ EDITOR: 'vim', PATH: dir, VISUAL: 'helix' })).toEqual(['helix'])
  })

  it('falls back to $EDITOR when $VISUAL is unset', () => {
    expect(resolveEditor({ EDITOR: 'nvim', PATH: dir })).toEqual(['nvim'])
  })

  it('shell-tokenizes editors with arguments', () => {
    expect(resolveEditor({ EDITOR: 'code --wait', PATH: dir })).toEqual(['code', '--wait'])
    expect(resolveEditor({ PATH: dir, VISUAL: 'emacsclient -t' })).toEqual(['emacsclient', '-t'])
  })

  it('ignores whitespace-only env vars', () => {
    const expected = exe(dir, 'editor')

    expect(resolveEditor({ EDITOR: '   ', PATH: dir, VISUAL: '' })).toEqual([expected])
  })

  it('prefers `editor` over nano over vi on $PATH', () => {
    exe(dir, 'nano')
    exe(dir, 'vi')
    const expected = exe(dir, 'editor')

    expect(resolveEditor({ PATH: dir })).toEqual([expected])
  })

  it('falls back to nano before vi when both exist', () => {
    exe(dir, 'vi')
    const expected = exe(dir, 'nano')

    expect(resolveEditor({ PATH: dir })).toEqual([expected])
  })

  it('returns ["vi"] when $PATH is empty', () => {
    expect(resolveEditor({ PATH: '' })).toEqual(['vi'])
  })

  it('walks multi-entry $PATH', () => {
    const a = mkdtempSync(join(tmpdir(), 'editor-a-'))
    const b = mkdtempSync(join(tmpdir(), 'editor-b-'))
    const expected = exe(b, 'editor')

    expect(resolveEditor({ PATH: [a, b].join(delimiter) })).toEqual([expected])
  })

  it('uses notepad.exe on Windows when no env override', () => {
    expect(resolveEditor({ PATH: dir }, 'win32')).toEqual(['notepad.exe'])
  })
})

interface StableReadStep {
  at: number
  content?: string
  fail?: boolean
}

const stableReadHarness = (initial: string, steps: StableReadStep[] = []) => {
  let elapsed = 0
  let content = initial
  let fail = false

  return {
    options: {
      now: () => elapsed,
      read: async () => {
        if (fail) {
          fail = false
          throw new Error('temporary read failure')
        }

        return content
      },
      wait: async (delay: number) => {
        elapsed += delay

        for (const step of steps.filter(candidate => candidate.at === elapsed)) {
          content = step.content ?? content
          fail = step.fail ?? false
        }
      }
    },
    elapsed: () => elapsed
  }
}

describe('readStableEditorFile', () => {
  it('waits for a delayed save and returns its stable contents', async () => {
    const harness = stableReadHarness('draft', [{ at: 50, content: 'final prompt' }])

    await expect(readStableEditorFile('prompt.md', 'draft', harness.options)).resolves.toBe('final prompt')
    expect(harness.elapsed()).toBe(250)
  })

  it('debounces closely spaced saves and returns the last one', async () => {
    const harness = stableReadHarness('draft', [
      { at: 50, content: 'partial prompt' },
      { at: 150, content: 'final prompt' }
    ])

    await expect(readStableEditorFile('prompt.md', 'draft', harness.options)).resolves.toBe('final prompt')
    expect(harness.elapsed()).toBe(350)
  })

  it('accepts unchanged contents after the bounded timeout', async () => {
    const harness = stableReadHarness('draft')

    await expect(readStableEditorFile('prompt.md', 'draft', harness.options)).resolves.toBe('draft')
    expect(harness.elapsed()).toBe(2_000)
  })

  it('retries transient read failures while waiting for stability', async () => {
    const harness = stableReadHarness('draft', [
      { at: 50, content: 'final prompt' },
      { at: 100, fail: true }
    ])

    await expect(readStableEditorFile('prompt.md', 'draft', harness.options)).resolves.toBe('final prompt')
    expect(harness.elapsed()).toBe(250)
  })
})
