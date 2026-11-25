import { callsService } from './calls'
import type { SimulatedTransactionRequest } from '../types/transaction'
export const transactionsService = {
  simulateForCall: (callId: string, payload: SimulatedTransactionRequest) => callsService.simulateTransaction(callId, payload),
}
