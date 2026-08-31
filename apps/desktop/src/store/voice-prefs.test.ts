import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getHermesConfigRecord, saveHermesConfig } = vi.hoisted(() => ({
  getHermesConfigRecord: vi.fn(),
  saveHermesConfig: vi.fn()
}))

vi.mock('@/hermes', () => ({
  getHermesConfigRecord,
  saveHermesConfig
}))

import {
  $autoSpeakReplies,
  $voiceStopPhrase,
  applyAutoSpeakFromConfig,
  applyVoiceStopPhraseFromConfig,
  setAutoSpeakReplies
} from './voice-prefs'

describe('desktop auto-speak preference', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    $autoSpeakReplies.set(false)
    getHermesConfigRecord.mockResolvedValue({
      desktop: { repo_scan_enabled: true },
      voice: { auto_tts: false, thinking_sound: true }
    })
    saveHermesConfig.mockResolvedValue(undefined)
  })

  it('loads the desktop preference independently of gateway auto-TTS', () => {
    applyAutoSpeakFromConfig({
      desktop: { auto_speak_replies: true },
      voice: { auto_tts: false }
    })

    expect($autoSpeakReplies.get()).toBe(true)
  })

  it('persists only the desktop preference and preserves gateway auto-TTS', async () => {
    await setAutoSpeakReplies(true)

    expect(saveHermesConfig).toHaveBeenCalledWith({
      desktop: { repo_scan_enabled: true, auto_speak_replies: true },
      voice: { auto_tts: false, thinking_sound: true }
    })
    expect($autoSpeakReplies.get()).toBe(true)
  })
})

describe('applyVoiceStopPhraseFromConfig', () => {
  it('defaults to "stop" when the key is absent (backend default applies)', () => {
    applyVoiceStopPhraseFromConfig({ voice: {} })
    expect($voiceStopPhrase.get()).toBe('stop')

    applyVoiceStopPhraseFromConfig(null)
    expect($voiceStopPhrase.get()).toBe('stop')
  })

  it('uses the first configured phrase so a custom phrase renders correctly', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: ['goodbye hermes', 'stop'] } })
    expect($voiceStopPhrase.get()).toBe('goodbye hermes')
  })

  it('coerces a bare string like the backend does', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: 'halt' } })
    expect($voiceStopPhrase.get()).toBe('halt')
  })

  it('null phrase when stop phrases are disabled — no notice is shown', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: [] } })
    expect($voiceStopPhrase.get()).toBeNull()
  })

  it('malformed entries are skipped; all-blank list disables', () => {
    applyVoiceStopPhraseFromConfig({ voice: { stop_phrases: ['  ', ''] } })
    expect($voiceStopPhrase.get()).toBeNull()
  })
})
