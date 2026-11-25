
import { useEffect, useState } from 'react'
import { apiRequest } from '../services/api'
import { callsService } from '../services/calls'
import {
  Phone,
  ShieldAlert,
  ShieldCheck,
  LockKeyhole,
  Activity,
  Clock,
  Radio,
  ArrowUpRight,
  BrainCircuit,
  Mic,
  Fingerprint,
  AlertTriangle,
} from 'lucide-react'

const stats = [
  {
    title: 'Calls Monitored',
    value: '120',
    change: '+12.5%',
    description: 'Total demo calls',
    icon: Phone,
    color: 'text-cyan-400',
    bg: 'bg-cyan-500/10',
  },
  {
    title: 'Suspicious Calls',
    value: '18',
    change: '+4.2%',
    description: 'Flagged for review',
    icon: ShieldAlert,
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
  },
  {
    title: 'Verified Speakers',
    value: '95',
    change: '+8.1%',
    description: 'Identity checks passed',
    icon: ShieldCheck,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
  },
  {
    title: 'Transactions Held',
    value: '7',
    change: 'Requires review',
    description: 'Awaiting independent approval',
    icon: LockKeyhole,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
  },
]

const services = [
  {
    name: 'Voice Authenticity',
    provider: 'DetectifAI Aletheia',
    icon: Mic,
    status: 'Integration pending',
    color: 'text-amber-400',
  },
  {
    name: 'Speaker Verification',
    provider: 'DetectifAI Eidos',
    icon: Fingerprint,
    status: 'Integration pending',
    color: 'text-amber-400',
  },
  {
    name: 'Speech Transcription',
    provider: 'Sarvam Saaras',
    icon: Activity,
    status: 'Integration pending',
    color: 'text-amber-400',
  },
  {
    name: 'Conversation Intelligence',
    provider: 'Gemini / Hugging Face',
    icon: BrainCircuit,
    status: 'Integration pending',
    color: 'text-amber-400',
  },
]

const activities = [
  {
    id: 'CALL-001',
    title: 'Suspicious call detected',
    detail: 'Voice authenticity requires review',
    time: '2 minutes ago',
    status: 'Review',
    color: 'text-rose-400',
  },
  {
    id: 'CALL-002',
    title: 'Speaker verification completed',
    detail: 'Identity check passed',
    time: '8 minutes ago',
    status: 'Verified',
    color: 'text-emerald-400',
  },
  {
    id: 'TXN-003',
    title: 'Transaction placed on hold',
    detail: 'Independent approval required',
    time: '15 minutes ago',
    status: 'On hold',
    color: 'text-amber-400',
  },
  {
    id: 'CALL-004',
    title: 'New call session created',
    detail: 'Waiting for audio analysis',
    time: '25 minutes ago',
    status: 'Pending',
    color: 'text-cyan-400',
  },
]

