import { useState } from 'react'
import { BrainCircuit, Upload, AlertTriangle, ShieldCheck, Loader2, FileAudio } from 'lucide-react'
import { callsService } from '../services/calls'

interface PipelineResponse { call_id: string; transcript?: string | null; language?: string | null; evidence: Array<Record<string, unknown>>; decision: Record<string, unknown> }

function ConversationIntelligence() {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<PipelineResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function analyze() {
    if (!file) { setError('Choose an audio file first.'); return }
    setLoading(true); setError(''); setResult(null)
    try {
      const callId = `INTEL-${crypto.randomUUID()}`
      await callsService.create({ call_id: callId, checks_mode: 'deepfake', consent_confirmed: false })
      const response = await callsService.analyzeAudio(callId, file, [])
      setResult(response)
    } catch (err) { setError(err instanceof Error ? err.message : 'Conversation analysis failed.') }
    finally { setLoading(false) }
  }

  return <div className="space-y-6">
    <div><div className="flex items-center gap-2 text-cyan-400 text-sm font-medium"><BrainCircuit size={17}/> AI-POWERED AUDIO ANALYSIS</div><h1 className="mt-2 text-2xl font-bold text-white">Conversation Intelligence</h1><p className="mt-1 text-slate-400">Transcribe audio with Sarvam and inspect conversation context with Gemini when configured.</p></div>
    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4"><div className="flex gap-3"><AlertTriangle className="shrink-0 text-amber-400" size={20}/><p className="text-sm text-slate-400">This endpoint accepts an audio file, not a pasted transcript. Use consented test recordings only. DetectifAI voice evidence is not supplied by this page; without independent authenticity and identity evidence, the Trust Engine must remain insufficient rather than approving the caller.</p></div></div>
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-4"><h2 className="font-semibold text-white">Audio input</h2><label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-slate-700 bg-slate-950 p-5"><Upload className="text-cyan-400"/><span className="text-sm text-slate-300">{file ? file.name : 'Choose audio recording (max 25 MB)'}</span><input className="hidden" type="file" accept="audio/*" onChange={e=>{setFile(e.target.files?.[0] || null);setResult(null);setError('')}}/></label>{file && <div className="flex items-center gap-2 text-xs text-slate-500"><FileAudio size={15}/>{(file.size/1024/1024).toFixed(2)} MB</div>}<button onClick={analyze} disabled={!file || loading} className="flex items-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 disabled:opacity-50">{loading?<Loader2 className="animate-spin" size={17}/>:<BrainCircuit size={17}/>} {loading?'Analyzing with backend...':'Analyze audio'}</button>{error && <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-300">{error}</p>}</section>
    {result && <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 space-y-4"><h2 className="font-semibold text-white">Backend analysis result</h2><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-lg bg-slate-950 p-3"><p className="text-xs text-slate-500">Language</p><p className="mt-1 text-white">{result.language || 'Not returned'}</p></div><div className="rounded-lg bg-slate-950 p-3"><p className="text-xs text-slate-500">Trust recommendation</p><p className="mt-1 text-amber-300">{String(result.decision.recommended_action || 'insufficient_evidence').replaceAll('_',' ').toUpperCase()}</p></div></div><div className="rounded-lg bg-slate-950 p-4"><p className="text-xs text-slate-500">Transcript</p><p className="mt-2 whitespace-pre-wrap text-sm text-slate-200">{result.transcript || 'No final transcript returned.'}</p></div><div><p className="mb-2 text-xs text-slate-500">Evidence returned ({result.evidence.length})</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-4 text-xs text-slate-300">{JSON.stringify(result.evidence,null,2)}</pre></div><pre className="max-h-64 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-400">{JSON.stringify(result.decision,null,2)}</pre></section>}
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5"><div className="mb-3 flex items-center gap-2"><ShieldCheck className="text-cyan-400" size={20}/><h2 className="font-semibold text-white">Security principle</h2></div><p className="text-sm leading-6 text-slate-400">Conversation intelligence flags possible social-engineering indicators. It does not establish voice authenticity, verify speaker identity, or authorize transactions. Those require separate Aletheia and Eidos evidence and the deterministic Trust Engine.</p></div>
  </div>
}
export default ConversationIntelligence
