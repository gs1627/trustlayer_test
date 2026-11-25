import { useEffect, useRef, useState } from 'react'
import { Radio, Phone, PhoneOff, ShieldCheck, ShieldAlert, Fingerprint, Mic, Activity, AlertTriangle, Languages, MessageSquare } from 'lucide-react'
import { useCallSession } from '../hooks/useCallSession'
import { useWebSocket } from '../hooks/useWebSocket'
import { connectCallAudio } from '../services/websocket'
import type { EvidenceItem } from '../types/evidence'

function floatToPcm16(input: Float32Array, inputRate: number): ArrayBuffer {
  const ratio = inputRate / 16000
  const length = Math.floor(input.length / ratio)
  const output = new Int16Array(length)
  for (let i = 0; i < length; i++) {
    const sample = input[Math.min(Math.floor(i * ratio), input.length - 1)] || 0
    output[i] = Math.max(-1, Math.min(1, sample)) < 0
      ? Math.max(-32768, Math.min(32767, sample * 32768))
      : Math.max(-32768, Math.min(32767, sample * 32767))
  }
  return output.buffer
}

function LiveMonitoring() {
  const { session, start, end, loading, error } = useCallSession()
  const { events, status: eventStatus } = useWebSocket(session?.call_id || null)
  const [micStatus, setMicStatus] = useState('Not started')
  const [speakerId, setSpeakerId] = useState('')
  const [audioError, setAudioError] = useState('')
  const [evidence, setEvidence] = useState<EvidenceItem[]>([])
  const [decision, setDecision] = useState('Insufficient Evidence')
  const audioSocket = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const contextRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)

  useEffect(() => () => { processorRef.current?.disconnect(); contextRef.current?.close(); streamRef.current?.getTracks().forEach(t => t.stop()); audioSocket.current?.close() }, [])

  async function startCall() {
    setAudioError('')
    try {
      const created = await start(speakerId.trim() ? { checksMode: 'deepfake,verify', speakerId: speakerId.trim() } : { checksMode: 'deepfake' })
      const socket = connectCallAudio(created.call_id)
      audioSocket.current = socket
      socket.onopen = async () => {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
          streamRef.current = stream
          const context = new AudioContext()
          contextRef.current = context
          const source = context.createMediaStreamSource(stream)
          const processor = context.createScriptProcessor(4096, 1, 1)
          processorRef.current = processor
          processor.onaudioprocess = (event) => {
            if (socket.readyState === WebSocket.OPEN) socket.send(floatToPcm16(event.inputBuffer.getChannelData(0), context.sampleRate))
          }
          source.connect(processor); processor.connect(context.destination)
          setMicStatus('Streaming PCM audio to backend / DetectifAI')
        } catch (err) { setAudioError(err instanceof Error ? err.message : 'Microphone unavailable'); setMicStatus('Microphone unavailable') }
      }
      socket.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data)
          if (data.type === 'error') setAudioError(data.message || data.code || 'Audio stream error')
          if (data.source === 'detectifai' && data.type === 'completed') setMicStatus('Provider stream completed')
        } catch { /* provider frames are not guaranteed to be JSON */ }
      }
      socket.onerror = () => setAudioError('Live audio WebSocket failed. Check backend logs and authentication.')
    } catch (err) { setAudioError(err instanceof Error ? err.message : 'Could not start call session') }
  }

  async function stopCall() {
    if (audioSocket.current?.readyState === WebSocket.OPEN) audioSocket.current.send(JSON.stringify({ type: 'stop' }))
    audioSocket.current?.close(); audioSocket.current = null
    processorRef.current?.disconnect(); processorRef.current = null
    await contextRef.current?.close(); contextRef.current = null
    streamRef.current?.getTracks().forEach(t => t.stop()); streamRef.current = null
    setMicStatus('Stopped')
    try { await end() } catch (err) { setAudioError(err instanceof Error ? err.message : 'Could not end session') }
  }

  useEffect(() => {
    if (!session?.call_id) return
    let cancelled = false
    const load = async () => {
      try {
        const { callsService } = await import('../services/calls')
        const [ev, assessment] = await Promise.all([callsService.evidence(session.call_id), callsService.latestAssessment(session.call_id).catch(() => null)])
        if (!cancelled) { setEvidence(ev.items); if (assessment) setDecision(assessment.recommended_action.replaceAll('_', ' ').toUpperCase()) }
      } catch { /* evidence is refreshed by live event feed; no invented state */ }
    }
    void load()
    return () => { cancelled = true }
  }, [session?.call_id, events.length])

  return <div className="space-y-7">
    <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center"><div className="flex items-center gap-3"><div className="rounded-xl bg-cyan-500/10 p-3"><Radio className="h-7 w-7 text-cyan-400" /></div><div><h1 className="text-2xl font-bold text-white">Live Call Monitoring</h1><p className="mt-1 text-sm text-slate-400">Backend call session, DetectifAI audio stream and event feed.</p></div></div><span className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-300">API connected when backend is available</span></section>
    <div className="flex gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4"><AlertTriangle className="h-5 w-5 shrink-0 text-amber-400" /><p className="text-xs leading-5 text-slate-400">Live capture sends mono PCM16 audio to your configured backend and DetectifAI stream. It does not connect to a telephone network. Sarvam live transcription is not yet attached to this WebSocket path.</p></div>
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-6"><div className="mb-5 max-w-xl"><label className="mb-2 block text-sm text-slate-300">Enrolled speaker ID (optional)</label><input value={speakerId} onChange={e=>setSpeakerId(e.target.value)} placeholder="Leave blank for Aletheia-only unknown caller check" disabled={!!session && !['ended','completed','disconnected'].includes(session.status)} className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm text-white outline-none focus:border-cyan-500"/><p className="mt-1 text-xs text-slate-500">Enter an existing Eidos speaker ID to request combined deepfake and speaker verification.</p></div><div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-center"><div><p className="text-sm text-slate-400">Current call session</p><h2 className="mt-2 text-xl font-bold text-white">{session ? session.status : 'No active session'}</h2><p className="mt-2 break-all text-xs text-slate-500">{session ? `Session ID: ${session.call_id}` : 'Start a monitored audio session.'}</p></div>{!session || ['ended','completed','disconnected'].includes(session.status) ? <button disabled={loading} onClick={startCall} className="flex items-center justify-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50"><Phone size={18}/>Start monitored call</button> : <button disabled={loading} onClick={stopCall} className="flex items-center justify-center gap-2 rounded-lg bg-rose-500 px-5 py-3 font-semibold text-white disabled:opacity-50"><PhoneOff size={18}/>End call</button>}</div><div className="mt-6 grid gap-4 border-t border-slate-800 pt-5 sm:grid-cols-3"><div><p className="text-xs text-slate-500">Microphone / audio</p><p className="mt-2 text-sm font-semibold text-cyan-300">{micStatus}</p></div><div><p className="text-xs text-slate-500">Dashboard event socket</p><p className="mt-2 text-sm font-semibold text-cyan-300">{eventStatus}</p></div><div><p className="text-xs text-slate-500">Trust decision</p><p className="mt-2 text-sm font-semibold text-amber-300">{decision}</p></div></div>{(error || audioError) && <p className="mt-4 rounded-lg bg-red-500/10 p-3 text-sm text-red-300">{audioError || error}</p>}</section>
    <section><h2 className="mb-4 text-lg font-semibold text-white">AI Security Evidence</h2><div className="grid gap-4 md:grid-cols-3">{[{name:'Voice authenticity',provider:'DetectifAI Aletheia',icon:ShieldCheck,kind:'deepfake'},{name:'Speaker identity',provider:'DetectifAI Eidos',icon:Fingerprint,kind:'speaker_verification'},{name:'Speech transcription',provider:'Sarvam Saaras',icon:Languages,kind:'transcription'}].map(item => { const Icon=item.icon; const matches=evidence.filter(e=>e.check_type===item.kind); return <div key={item.kind} className="rounded-xl border border-slate-800 bg-slate-900 p-5"><Icon className="h-6 w-6 text-cyan-400"/><h3 className="mt-4 font-semibold text-white">{item.name}</h3><p className="mt-1 text-xs text-slate-500">{item.provider}</p><p className="mt-3 text-sm text-amber-300">{matches.length ? `${matches.length} evidence item(s): ${matches[matches.length-1].status}${matches[matches.length-1].verdict ? ` · ${matches[matches.length-1].verdict}` : ''}` : 'No evidence received'}</p></div>})}</div></section>
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-6"><div className="flex items-center gap-2"><ShieldAlert className="h-5 w-5 text-amber-400"/><h2 className="text-lg font-semibold text-white">Trust Engine</h2></div><p className="mt-4 rounded-lg bg-slate-950 p-5 text-center text-amber-300">{decision}</p><p className="mt-2 text-xs text-slate-500">No evidence is interpreted as approval. Only persisted Trust Engine assessments are displayed.</p></section>
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-6"><div className="flex items-center gap-2"><MessageSquare className="h-5 w-5 text-cyan-400"/><h2 className="text-lg font-semibold text-white">Live events</h2><Activity className="ml-auto h-4 w-4 text-slate-500"/></div><div className="mt-4 max-h-72 space-y-2 overflow-auto">{events.length ? events.slice().reverse().map((event, i)=><pre key={i} className="overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">{JSON.stringify(event,null,2)}</pre>) : <p className="text-sm text-slate-500">No events received yet.</p>}</div></section>
  </div>
}
export default LiveMonitoring
