import { spawnSync } from 'node:child_process'
import { accessSync, constants, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { performance } from 'node:perf_hooks'

import { withInkSuspended } from '@hermes/ink'

/**
 * Editor fallback chain when neither $VISUAL nor $EDITOR is set. Mirrors
 * prompt_toolkit's `Buffer.open_in_editor()` picker so the classic CLI and
 * the TUI launch the same editor on a given box.
 */
const FALLBACKS = ['editor', 'nano', 'pico', 'vi', 'emacs']

const EDITOR_READ_POLL_MS = 50
const EDITOR_READ_STABLE_MS = 200
const EDITOR_READ_TIMEOUT_MS = 2_000

interface StableEditorReadOptions {
  now?: () => number
  read?: (path: string) => Promise<string>
  wait?: (delay: number) => Promise<void>
}

const wait = (delay: number): Promise<void> =>
  new Promise(resolve => {
    setTimeout(resolve, delay)
  })

const isExecutable = (path: string): boolean => {
  try {
    accessSync(path, constants.X_OK)

    return true
  } catch {
    return false
  }
}

/**
 * Resolve the editor invocation argv (without the file argument).
 *
 *   1. $VISUAL / $EDITOR, shell-tokenized so `EDITOR="code --wait"` works
 *   2. on POSIX: first FALLBACKS entry resolvable on $PATH
 *   3. on Windows: `notepad.exe`
 *   4. literal `['vi']` as the last-resort POSIX floor
 */
export const resolveEditor = (
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform
): string[] => {
  const explicit = env.VISUAL ?? env.EDITOR

  if (explicit?.trim()) {
    return explicit.trim().split(/\s+/)
  }

  if (platform === 'win32') {
    return ['notepad.exe']
  }

  const dirs = (env.PATH ?? '').split(delimiter).filter(Boolean)
  const found = FALLBACKS.flatMap(name => dirs.map(d => join(d, name))).find(isExecutable)

  return [found ?? 'vi']
}

/**
 * Read an editor tempfile after its post-exit contents settle.
 *
 * Some graphical editors release their `--wait` process just before the final
 * save becomes visible. Changed contents must survive a debounce window;
 * unchanged contents remain valid once the overall wait reaches its bound.
 */
export async function readStableEditorFile(
  file: string,
  initial: string,
  options: StableEditorReadOptions = {}
): Promise<string> {
  const now = options.now ?? (() => performance.now())
  const read = options.read ?? (async (path: string) => readFile(path, 'utf8'))
  const sleep = options.wait ?? wait
  const startedAt = now()
  let latest = initial
  let latestSince = startedAt

  while (true) {
    try {
      const content = await read(file)
      const observedAt = now()

      if (content !== latest) {
        latest = content
        latestSince = observedAt
      }

      if (content !== initial && observedAt - latestSince >= EDITOR_READ_STABLE_MS) {
        return content
      }
    } catch {
      // Atomic-save renames can make the path briefly unreadable; retry below.
    }

    const elapsed = now() - startedAt

    if (elapsed >= EDITOR_READ_TIMEOUT_MS) {
      return latest
    }

    await sleep(Math.min(EDITOR_READ_POLL_MS, EDITOR_READ_TIMEOUT_MS - elapsed))
  }
}

/** Suspend Ink, open ``initial`` in $EDITOR, return the edited text (null if aborted). */
export async function openInEditor(initial: string, suffix = '.txt'): Promise<null | string> {
  const dir = mkdtempSync(join(tmpdir(), 'hermes-edit-'))
  const file = join(dir, `edit${suffix}`)
  writeFileSync(file, initial)
  const [cmd, ...args] = resolveEditor()
  let status: null | number = null

  await withInkSuspended(async () => {
    status = spawnSync(cmd!, [...args, file], { stdio: 'inherit' }).status
  })

  try {
    return status === 0 ? await readStableEditorFile(file, initial) : null
  } finally {
    rmSync(dir, { force: true, recursive: true })
  }
}
