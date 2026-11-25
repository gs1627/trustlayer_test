import { useEffect, useRef, useState } from 'react'
import { connectCallEvents } from '../services/websocket'

export function useWebSocket(callId: string | null) {
  const socketRef = useRef<WebSocket | null>(null)
  const [events, setEvents] = useState<unknown[]>([])
  const [status, setStatus] = useState<'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'>('idle')
  useEffect(() => {
    if (!callId) { setStatus('idle'); return }
    setStatus('connecting')
    const socket = connectCallEvents(callId); socketRef.current = socket
    socket.onopen = () => setStatus('connected')
    socket.onmessage = (message) => { try { setEvents((old) => [...old.slice(-99), JSON.parse(message.data)]) } catch { /* ignore malformed frames */ } }
    socket.onerror = () => setStatus('error')
    socket.onclose = () => setStatus((old) => old === 'error' ? old : 'disconnected')
    return () => { socket.close(); socketRef.current = null }
  }, [callId])
  return { events, status, socket: socketRef }
}
