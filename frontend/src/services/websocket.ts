import { getAccessToken, getWebSocketUrl } from './api'

export function connectCallAudio(callId: string): WebSocket {
  const socket = new WebSocket(getWebSocketUrl(`/calls/ws/${encodeURIComponent(callId)}`))
  socket.addEventListener('open', () => {
    const token = getAccessToken()
    if (token) socket.send(JSON.stringify({ type: 'auth', token }))
  }, { once: true })
  return socket
}

export function connectCallEvents(callId: string): WebSocket {
  const socket = new WebSocket(getWebSocketUrl(`/calls/ws/${encodeURIComponent(callId)}/events`))
  socket.addEventListener('open', () => {
    const token = getAccessToken()
    if (token) socket.send(JSON.stringify({ type: 'auth', token }))
  }, { once: true })
  return socket
}
