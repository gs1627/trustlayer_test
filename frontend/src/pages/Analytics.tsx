
import { useState } from 'react'
import {
  Activity,
  ShieldCheck,
  ShieldAlert,
  Fingerprint,
  Phone,
  TrendingUp,
  Clock,
  BarChart3,
} from 'lucide-react'

type Period = 'Today' | '7 Days' | '30 Days'


const chartData = {
  Today: [
    { day: '9 AM', calls: 8, suspicious: 2 },
    { day: '10 AM', calls: 14, suspicious: 3 },
    { day: '11 AM', calls: 18, suspicious: 4 },
    { day: '12 PM', calls: 12, suspicious: 1 },
    { day: '1 PM', calls: 16, suspicious: 2 },
    { day: '2 PM', calls: 10, suspicious: 0 },
    { day: '3 PM', calls: 8, suspicious: 0 },
  ],
  '7 Days': [
    { day: 'Mon', calls: 42, suspicious: 8 },
    { day: 'Tue', calls: 58, suspicious: 12 },
    { day: 'Wed', calls: 49, suspicious: 6 },
    { day: 'Thu', calls: 71, suspicious: 15 },
    { day: 'Fri', calls: 64, suspicious: 9 },
    { day: 'Sat', calls: 38, suspicious: 5 },
    { day: 'Sun', calls: 53, suspicious: 11 },
  ],
  '30 Days': [
    { day: 'Week 1', calls: 310, suspicious: 48 },
    { day: 'Week 2', calls: 365, suspicious: 62 },
    { day: 'Week 3', calls: 390, suspicious: 71 },
    { day: 'Week 4', calls: 417, suspicious: 60 },
  ],
}


const decisions = [
  { label: 'Normal Flow', value: 58, color: 'bg-emerald-400' },
  { label: 'Step-up Verification', value: 24, color: 'bg-cyan-400' },
  { label: 'Sensitive Action on Hold', value: 13, color: 'bg-red-400' },
  { label: 'Insufficient Evidence', value: 5, color: 'bg-amber-400' },
]

