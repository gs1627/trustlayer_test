export type EvidenceCheckType = 'deepfake' | 'speaker_verification' | 'transcription' | 'context'
export type EvidenceStatus = 'pending' | 'completed' | 'failed' | 'inconclusive'
export interface EvidenceItem {
  evidence_id?: string; call_id: string; provider: string; model: string; check_type: EvidenceCheckType
  status: EvidenceStatus; verdict?: string | null; raw_score?: number | null; score_type?: string | null
  is_early?: boolean | null; is_final: boolean; speaker_id?: string | null; source_channel?: string | null
  details?: Record<string, unknown>; created_at?: string
}
export interface TrustAssessment {
  assessment_id?: string; call_id: string; trust_score?: number | null; risk_level: string
  recommended_action: string; reasons?: string[]; evidence_ids?: string[]; created_at?: string
}
