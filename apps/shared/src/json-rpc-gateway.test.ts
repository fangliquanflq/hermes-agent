import { describe, expect, it, vi } from 'vitest'

import { JsonRpcGatewayClient } from './json-rpc-gateway'

class FakeSocket extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 3

  readonly sent: string[] = []
  readyState = FakeSocket.CONNECTING

  close() {
    this.readyState = FakeSocket.CLOSED
    this.dispatchEvent(new Event('close'))
  }

  open() {
    this.readyState = FakeSocket.OPEN
    this.dispatchEvent(new Event('open'))
  }

  receive(frame: unknown) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(frame) }))
  }

  send(frame: string) {
    this.sent.push(frame)
  }
}

describe('JsonRpcGatewayClient reconnect event recovery', () => {
  it('resumes applied cursors and ignores a replayed duplicate', async () => {
    const sockets: FakeSocket[] = []

    const client = new JsonRpcGatewayClient({
      socketFactory: () => {
        const socket = new FakeSocket()

        sockets.push(socket)

        return socket as unknown as WebSocket
      }
    })

    const received = vi.fn()

    client.onEvent(received)

    const firstConnect = client.connect('ws://localhost/api/ws')
    sockets[0].open()
    await firstConnect
    sockets[0].receive({
      jsonrpc: '2.0',
      method: 'event',
      params: { event_seq: 7, session_id: 'session-a', type: 'message.delta' }
    })

    sockets[0].close()

    const reconnect = client.connect('ws://localhost/api/ws')
    sockets[1].open()
    await reconnect

    expect(JSON.parse(sockets[1].sent[0])).toMatchObject({
      method: 'session.events.resume',
      params: { cursors: { 'session-a': 7 } }
    })

    sockets[1].receive({
      jsonrpc: '2.0',
      method: 'event',
      params: { event_seq: 7, session_id: 'session-a', type: 'message.delta' }
    })
    sockets[1].receive({
      jsonrpc: '2.0',
      method: 'event',
      params: { event_seq: 8, session_id: 'session-a', type: 'message.complete' }
    })

    expect(received.mock.calls.map(([event]) => event.event_seq)).toEqual([7, 8])
  })
})