function Analytics() {
  const [period, setPeriod] = useState<Period>('7 Days')

  const periodMetrics = {
    Today: { calls: '86', suspicious: '12', verified: '68', held: '6' },
    '7 Days': { calls: '375', suspicious: '66', verified: '292', held: '31' },
    '30 Days': { calls: '1,482', suspicious: '241', verified: '1,126', held: '115' },
  }

  const metrics = periodMetrics[period]
  const currentChartData = chartData[period]

const maxCalls = Math.max(
  ...currentChartData.map((item) => item.calls)
)

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-cyan-400 text-sm font-medium">
            <BarChart3 size={17} />
            SECURITY PERFORMANCE
          </div>
          <h1 className="text-2xl font-bold text-white mt-2">Analytics</h1>
          <p className="text-slate-400 mt-1">
            Monitor caller trust, risk decisions and transaction security.
          </p>
        </div>

        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value as Period)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm text-white outline-none focus:border-cyan-500"
        >
          <option value="Today">Today</option>
          <option value="7 Days">Last 7 Days</option>
          <option value="30 Days">Last 30 Days</option>
        </select>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <div className="flex gap-3">
          <ShieldAlert size={20} className="text-amber-400 shrink-0" />
          <div>
            <p className="text-amber-300 text-sm font-semibold">
              Sample analytics — not live measurements
            </p>
            <p className="text-slate-400 text-sm mt-1">
              All figures and charts on this page are illustrative demo data.
              They do not represent actual Aletheia, Eidos, or Trust Engine
              performance.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center justify-between">
            <p className="text-slate-400 text-sm">Calls Monitored</p>
            <Phone size={19} className="text-cyan-400" />
          </div>
          <p className="text-3xl font-bold text-white mt-3">{metrics.calls}</p>
          <p className="text-xs text-slate-500 mt-2">{period} sample volume</p>
        </div>

        <div className="rounded-xl border border-red-500/20 bg-slate-900 p-5">
          <div className="flex items-center justify-between">
            <p className="text-slate-400 text-sm">Suspicious Calls</p>
            <ShieldAlert size={19} className="text-red-400" />
          </div>
          <p className="text-3xl font-bold text-red-400 mt-3">
            {metrics.suspicious}
          </p>
          <p className="text-xs text-slate-500 mt-2">Sample flagged calls</p>
        </div>

        <div className="rounded-xl border border-emerald-500/20 bg-slate-900 p-5">
          <div className="flex items-center justify-between">
            <p className="text-slate-400 text-sm">Verified Speakers</p>
            <Fingerprint size={19} className="text-emerald-400" />
          </div>
          <p className="text-3xl font-bold text-emerald-400 mt-3">
            {metrics.verified}
          </p>
          <p className="text-xs text-slate-500 mt-2">Sample verification records</p>
        </div>

        <div className="rounded-xl border border-amber-500/20 bg-slate-900 p-5">
          <div className="flex items-center justify-between">
            <p className="text-slate-400 text-sm">Actions on Hold</p>
            <ShieldCheck size={19} className="text-amber-400" />
          </div>
          <p className="text-3xl font-bold text-amber-400 mt-3">
            {metrics.held}
          </p>
          <p className="text-xs text-slate-500 mt-2">Sample held actions</p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 mb-1">
            <Activity size={19} className="text-cyan-400" />
            <h2 className="text-white font-semibold">Call Monitoring Trend</h2>
          </div>
          <p className="text-slate-500 text-xs mb-6">
            {period === 'Today'
  ? 'Illustrative calls and suspicious calls by hour'
  : period === '7 Days'
    ? 'Illustrative calls and suspicious calls by day'
    : 'Illustrative calls and suspicious calls by week'}
          </p>

          <div className="flex gap-5 text-xs text-slate-400 mb-5">
            <span className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm bg-cyan-400" />
              Total calls
            </span>
            <span className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm bg-red-400" />
              Suspicious
            </span>
          </div>

          <div className="space-y-4">
            {currentChartData.map((item) => (
              <div key={item.day} className="grid grid-cols-[65px_minmax(0,1fr)_35px] gap-3 items-center">
                <span className="text-xs text-slate-400 whitespace-nowrap">
  {item.day}
</span>
                <div className="space-y-1.5">
                  <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-cyan-400"
                      style={{ width: `${(item.calls / maxCalls) * 100}%` }}
                    />
                  </div>
                  <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-red-400"
                      style={{ width: `${(item.suspicious / maxCalls) * 100}%` }}
                    />
                  </div>
                </div>
                <span className="text-xs text-slate-400 text-right">
                  {item.calls}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck size={19} className="text-cyan-400" />
            <h2 className="text-white font-semibold">Trust Engine Decisions</h2>
          </div>
          <p className="text-slate-500 text-xs mb-6">
            Illustrative distribution of security outcomes
          </p>

          <div className="space-y-5">
            {decisions.map((decision) => (
              <div key={decision.label}>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm text-slate-300">
                    {decision.label}
                  </span>
                  <span className="text-sm text-white font-semibold">
                    {decision.value}%
                  </span>
                </div>
                <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${decision.color}`}
                    style={{ width: `${decision.value}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 rounded-lg border border-slate-800 bg-slate-950 p-3">
            <p className="text-xs text-slate-400 leading-5">
              These outcomes are separate policy decisions. A genuine voice
              does not automatically establish speaker identity or authorize
              a financial action.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 mb-4">
            <Fingerprint size={19} className="text-cyan-400" />
            <h2 className="text-white font-semibold">AI Service Overview</h2>
          </div>

          <div className="space-y-4">
            {[
              { name: 'Aletheia', role: 'Voice authenticity detection' },
              { name: 'Eidos', role: 'Speaker identity verification' },
              { name: 'Sarvam Saaras', role: 'Speech transcription' },
              { name: 'Conversation Intelligence', role: 'Social engineering indicators' },
            ].map((service) => (
              <div key={service.name} className="flex justify-between items-center gap-3">
                <div>
                  <p className="text-sm text-white font-medium">{service.name}</p>
                  <p className="text-xs text-slate-500 mt-1">{service.role}</p>
                </div>
                <span className="rounded-full border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-400">
                  Awaiting integration
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={19} className="text-cyan-400" />
            <h2 className="text-white font-semibold">Performance Metrics</h2>
          </div>

          <div className="space-y-4">
            {[
              { label: 'Voice analysis latency', value: 'Not measured' },
              { label: 'Speaker verification latency', value: 'Not measured' },
              { label: 'Deepfake detection precision', value: 'Not measured' },
              { label: 'False acceptance rate', value: 'Not measured' },
              { label: 'False rejection rate', value: 'Not measured' },
            ].map((metric) => (
              <div key={metric.label} className="flex justify-between items-center gap-3 border-b border-slate-800 pb-3">
                <span className="text-sm text-slate-400">{metric.label}</span>
                <span className="text-xs text-amber-400">{metric.value}</span>
              </div>
            ))}
          </div>

          <div className="mt-4 text-xs text-slate-500 leading-5">
            Accuracy and latency should only be reported after evaluation on
            a documented, consented test dataset.
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center gap-2 mb-2">
          <TrendingUp size={19} className="text-cyan-400" />
          <h2 className="text-white font-semibold">Evaluation Readiness</h2>
        </div>
        <p className="text-slate-400 text-sm leading-6">
          TRUSTLAYER will report detection precision, recall, false acceptance
          rate, false rejection rate, equal error rate, processing latency,
          and transaction hold outcomes once real model evaluations are
          available. No accuracy claims are made using demonstration data.
        </p>
      </div>
    </div>
  )
}

export default Analytics
