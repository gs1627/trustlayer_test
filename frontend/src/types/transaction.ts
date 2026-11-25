export type TransactionDecision = 'allow' | 'step_up_verify' | 'hold' | 'block'
export interface SimulatedTransactionRequest {
  action_type: 'fund_transfer' | 'beneficiary_add' | 'credential_reset' | 'limit_change'
  amount: string; currency: string; recipient_ref: string; notes?: string
}
export interface SimulatedTransactionResponse {
  transaction_id: string; call_id: string; assessment_id?: string | null; action_type: string
  amount: string; currency: string; decision: TransactionDecision; policy_reasons: string[]
  evidence_ids: string[]; policy_version: string; simulated: true; created_at: string
}
