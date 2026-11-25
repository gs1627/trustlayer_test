import { useCallback, useState } from 'react'
import { callsService } from '../services/calls'
import type { CallSession, ChecksMode } from '../types/call'

export function useCallSession() {
  const [session, setSession] = useState<CallSession | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const start = useCallback(async (options: { speakerId?: string; checksMode?: ChecksMode; consentConfirmed?: boolean } = {}) => {
    setLoading(true); setError('')
    try {
      const payload = {
        call_id: `TL-${crypto.randomUUID()}`,
        checks_mode: options.checksMode || (options.speakerId ? 'deepfake,verify' : 'deepfake'),
        consent_confirmed: options.consentConfirmed || false,
        ...(options.speakerId ? { speaker_id: options.speakerId } : {}),
      } as const
      await callsService.create(payload)
      const created: CallSession = { ...payload, status: 'created' }
      setSession(created); return created
    } catch (err) { const message = err instanceof Error ? err.message : 'Could not create call session'; setError(message); throw err }
    finally { setLoading(false) }
  }, [])
  const end = useCallback(async () => {
    if (!session) return
    setLoading(true)
    try { const ended = await callsService.end(session.call_id); setSession(ended) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not end call'); throw err }
    finally { setLoading(false) }
  }, [session])
  return { session, setSession, loading, error, start, end }
}
