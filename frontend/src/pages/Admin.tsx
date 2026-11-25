
import { useState } from 'react'
import {
  Settings,
  ShieldCheck,
  Server,
  Database,
  BrainCircuit,
  Fingerprint,
  Activity,
  Lock,
  RefreshCw,
  ClipboardList,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react'

function Admin() {
  const [maintenanceMode, setMaintenanceMode] = useState(false)
  const [strictVerification, setStrictVerification] = useState(true)
  const [auditLogging, setAuditLogging] = useState(true)

  const services = [
    {
      name: 'Aletheia',
      description: 'Voice authenticity detection',
      icon: BrainCircuit,
    },
    {
      name: 'Eidos',
      description: 'Speaker identity verification',
      icon: Fingerprint,
    },
    {
      name: 'Sarvam Saaras',
      description: 'Speech transcription',
      icon: Activity,
    },
    {
      name: 'PostgreSQL',
      description: 'Application database',
      icon: Database,
    },
    {
      name: 'Trust Engine',
      description: 'Evidence-based security decisions',
      icon: ShieldCheck,
    },
    {
      name: 'API Server',
      description: 'Backend application service',
      icon: Server,
    },
  ]

  const auditEvents = [
    {
      event: 'Admin dashboard accessed',
      user: 'Security Admin',
      time: '10:45 AM',
      type: 'Information',
    },
    {
      event: 'Sensitive transaction placed on hold',
      user: 'Security Team',
      time: '10:38 AM',
      type: 'Warning',
    },
    {
      event: 'Customer enrollment submitted',
      user: 'Demo Customer',
      time: '10:25 AM',
      type: 'Information',
    },
    {
      event: 'Speaker verification requested',
      user: 'Security Team',
      time: '10:12 AM',
      type: 'Information',
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 text-cyan-400 text-sm font-medium">
          <Settings size={17} />
          PLATFORM MANAGEMENT
        </div>
        <h1 className="text-2xl font-bold text-white mt-2">
          Admin Console
        </h1>
        <p className="text-slate-400 mt-1">
          Manage security configuration, monitor services and review audit activity.
        </p>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <div className="flex gap-3">
          <AlertTriangle size={20} className="text-amber-400 shrink-0" />
          <div>
            <p className="text-amber-300 text-sm font-semibold">
              Frontend demonstration mode
            </p>
            <p className="text-slate-400 text-sm mt-1">
              Service states and audit entries are sample data. Settings below
              change local interface state only. They do not change backend
              security policies or production services.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-slate-400 text-sm">Platform</p>
          <p className="text-xl font-semibold text-white mt-2">
            Development
          </p>
          <p className="text-xs text-cyan-400 mt-2">Demo environment</p>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-slate-400 text-sm">AI Integrations</p>
          <p className="text-xl font-semibold text-white mt-2">0 Connected</p>
          <p className="text-xs text-amber-400 mt-2">Awaiting backend integration</p>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-slate-400 text-sm">Audit Logging</p>
          <p className="text-xl font-semibold text-white mt-2">
            {auditLogging ? 'Enabled in demo' : 'Disabled in demo'}
          </p>
          <p className="text-xs text-slate-500 mt-2">Local UI setting</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center gap-2 mb-5">
          <Server size={20} className="text-cyan-400" />
          <div>
            <h2 className="text-white font-semibold">Service Monitoring</h2>
            <p className="text-slate-500 text-xs mt-1">
              Expected platform components
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {services.map((service) => {
            const Icon = service.icon

            return (
              <div
                key={service.name}
                className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950 p-4"
              >
                <div className="flex items-center gap-3">
                  <div className="rounded-lg bg-cyan-500/10 p-2">
                    <Icon size={20} className="text-cyan-400" />
                  </div>
                  <div>
                    <p className="text-sm text-white font-medium">
                      {service.name}
                    </p>
                    <p className="text-xs text-slate-500 mt-1">
                      {service.description}
                    </p>
                  </div>
                </div>

                <span className="whitespace-nowrap rounded-full border border-slate-700 px-2.5 py-1 text-xs text-slate-400">
                  Not connected
                </span>
              </div>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 mb-5">
            <Lock size={20} className="text-cyan-400" />
            <h2 className="text-white font-semibold">Security Configuration</h2>
          </div>

          <div className="space-y-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-white text-sm font-medium">
                  Maintenance Mode
                </p>
                <p className="text-slate-500 text-xs mt-1">
                  Simulate restricted platform access
                </p>
              </div>
              <button
                onClick={() => setMaintenanceMode(!maintenanceMode)}
                className={`relative h-6 w-11 rounded-full transition ${
                  maintenanceMode ? 'bg-cyan-500' : 'bg-slate-700'
                }`}
                aria-label="Toggle maintenance mode demo"
                aria-pressed={maintenanceMode}
              >
                <span
                  className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${
                    maintenanceMode ? 'left-6' : 'left-1'
                  }`}
                />
              </button>
            </div>

            <div className="border-t border-slate-800" />

            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-white text-sm font-medium">
                  Strict Verification
                </p>
                <p className="text-slate-500 text-xs mt-1">
                  Require independent verification for sensitive actions
                </p>
              </div>
              <button
                onClick={() => setStrictVerification(!strictVerification)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition ${
                  strictVerification ? 'bg-cyan-500' : 'bg-slate-700'
                }`}
                aria-label="Toggle strict verification demo"
                aria-pressed={strictVerification}
              >
                <span
                  className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${
                    strictVerification ? 'left-6' : 'left-1'
                  }`}
                />
              </button>
            </div>

            <div className="border-t border-slate-800" />

            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-white text-sm font-medium">
                  Audit Logging
                </p>
                <p className="text-slate-500 text-xs mt-1">
                  Simulate audit logging preference
                </p>
              </div>
              <button
                onClick={() => setAuditLogging(!auditLogging)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition ${
                  auditLogging ? 'bg-cyan-500' : 'bg-slate-700'
                }`}
                aria-label="Toggle audit logging demo"
                aria-pressed={auditLogging}
              >
                <span
                  className={`absolute top-1 h-4 w-4 rounded-full bg-white transition ${
                    auditLogging ? 'left-6' : 'left-1'
                  }`}
                />
              </button>
            </div>
          </div>

          {maintenanceMode && (
            <div className="mt-5 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-300">
              Maintenance mode is enabled in this demo interface only.
            </div>
          )}

          <div className="mt-5 rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs text-slate-500">
            Production security policies must be enforced and validated by
            the backend. A frontend toggle must never weaken transaction
            authorization controls.
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
          <div className="flex items-center gap-2 mb-5">
            <ClipboardList size={20} className="text-cyan-400" />
            <h2 className="text-white font-semibold">Recent Audit Activity</h2>
          </div>

          <div className="space-y-4">
            {auditEvents.map((event, index) => (
              <div
                key={index}
                className="flex gap-3 border-b border-slate-800 pb-4 last:border-0 last:pb-0"
              >
                <div className="mt-1">
                  {event.type === 'Warning' ? (
                    <AlertTriangle size={17} className="text-amber-400" />
                  ) : (
                    <CheckCircle2 size={17} className="text-cyan-400" />
                  )}
                </div>
                <div className="flex-1">
                  <p className="text-sm text-white">{event.event}</p>
                  <p className="text-xs text-slate-500 mt-1">
                    {event.user}
                  </p>
                  <p className="text-xs text-slate-600 mt-1">
                    {event.time}
                  </p>
                </div>
                <span
                  className={`text-xs ${
                    event.type === 'Warning'
                      ? 'text-amber-400'
                      : 'text-slate-500'
                  }`}
                >
                  {event.type}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <div className="flex items-center gap-2 mb-3">
          <RefreshCw size={19} className="text-cyan-400" />
          <h2 className="text-white font-semibold">Integration Readiness</h2>
        </div>
        <p className="text-slate-400 text-sm leading-6">
          The backend integration should provide service health checks,
          role-based access control, immutable audit events, configuration
          validation, and signed webhook verification. Administrative actions
          must be authenticated, authorized, and recorded on the server.
        </p>
      </div>
    </div>
  )
}

export default Admin
