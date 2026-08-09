import { createRequire } from 'node:module'

import { rebuildGetWindowsViaNpm } from './stage-native-deps.mjs'
import { isMain } from './utils.mjs'

const SUPPORTED_WINDOWS_ARCHES = new Set(['x64', 'ia32'])
const require = createRequire(import.meta.url)

function isGetWindowsInstalled() {
  try {
    require.resolve('get-windows')
    return true
  } catch {
    return false
  }
}

export function prepareGetWindowsForHost({
  platform = process.platform,
  arch = process.arch,
  installed = isGetWindowsInstalled(),
  rebuild = rebuildGetWindowsViaNpm
} = {}) {
  if (platform !== 'win32' || !installed) return false

  if (!SUPPORTED_WINDOWS_ARCHES.has(arch)) {
    console.warn(
      `[root postinstall] get-windows has no supported ${platform}-${arch} binding; ` +
      'native window enumeration will remain disabled.'
    )
    return false
  }

  console.log(`[root postinstall] rebuilding get-windows for ${platform}-${arch}...`)
  const status = rebuild()
  if (status !== 0) {
    throw new Error(`npm rebuild get-windows exited with ${status}`)
  }
  return true
}

if (isMain(import.meta.url)) {
  prepareGetWindowsForHost()
  console.log('✅ Browser tools ready. Run: python run_agent.py --help')
}