function Dashboard() {
  const [backend, setBackend] = useState('Checking backend...')
  const [sessionCount, setSessionCount] = useState<number | null>(null)
  useEffect(() => {
    let active = true
    Promise.all([apiRequest<{ status: string; database: string }>('/health'), callsService.list(1, 0)])
      .then(([health, sessions]) => { if (active) { setBackend(`${health.status} · database ${health.database}`); setSessionCount(sessions.total) } })
      .catch((err: unknown) => { if (active) setBackend(err instanceof Error ? err.message : 'Backend unavailable') })
    return () => { active = false }
  }, [])
  return (
    <div className="space-y-8">

      {/* Welcome section */}
      <section className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Security Overview
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Monitor voice authenticity, speaker identity and transaction safety.
          </p>
        </div>

        <div className="flex items-center gap-2 self-start rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-4 py-2">
          <span className="h-2 w-2 rounded-full bg-cyan-400" />
          <span className="text-sm text-cyan-300">
            Backend: {backend}
          </span>
        </div>
      </section>

      {/* Demo data notice */}
      <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
        <div>
          <p className="text-sm font-semibold text-amber-300">
            Demonstration data
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-400">
            The four headline statistics and activity below remain illustrative sample data. Backend connectivity and the session count are queried live from FastAPI.
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">Backend call sessions recorded: <span className="font-semibold text-cyan-300">{sessionCount === null ? 'Unavailable' : sessionCount}</span></div>

      {/* Statistics cards */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((stat) => {
          const Icon = stat.icon

          return (
            <div
              key={stat.title}
              className="rounded-xl border border-slate-800 bg-slate-900 p-5 transition hover:border-slate-600"
            >
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-400">
                  {stat.title}
                </p>

                <div className={`rounded-lg p-3 ${stat.bg}`}>
                  <Icon className={`h-5 w-5 ${stat.color}`} />
                </div>
              </div>

              <h2 className="mt-4 text-3xl font-bold text-white">
                {stat.value}
              </h2>

              <p className="mt-2 text-xs text-slate-500">
                {stat.description}
              </p>

              <div className={`mt-4 flex items-center gap-1 text-xs ${stat.color}`}>
                <ArrowUpRight size={14} />
                {stat.change}
              </div>
            </div>
          )
        })}
      </section>

      {/* AI services and live monitoring */}
      <section className="grid grid-cols-1 gap-5 xl:grid-cols-3">

        {/* AI services */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6 xl:col-span-2">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">
                AI Security Services
              </h2>
              <p className="mt-1 text-xs text-slate-400">
                Connected intelligence providers
              </p>
            </div>

            <BrainCircuit className="h-6 w-6 text-cyan-400" />
          </div>

          <div className="mt-6 space-y-5">
            {services.map((service) => {
              const Icon = service.icon

              return (
                <div
                  key={service.name}
                  className="flex flex-col justify-between gap-3 border-b border-slate-800 pb-4 last:border-0 sm:flex-row sm:items-center"
                >
                  <div className="flex items-center gap-3">
                    <div className="rounded-lg bg-slate-800 p-3">
                      <Icon className="h-5 w-5 text-cyan-400" />
                    </div>

                    <div>
                      <p className="text-sm font-medium text-white">
                        {service.name}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {service.provider}
                      </p>
                    </div>
                  </div>

                  <span className={`text-xs font-medium ${service.color}`}>
                    {service.status}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        {/* Monitoring status */}
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
          <div className="flex items-center gap-2">
            <Radio className="h-5 w-5 text-cyan-400" />
            <h2 className="text-lg font-semibold text-white">
              Live Monitoring
            </h2>
          </div>

          <div className="mt-6 rounded-xl border border-slate-800 bg-slate-950 p-5 text-center">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-cyan-500/10">
              <Activity className="h-8 w-8 text-cyan-400" />
            </div>

            <h3 className="mt-4 font-semibold text-white">
              Monitoring interface ready
            </h3>

            <p className="mt-2 text-xs leading-5 text-slate-400">
              Live call analysis will be available after backend integration.
            </p>
          </div>

          <div className="mt-5 flex items-center justify-between border-b border-slate-800 pb-3">
            <span className="text-sm text-slate-400">
              Backend connection
            </span>
            <span className="text-xs text-amber-400">
              Not connected
            </span>
          </div>

          <div className="mt-3 flex items-center justify-between">
            <span className="text-sm text-slate-400">
              Active sessions
            </span>
            <span className="text-sm font-semibold text-white">
              0
            </span>
          </div>
        </div>
      </section>

      {/* Recent activity */}
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Recent Security Activity
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              Sample events for interface development
            </p>
          </div>

          <Clock className="h-5 w-5 text-slate-400" />
        </div>

        <div className="mt-6 space-y-4">
          {activities.map((activity) => (
            <div
              key={activity.id}
              className="flex flex-col justify-between gap-3 border-b border-slate-800 pb-4 last:border-0 sm:flex-row sm:items-center"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-cyan-400">
                    {activity.id}
                  </span>
                  <span className="text-sm font-medium text-white">
                    {activity.title}
                  </span>
                </div>

                <p className="mt-2 text-xs text-slate-400">
                  {activity.detail}
                </p>

                <p className="mt-1 text-xs text-slate-600">
                  {activity.time}
                </p>
              </div>

              <span className={`text-xs font-semibold ${activity.color}`}>
                {activity.status}
              </span>
            </div>
          ))}
        </div>
      </section>

    </div>
  )
}

export default Dashboard
