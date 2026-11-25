
import { useState } from 'react'
import {
  ShieldCheck,
  ShieldAlert,
  Smartphone,
  Lock,
  CheckCircle2,
  Clock,
  ArrowRight,
  RefreshCw,
} from 'lucide-react'

type ApprovalStatus = 'waiting' | 'sent' | 'approved' | 'rejected'

function CustomerApproval() {
  const [status, setStatus] = useState<ApprovalStatus>('waiting')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [showDemoCode, setShowDemoCode] = useState(false)

  const demoCode = '482916'

  const sendChallenge = () => {
    setStatus('sent')
    setCode('')
    setError('')
    setShowDemoCode(true)
  }

  const verifyCode = () => {
    if (code.trim().length !== 6) {
      setError('Enter the six-digit verification code.')
      return
    }

    if (code.trim() === demoCode) {
      setStatus('approved')
      setError('')
    } else {
      setError('Incorrect demo code. Please try again.')
    }
  }

  const resetDemo = () => {
    setStatus('waiting')
    setCode('')
    setError('')
    setShowDemoCode(false)
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center gap-2 text-cyan-400 text-sm font-medium">
          <ShieldCheck size={17} />
          INDEPENDENT CUSTOMER VERIFICATION
        </div>
        <h1 className="text-2xl font-bold text-white mt-2">
          Customer Approval
        </h1>
        <p className="text-slate-400 mt-1">
          Verify sensitive transactions through a separate trusted channel.
        </p>
      </div>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <div className="flex gap-3">
          <ShieldAlert size={20} className="text-amber-400 shrink-0" />
          <div>
            <p className="text-amber-300 text-sm font-semibold">
              Frontend demonstration mode
            </p>
            <p className="text-slate-400 text-sm mt-1">
              This page simulates a verification challenge. No SMS, banking
              service, or real transaction is involved. The demo code is
              displayed on this page for testing.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900 p-6">
          <div className="flex items-center justify-between gap-3 mb-6">
            <div>
              <h2 className="text-white font-semibold text-lg">
                Transaction Verification
              </h2>
              <p className="text-slate-500 text-xs mt-1">
                Sample transaction awaiting customer confirmation
              </p>
            </div>
            <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-xs text-amber-400">
              Demo transaction
            </span>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-950 p-5 space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-slate-500 text-sm">Transaction ID</span>
              <span className="text-cyan-400 text-sm font-medium">
                TXN-2026-002
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-slate-500 text-sm">Customer</span>
              <span className="text-white text-sm">Priya Nair</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-slate-500 text-sm">Amount</span>
              <span className="text-white text-lg font-bold">₹85,000</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-slate-500 text-sm">Beneficiary</span>
              <span className="text-white text-sm">Unknown Beneficiary</span>
            </div>
            <div className="border-t border-slate-800 pt-4 flex justify-between items-center">
              <span className="text-slate-500 text-sm">Verification status</span>
              <span className="text-amber-400 text-sm font-medium">
                {status === 'waiting' && 'Awaiting challenge'}
                {status === 'sent' && 'Challenge issued'}
                {status === 'approved' && 'Demo verified'}
                {status === 'rejected' && 'Rejected'}
              </span>
            </div>
          </div>

          <div className="mt-6 space-y-4">
            {status === 'waiting' && (
              <div className="rounded-xl border border-slate-800 p-5 text-center">
                <Smartphone size={36} className="mx-auto text-cyan-400" />
                <h3 className="text-white font-semibold mt-3">
                  Send independent verification challenge
                </h3>
                <p className="text-slate-400 text-sm mt-2">
                  In the real platform, the customer would receive a
                  transaction-specific challenge through a separately
                  authenticated channel.
                </p>
                <button
                  onClick={sendChallenge}
                  className="mt-5 inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-400"
                >
                  Send Demo Challenge
                  <ArrowRight size={17} />
                </button>
              </div>
            )}

            {status === 'sent' && (
              <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-5 space-y-4">
                <div className="flex items-center gap-2">
                  <Lock size={20} className="text-cyan-400" />
                  <h3 className="text-white font-semibold">
                    Verify customer challenge
                  </h3>
                </div>

                <p className="text-slate-400 text-sm">
                  Enter the six-digit demo code to simulate independent
                  customer verification.
                </p>

                {showDemoCode && (
                  <div className="rounded-lg border border-cyan-500/20 bg-slate-950 p-3">
                    <p className="text-xs text-slate-500">
                      Demo code — not a real OTP
                    </p>
                    <p className="text-2xl tracking-[0.3em] font-bold text-cyan-400 mt-1">
                      {demoCode}
                    </p>
                  </div>
                )}

                <input
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value.replace(/\D/g, '').slice(0, 6))
                    setError('')
                  }}
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="Enter 6-digit code"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-center text-xl tracking-[0.4em] text-white outline-none focus:border-cyan-500"
                />

                {error && (
                  <p className="text-sm text-red-400">{error}</p>
                )}

                <button
                  onClick={verifyCode}
                  className="w-full rounded-lg bg-cyan-500 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-400"
                >
                  Verify Demo Code
                </button>
              </div>
            )}

            {status === 'approved' && (
              <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-5 text-center">
                <CheckCircle2 size={42} className="mx-auto text-emerald-400" />
                <h3 className="text-emerald-400 font-semibold text-lg mt-3">
                  Demo Verification Successful
                </h3>
                <p className="text-slate-400 text-sm mt-2">
                  The demo code matched. This does not authorize or release
                  the real transaction.
                </p>
                <div className="mt-4 rounded-lg bg-slate-950 p-3 text-sm text-slate-300">
                  Customer challenge: Matched
                  <br />
                  Transaction authorization: Not performed
                </div>
              </div>
            )}

            {status === 'rejected' && (
              <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-5">
                <p className="text-red-400 font-semibold">
                  Customer rejected the challenge
                </p>
                <p className="text-slate-400 text-sm mt-2">
                  The transaction should remain on hold pending investigation.
                </p>
              </div>
            )}

            <button
              onClick={resetDemo}
              className="flex items-center gap-2 text-sm text-slate-400 hover:text-white"
            >
              <RefreshCw size={15} />
              Reset demonstration
            </button>
          </div>
        </div>

        <div className="space-y-5">
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <h3 className="text-white font-semibold mb-4">
              Verification Process
            </h3>

            <div className="space-y-5">
              <div className="flex gap-3">
                <div className="rounded-full bg-cyan-500/10 p-2 h-fit">
                  <Smartphone size={17} className="text-cyan-400" />
                </div>
                <div>
                  <p className="text-white text-sm font-medium">
                    1. Challenge issued
                  </p>
                  <p className="text-slate-500 text-xs mt-1">
                    Send a separate verification request.
                  </p>
                </div>
              </div>

              <div className="flex gap-3">
                <div className="rounded-full bg-cyan-500/10 p-2 h-fit">
                  <Lock size={17} className="text-cyan-400" />
                </div>
                <div>
                  <p className="text-white text-sm font-medium">
                    2. Customer verifies
                  </p>
                  <p className="text-slate-500 text-xs mt-1">
                    Confirm the exact transaction details.
                  </p>
                </div>
              </div>

              <div className="flex gap-3">
                <div className="rounded-full bg-emerald-500/10 p-2 h-fit">
                  <ShieldCheck size={17} className="text-emerald-400" />
                </div>
                <div>
                  <p className="text-white text-sm font-medium">
                    3. Evidence recorded
                  </p>
                  <p className="text-slate-500 text-xs mt-1">
                    Record the result for the Trust Engine.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Clock size={18} className="text-amber-400" />
              <h3 className="text-white font-semibold">Security reminder</h3>
            </div>
            <p className="text-slate-400 text-sm leading-6">
              A successful challenge is only one piece of evidence. The
              challenge should be short-lived, single-use, and bound to the
              exact amount and beneficiary. Voice evidence alone must never
              approve a sensitive transaction.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CustomerApproval
