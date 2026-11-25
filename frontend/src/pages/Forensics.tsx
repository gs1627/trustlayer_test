
import { useRef, useState } from 'react'
import { callsService } from '../services/calls'
import {
  Upload,
  FileAudio,
  ShieldCheck,
  ShieldAlert,
  Clock,
  Activity,
  Trash2,
  AlertTriangle,
  Fingerprint,
  FileSearch,
} from 'lucide-react'

function Forensics() {
  const [file, setFile] = useState<File | null>(null)
  const [audioUrl, setAudioUrl] = useState('')
  const [analyzing, setAnalyzing] = useState(false)
  const [analysisComplete, setAnalysisComplete] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState<{ callId: string; aletheia?: unknown; intelligence?: unknown } | null>(null)

  const inputRef = useRef<HTMLInputElement>(null)

  function handleFileChange(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const selectedFile = event.target.files?.[0]

    if (!selectedFile) return

    if (!selectedFile.type.startsWith('audio/')) {
      setError('Please select a valid audio file.')
      return
    }

    if (selectedFile.size > 25 * 1024 * 1024) {
      setError('Please select an audio file smaller than 25 MB.')
      return
    }

    if (audioUrl) URL.revokeObjectURL(audioUrl)

    setFile(selectedFile)
    setAudioUrl(URL.createObjectURL(selectedFile))
    setAnalysisComplete(false)
    setError('')
  }

  function removeFile() {
    if (audioUrl) URL.revokeObjectURL(audioUrl)

    setFile(null)
    setAudioUrl('')
    setAnalysisComplete(false)
    setAnalyzing(false)
    setReport(null)
    setError('')

    if (inputRef.current) inputRef.current.value = ''
  }

  async function runDemoAnalysis() {
    if (!file) { setError('Upload an audio file first.'); return }
    setError(''); setAnalyzing(true); setAnalysisComplete(false); setReport(null)
    try {
      const callId = `FORENSIC-${crypto.randomUUID()}`
      await callsService.create({ call_id: callId, checks_mode: 'deepfake', consent_confirmed: false })
      const outcomes = await Promise.allSettled([
        callsService.detectDeepfake(file, callId),
        callsService.analyzeAudio(callId, file, []),
      ])
      const aletheia = outcomes[0].status === 'fulfilled' ? outcomes[0].value : { error: outcomes[0].reason instanceof Error ? outcomes[0].reason.message : 'Aletheia request failed' }
      const intelligence = outcomes[1].status === 'fulfilled' ? outcomes[1].value : { error: outcomes[1].reason instanceof Error ? outcomes[1].reason.message : 'Sarvam/Gemini analysis failed' }
      setReport({ callId, aletheia, intelligence }); setAnalysisComplete(true)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not create forensic analysis session.') }
    finally { setAnalyzing(false) }
  }

  return (
    <div className="space-y-7">

      {/* Header */}
      <section className="flex items-center gap-3">
        <div className="rounded-xl bg-cyan-500/10 p-3">
          <FileSearch className="h-7 w-7 text-cyan-400" />
        </div>

        <div>
          <h1 className="text-2xl font-bold text-white">
            Audio Forensics
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Inspect recordings and review voice security evidence.
          </p>
        </div>
      </section>

      {/* Development notice */}
      <div className="flex gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <AlertTriangle className="h-5 w-5 shrink-0 text-amber-400" />
        <div>
          <p className="text-sm font-semibold text-amber-300">
            Frontend demonstration
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-400">
            The analysis action creates a backend call session and submits the recording to Aletheia plus the Sarvam/Gemini clip pipeline. Eidos identity is not checked unless a speaker is enrolled and separately verified.
          </p>
        </div>
      </div>

      {/* Upload */}
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h2 className="text-lg font-semibold text-white">
          Upload Audio Evidence
        </h2>

        <p className="mt-1 text-xs text-slate-400">
          Select an audio recording for forensic review.
        </p>

        <input
          ref={inputRef}
          type="file"
          accept="audio/*"
          onChange={handleFileChange}
          className="hidden"
        />

        {!file ? (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="mt-6 flex w-full flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-700 bg-slate-950 p-10 text-center transition hover:border-cyan-400"
          >
            <Upload className="h-10 w-10 text-cyan-400" />

            <p className="mt-4 font-semibold text-white">
              Click to upload audio
            </p>

            <p className="mt-2 text-xs text-slate-500">
              Audio files · Maximum 25 MB
            </p>
          </button>
        ) : (
          <div className="mt-6 rounded-xl border border-slate-700 bg-slate-950 p-5">
            <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-cyan-500/10 p-3">
                  <FileAudio className="h-6 w-6 text-cyan-400" />
                </div>

                <div>
                  <p className="break-all text-sm font-medium text-white">
                    {file.name}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {(file.size / (1024 * 1024)).toFixed(2)} MB
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={removeFile}
                className="flex items-center gap-2 self-start text-xs text-rose-400 hover:text-rose-300"
              >
                <Trash2 size={16} />
                Remove
              </button>
            </div>

            <audio
              controls
              src={audioUrl}
              className="mt-5 w-full"
            />
          </div>
        )}

        {error && (
          <p className="mt-4 text-sm text-rose-400">
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={runDemoAnalysis}
          disabled={!file || analyzing}
          className="mt-5 flex items-center justify-center gap-2 rounded-lg bg-cyan-500 px-6 py-3 font-semibold text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Activity size={18} />
          {analyzing ? 'Submitting to backend...' : 'Run Backend Analysis'}
        </button>
      </section>

      {/* File metadata */}
      {file && (
        <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-lg font-semibold text-white">
            Audio Metadata
          </h2>

          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <div className="rounded-lg bg-slate-950 p-4">
              <p className="text-xs text-slate-500">File type</p>
              <p className="mt-2 break-all text-sm text-white">
                {file.type || 'Not reported'}
              </p>
            </div>

            <div className="rounded-lg bg-slate-950 p-4">
              <p className="text-xs text-slate-500">File size</p>
              <p className="mt-2 text-sm text-white">
                {(file.size / (1024 * 1024)).toFixed(2)} MB
              </p>
            </div>

            <div className="rounded-lg bg-slate-950 p-4">
              <p className="text-xs text-slate-500">Last modified</p>
              <p className="mt-2 text-sm text-white">
                {new Date(file.lastModified).toLocaleDateString()}
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Analysis results */}
      {analysisComplete && (
        <>
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-amber-400" />
              <h2 className="text-lg font-semibold text-white">
                Analysis Report
              </h2>
            </div>

            <div className="mt-5 rounded-xl border border-amber-500/20 bg-amber-500/5 p-5">
              <p className="font-semibold text-amber-300">
                Provider responses
              </p>
              <p className="mt-2 text-sm leading-6 text-slate-400">
                The backend responses below are provider operation and pipeline outputs. Missing or failed results are not treated as a genuine-voice verdict.
              </p>
            </div>
            <div className="mt-4 rounded-lg bg-slate-950 p-4"><p className="mb-2 text-xs text-slate-500">Call ID: {report?.callId}</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-300">{JSON.stringify(report, null, 2)}</pre></div>
          </section>

          <section className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex items-center gap-3">
                <ShieldCheck className="h-6 w-6 text-cyan-400" />
                <h3 className="font-semibold text-white">
                  Aletheia Authenticity
                </h3>
              </div>
              <p className="mt-4 text-sm text-amber-400">
                Request completed or returned an error; inspect provider response above
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex items-center gap-3">
                <Fingerprint className="h-6 w-6 text-cyan-400" />
                <h3 className="font-semibold text-white">
                  Eidos Speaker Identity
                </h3>
              </div>
              <p className="mt-4 text-sm text-amber-400">
                Not run: no enrolled speaker ID was supplied
              </p>
            </div>
          </section>
        </>
      )}

      {/* Evidence timeline */}
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex items-center gap-2">
          <Clock className="h-5 w-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-white">
            Evidence Timeline
          </h2>
        </div>

        <div className="mt-5 space-y-4">
          <div className="flex items-start gap-3">
            <span className="mt-1 h-2.5 w-2.5 rounded-full bg-cyan-400" />
            <div>
              <p className="text-sm text-white">Forensic workspace initialized</p>
              <p className="mt-1 text-xs text-slate-500">Frontend ready</p>
            </div>
          </div>

          {file && (
            <div className="flex items-start gap-3">
              <span className="mt-1 h-2.5 w-2.5 rounded-full bg-cyan-400" />
              <div>
                <p className="text-sm text-white">Audio file selected</p>
                <p className="mt-1 text-xs text-slate-500">{file.name}</p>
              </div>
            </div>
          )}

          {analysisComplete && (
            <div className="flex items-start gap-3">
              <span className="mt-1 h-2.5 w-2.5 rounded-full bg-amber-400" />
              <div>
                <p className="text-sm text-white">Demo workflow completed</p>
                <p className="mt-1 text-xs text-slate-500">
                  Backend response received; review raw result and status
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

    </div>
  )
}

export default Forensics
