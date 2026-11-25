import { apiRequest, apiUpload } from './api'
import type { CallSession, CallSessionCreate, CallSessionCreated, Paginated } from '../types/call'
import type { EvidenceItem, TrustAssessment } from '../types/evidence'
import type { SimulatedTransactionRequest, SimulatedTransactionResponse } from '../types/transaction'

export const callsService = {
  create: (payload: CallSessionCreate) => apiRequest<CallSessionCreated>('/calls/sessions', { method: 'POST', body: JSON.stringify(payload) }),
  list: (limit = 50, offset = 0) => apiRequest<Paginated<CallSession>>(`/calls/sessions?limit=${limit}&offset=${offset}`),
  get: (callId: string) => apiRequest<CallSession>(`/calls/sessions/${encodeURIComponent(callId)}`),
  end: (callId: string, reason = 'frontend_user_ended') => apiRequest<CallSession>(`/calls/sessions/${encodeURIComponent(callId)}/end`, { method: 'POST', body: JSON.stringify({ reason }) }),
  evidence: (callId: string) => apiRequest<Paginated<EvidenceItem>>(`/calls/sessions/${encodeURIComponent(callId)}/evidence`),
  latestAssessment: (callId: string) => apiRequest<TrustAssessment>(`/calls/sessions/${encodeURIComponent(callId)}/trust-assessments/latest`),
  simulateTransaction: (callId: string, payload: SimulatedTransactionRequest) => apiRequest<SimulatedTransactionResponse>(`/calls/sessions/${encodeURIComponent(callId)}/transactions/simulate`, { method: 'POST', body: JSON.stringify(payload) }),
  analyzeAudio: (callId: string, file: File, voiceEvidence: EvidenceItem[] = []) => {
    const form = new FormData(); form.append('call_id', callId); form.append('voice_evidence_json', JSON.stringify(voiceEvidence)); form.append('file', file)
    return apiUpload<{ call_id: string; transcript?: string | null; language?: string | null; evidence: EvidenceItem[]; decision: Record<string, unknown> }>('/intelligence/analyze', form)
  },
  listSpeakers: (limit = 50) => apiRequest<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(`/detectif/speakers?limit=${limit}`),
  deleteSpeaker: (speakerId: string) => apiRequest<void>(`/detectif/speakers/${encodeURIComponent(speakerId)}`, { method: 'DELETE' }),
  listOperations: (limit = 50, offset = 0) => apiRequest<Paginated<Record<string, unknown>>>(`/detectif/operations?limit=${limit}&offset=${offset}`),
  detectDeepfake: (file: File, callId?: string) => {
    const form = new FormData(); form.append('file', file); if (callId) form.append('call_id', callId)
    return apiUpload<Record<string, unknown>>('/detectif/deepfake', form)
  },
  enrollSpeaker: (speakerId: string, displayName: string, file: File, callId?: string) => {
    const form = new FormData(); form.append('speaker_id', speakerId); form.append('display_name', displayName); form.append('consent_confirmed', 'true'); form.append('file', file); if (callId) form.append('call_id', callId)
    return apiUpload<Record<string, unknown>>('/detectif/speakers/enroll', form, `enroll-${speakerId}-${file.size}-${file.lastModified}`)
  },
  verifySpeaker: (speakerId: string, file: File, callId?: string) => {
    const form = new FormData(); form.append('speaker_id', speakerId); form.append('detect_deepfake', 'true'); form.append('file', file); if (callId) form.append('call_id', callId)
    return apiUpload<Record<string, unknown>>('/detectif/speakers/verify', form)
  },
}
