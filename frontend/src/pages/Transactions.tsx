import { useState } from 'react'
import { ShieldCheck, ShieldAlert, Lock, Loader2 } from 'lucide-react'
import { callsService } from '../services/calls'
import type { SimulatedTransactionResponse } from '../types/transaction'

function Transactions() {
  const [callId, setCallId] = useState('')
  const [actionType, setActionType] = useState<'fund_transfer'|'beneficiary_add'|'credential_reset'|'limit_change'>('fund_transfer')
  const [amount, setAmount] = useState('25000')
  const [recipient, setRecipient] = useState('DEMO_BENEFICIARY_01')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<SimulatedTransactionResponse | null>(null)

  async function evaluate() {
    if (!callId.trim()) { setError('Enter an existing backend call session ID first.'); return }
    if (!Number.isFinite(Number(amount)) || Number(amount) <= 0) { setError('Enter a valid positive amount.'); return }
    setLoading(true); setError(''); setResult(null)
    try {
      const response = await callsService.simulateTransaction(callId.trim(), { action_type: actionType, amount, currency: 'INR', recipient_ref: recipient.trim() })
      setResult(response)
    } catch (err) { setError(err instanceof Error ? err.message : 'Transaction policy evaluation failed.') }
    finally { setLoading(false) }
  }

  const decisionColor = result?.decision === 'allow' ? 'text-emerald-400' : 'text-amber-300'
  return <div className="space-y-6">
    <div><div className="flex items-center gap-2 text-cyan-400 text-sm font-medium"><ShieldCheck size={17}/> TRANSACTION SECURITY</div><h1 className="mt-2 text-2xl font-bold text-white">Transaction Guard</h1><p className="mt-1 text-slate-400">Evaluate a transaction against a persisted call trust assessment.</p></div>
    <div className="flex gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4"><ShieldAlert className="shrink-0 text-amber-400" size={20}/><p className="text-sm text-slate-400">Backend route returns a simulated policy decision only. No bank payment, beneficiary change, or real transaction is executed. An absent or insufficient trust assessment must not be treated as approval.</p></div>
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-4"><h2 className="font-semibold text-white">Evaluate transaction policy</h2><div><label className="mb-2 block text-sm text-slate-300">Existing call session ID</label><input value={callId} onChange={e=>setCallId(e.target.value)} placeholder="Paste CALL ID from Live Monitoring" className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-white outline-none focus:border-cyan-500"/></div><div className="grid gap-4 sm:grid-cols-2"><div><label className="mb-2 block text-sm text-slate-300">Action</label><select value={actionType} onChange={e=>setActionType(e.target.value as typeof actionType)} className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-white"><option value="fund_transfer">Fund transfer</option><option value="beneficiary_add">Add beneficiary</option><option value="credential_reset">Credential reset</option><option value="limit_change">Limit change</option></select></div><div><label className="mb-2 block text-sm text-slate-300">Amount (INR)</label><input value={amount} onChange={e=>setAmount(e.target.value)} inputMode="decimal" className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-white"/></div></div><div><label className="mb-2 block text-sm text-slate-300">Recipient reference</label><input value={recipient} onChange={e=>setRecipient(e.target.value)} className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-white"/></div><button disabled={loading} onClick={evaluate} className="flex items-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 disabled:opacity-50">{loading?<Loader2 size={17} className="animate-spin"/>:<Lock size={17}/>}Evaluate simulated transaction</button>{error && <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-300">{error}</p>}</section>
    {result && <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-3"><h2 className="font-semibold text-white">Policy result</h2><p className={`text-xl font-bold ${decisionColor}`}>{result.decision.replaceAll('_',' ').toUpperCase()}</p><div className="grid gap-3 sm:grid-cols-2 text-sm"><p className="text-slate-400">Transaction ID: <span className="text-white">{result.transaction_id}</span></p><p className="text-slate-400">Call ID: <span className="text-white">{result.call_id}</span></p><p className="text-slate-400">Amount: <span className="text-white">{result.currency} {result.amount}</span></p><p className="text-slate-400">Simulated: <span className="text-white">{String(result.simulated)}</span></p></div><div><p className="text-xs text-slate-500">Policy reasons</p><ul className="mt-2 list-disc pl-5 text-sm text-slate-300">{result.policy_reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul></div><pre className="max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-400">{JSON.stringify(result,null,2)}</pre></section>}
  </div>
}
export default Transactions
