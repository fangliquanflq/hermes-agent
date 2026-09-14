import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  requestGatewayForAgent: vi.fn().mockResolvedValue({ status: 'ok' }),
  runPreviewAction: vi.fn().mockResolvedValue({ elements: [{ ref: 'link-1' }], success: true })
}))

vi.mock('@/store/gateway', () => ({ requestGatewayForAgent: mocks.requestGatewayForAgent }))
vi.mock('./server-requests', () => ({ runPreviewAction: mocks.runPreviewAction }))

import { handleDesktopBridgeEvent } from './desktop-bridge'
import type { GatewayEventContext } from './types'

function legacyPreviewContext(activeSessionId: string): GatewayEventContext {
  return {
    event: {
      connectionId: 'remote-vps',
      payload: { action: 'elements', request_id: 'legacy-request-1' },
      profile: 'default',
      session_id: 'session-a',
      type: 'preview.act.request'
    },
    explicitSid: 'session-a',
    isActiveEvent: activeSessionId === 'session-a',
    payload: { action: 'elements', request_id: 'legacy-request-1' },
    sessionId: 'session-a'
  } as GatewayEventContext
}

describe('legacy preview action bridge', () => {
  afterEach(() => {
    vi.clearAllMocks()
  })

  it('answers an older remote backend from the active Desktop session', async () => {
    expect(handleDesktopBridgeEvent(legacyPreviewContext('session-a'))).toBe(true)

    await vi.waitFor(() => expect(mocks.requestGatewayForAgent).toHaveBeenCalledTimes(1))
    expect(mocks.runPreviewAction).toHaveBeenCalledWith({ action: 'elements', request_id: 'legacy-request-1' })
    expect(mocks.requestGatewayForAgent).toHaveBeenCalledWith(
      'remote-vps',
      'default',
      'preview.act.respond',
      {
        request_id: 'legacy-request-1',
        text: JSON.stringify({ elements: [{ ref: 'link-1' }], success: true })
      }
    )
  })

  it('leaves a scoped legacy request unanswered in another window', async () => {
    expect(handleDesktopBridgeEvent(legacyPreviewContext('session-b'))).toBe(true)

    await Promise.resolve()
    expect(mocks.runPreviewAction).not.toHaveBeenCalled()
    expect(mocks.requestGatewayForAgent).not.toHaveBeenCalled()
  })
})