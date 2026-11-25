export type ChecksMode = 'deepfake' | 'deepfake,verify' | 'deepfake,enroll'
export interface CallSession {
  call_id: string; speaker_id?: string | null; checks_mode: ChecksMode; consent_confirmed: boolean
  status: string; created_at?: string; updated_at?: string; ended_at?: string | null
}
export interface CallSessionCreate { call_id: string; speaker_id?: string; checks_mode: ChecksMode; consent_confirmed: boolean; display_name?: string }
export interface Paginated<T> { items: T[]; total: number; limit: number; offset: number }
export interface CallSessionCreated { call_id: string; speaker_id?: string | null; checks_mode: ChecksMode; status: string }
