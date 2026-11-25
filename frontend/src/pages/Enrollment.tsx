
import { useEffect, useRef, useState } from 'react'
import { callsService } from '../services/calls'
import {
  UserRound,
  Mail,
  Phone,
  Mic,
  MicOff,
  Square,
  Trash2,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  LockKeyhole,
} from 'lucide-react'

function Enrollment() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [consent, setConsent] = useState(false)

  const [recording, setRecording] = useState(false)
  const [audioUrl, setAudioUrl] = useState('')
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [audioFile, setAudioFile] = useState<File | null>(null)
  const [providerResult, setProviderResult] = useState('')

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current)
      }

      streamRef.current?.getTracks().forEach((track) => track.stop())
      recorderRef.current?.stop()

      if (audioUrl) {
        URL.revokeObjectURL(audioUrl)
      }
    }
  }, [audioUrl])

  async function startRecording() {
    try {
      setError('')

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          'Microphone access is unavailable. Use HTTPS or localhost in a supported browser.'
        )
      }

      if (audioUrl) {
        URL.revokeObjectURL(audioUrl)
        setAudioUrl('')
      }

      setDuration(0)
      chunksRef.current = []

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      })

      streamRef.current = stream

      const recorder = new MediaRecorder(stream)
      recorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        const audioBlob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })

        const url = URL.createObjectURL(audioBlob)
        setAudioUrl(url)
        setAudioFile(new File([audioBlob], 'voice-enrollment.webm', { type: audioBlob.type || 'audio/webm' }))

        stream.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }

      recorder.start()
      setRecording(true)

      timerRef.current = window.setInterval(() => {
        setDuration((previous) => previous + 1)
      }, 1000)
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Unable to access microphone.'
      )
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === 'recording') {
      recorderRef.current.stop()
    }

    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }

    setRecording(false)
  }

  function deleteRecording() {
    if (recording) {
      stopRecording()
    }

    if (audioUrl) {
      URL.revokeObjectURL(audioUrl)
    }

    setAudioUrl('')
    setAudioFile(null)
    setDuration(0)
    chunksRef.current = []
    setError('')
  }

  function formatTime(seconds: number) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60

    return `${String(minutes).padStart(2, '0')}:${String(
      remainingSeconds
    ).padStart(2, '0')}`
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    if (!consent) { setError('Please provide voice biometric consent first.'); return }
    if (!audioFile) { setError('Please record your voice before submitting.'); return }
    if (duration < 4) { setError('Please record at least 4 seconds of voice.'); return }
    try {
      const speakerId = `spk-${crypto.randomUUID()}`
      const result = await callsService.enrollSpeaker(speakerId, name.trim(), audioFile)
      setProviderResult(`Speaker ID: ${speakerId}\n${JSON.stringify(result, null, 2)}`)
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Eidos enrollment request failed.')
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-7">

      {/* Page heading */}
      <section>
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-cyan-500/10 p-3">
            <ShieldCheck className="h-7 w-7 text-cyan-400" />
          </div>

          <div>
            <h1 className="text-2xl font-bold text-white">
              Customer Voice Enrollment
            </h1>

            <p className="mt-1 text-sm text-slate-400">
              Register a customer's voice for future speaker verification.
            </p>
          </div>
        </div>
      </section>

      {/* Demo notice */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <p className="text-sm font-semibold text-amber-300">
          Development mode
        </p>

        <p className="mt-1 text-xs text-slate-400">
          This page records audio locally in your browser. The recording is sent to the backend enrollment endpoint after explicit consent. Do not upload real customer biometrics in a demo environment without approved retention and deletion controls.
        </p>
      </div>

      {submitted ? (
        <div className="rounded-xl border border-emerald-500/20 bg-slate-900 p-8 text-center">
          <CheckCircle2 className="mx-auto h-14 w-14 text-emerald-400" />

          <h2 className="mt-4 text-xl font-bold text-white">
            Enrollment request submitted
          </h2>

          <p className="mt-2 text-sm text-slate-400">
            The backend accepted the enrollment request. Provider status must be checked in the operation record; acceptance does not by itself prove enrollment completion.
          </p>

          <pre className="mx-auto mt-4 max-w-2xl overflow-auto rounded bg-slate-950 p-3 text-left text-xs text-slate-400">{providerResult}</pre>
          <button
            type="button"
            onClick={() => setSubmitted(false)}
            className="mt-6 rounded-lg bg-cyan-500 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-400"
          >
            Back to Enrollment
          </button>
        </div>
      ) : (

        <form onSubmit={handleSubmit} className="space-y-6">

          {/* Customer details */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">

            <div className="mb-6">
              <h2 className="text-lg font-semibold text-white">
                1. Customer Information
              </h2>

              <p className="mt-1 text-xs text-slate-400">
                Enter the customer's basic information.
              </p>
            </div>

            <div className="grid gap-5 md:grid-cols-2">

              <div>
                <label className="mb-2 block text-sm text-slate-300">
                  Full Name
                </label>

                <div className="flex items-center rounded-lg border border-slate-700 bg-slate-950 px-3">
                  <UserRound className="h-5 w-5 text-slate-500" />

                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    placeholder="Customer name"
                    className="w-full bg-transparent px-3 py-3 text-sm text-white outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm text-slate-300">
                  Email Address
                </label>

                <div className="flex items-center rounded-lg border border-slate-700 bg-slate-950 px-3">
                  <Mail className="h-5 w-5 text-slate-500" />

                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    placeholder="customer@email.com"
                    className="w-full bg-transparent px-3 py-3 text-sm text-white outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm text-slate-300">
                  Phone Number
                </label>

                <div className="flex items-center rounded-lg border border-slate-700 bg-slate-950 px-3">
                  <Phone className="h-5 w-5 text-slate-500" />

                  <input
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    required
                    placeholder="Customer phone number"
                    className="w-full bg-transparent px-3 py-3 text-sm text-white outline-none"
                  />
                </div>
              </div>

            </div>
          </section>

          {/* Consent */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">

            <h2 className="text-lg font-semibold text-white">
              2. Voice Biometric Consent
            </h2>

            <div className="mt-4 rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-4">
              <div className="flex items-start gap-3">
                <LockKeyhole className="mt-1 h-5 w-5 shrink-0 text-cyan-400" />

                <div>
                  <p className="text-sm font-semibold text-cyan-300">
                    Voice data protection
                  </p>

                  <p className="mt-2 text-xs leading-6 text-slate-400">
                    The customer's voice recording may be processed to create
                    a speaker verification profile. Explain the purpose,
                    processing provider, retention period and deletion
                    procedure before obtaining consent.
                  </p>
                </div>
              </div>
            </div>

            <label className="mt-5 flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="mt-1 h-4 w-4 accent-cyan-400"
              />

              <span className="text-sm leading-6 text-slate-300">
                I confirm that the customer has been informed about voice
                biometric processing and has explicitly consented to
                enrollment and the stated data handling practices.
              </span>
            </label>

          </section>

          {/* Voice recording */}
          <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">

            <h2 className="text-lg font-semibold text-white">
              3. Voice Recording
            </h2>

            <p className="mt-1 text-xs text-slate-400">
              Record a clear voice sample in a quiet environment.
            </p>

            <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950 p-6 text-center">

              <div className={`mx-auto flex h-20 w-20 items-center justify-center rounded-full ${
                recording
                  ? 'bg-rose-500/10'
                  : 'bg-cyan-500/10'
              }`}>
                {recording ? (
                  <MicOff className="h-9 w-9 text-rose-400" />
                ) : (
                  <Mic className="h-9 w-9 text-cyan-400" />
                )}
              </div>

              <h3 className="mt-5 text-xl font-bold text-white">
                {recording ? 'Recording in progress' : 'Voice Recording'}
              </h3>

              <p className="mt-2 text-2xl font-mono text-cyan-400">
                {formatTime(duration)}
              </p>

              <p className="mt-2 text-xs text-slate-500">
                {recording
                  ? 'Speak clearly into your microphone.'
                  : 'Allow microphone access when your browser asks.'}
              </p>

              <div className="mt-6 flex flex-wrap justify-center gap-3">

                {!recording ? (
                  <button
                    type="button"
                    onClick={startRecording}
                    disabled={submitted}
                    className="flex items-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-400"
                  >
                    <Mic size={18} />
                    Start Recording
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={stopRecording}
                    className="flex items-center gap-2 rounded-lg bg-rose-500 px-5 py-3 font-semibold text-white hover:bg-rose-400"
                  >
                    <Square size={17} />
                    Stop Recording
                  </button>
                )}

                {audioUrl && !recording && (
                  <button
                    type="button"
                    onClick={deleteRecording}
                    className="flex items-center gap-2 rounded-lg border border-slate-700 px-5 py-3 text-slate-300 hover:bg-slate-800"
                  >
                    <Trash2 size={17} />
                    Delete / Re-record
                  </button>
                )}

              </div>

              {audioUrl && (
                <div className="mt-6 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
                  <div className="flex items-center justify-center gap-2 text-sm text-emerald-400">
                    <CheckCircle2 size={18} />
                    Recording captured locally
                  </div>

                  <audio
                    controls
                    src={audioUrl}
                    className="mt-4 w-full"
                  />

                  <p className="mt-2 text-xs text-slate-500">
                    Review the audio before submitting.
                  </p>
                </div>
              )}

            </div>
          </section>

          {/* Error message */}
          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-400">
              <AlertCircle className="h-5 w-5 shrink-0" />
              {error}
            </div>
          )}

          {/* Submit */}
          <div className="flex flex-col justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900 p-5 sm:flex-row sm:items-center">

            <div>
              <p className="font-medium text-white">
                Ready to submit?
              </p>

              <p className="mt-1 text-xs text-slate-400">
                Review the details, consent and voice recording first.
              </p>
            </div>

            <button
              type="submit"
              disabled={recording}
              className="rounded-lg bg-cyan-500 px-6 py-3 font-semibold text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Submit Enrollment
            </button>

          </div>

        </form>
      )}

    </div>
  )
}

export default Enrollment
