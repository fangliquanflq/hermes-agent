import { act, cleanup } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderMessageStream } from './test-harness'

afterEach(cleanup)

describe('background.complete routing', () => {
  it('appends the result only to the originating session', () => {
    const stream = renderMessageStream('foreground-session')

    act(() =>
      stream.handleEvent({
        payload: { task_id: 'bg_123', text: 'Finished in the background.' },
        session_id: 'origin-session',
        type: 'background.complete'
      })
    )

    expect(stream.text('origin-session')).toContain('Finished in the background.')
    expect(stream.state('origin-session').messages.at(-1)?.role).toBe('system')
    expect(stream.state('foreground-session').messages).toHaveLength(0)
  })
})