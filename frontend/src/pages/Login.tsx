
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { authService } from '../services/auth'
import { apiRequest } from '../services/api'
import {
  ShieldCheck,
  LockKeyhole,
  Mail,
  Eye,
  EyeOff,
} from 'lucide-react'

function Login() {
  const navigate = useNavigate()

  const [showPassword, setShowPassword] = useState(false)
  const [email, setEmail] = useState(
  localStorage.getItem('trustlayerEmail') || ''
)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    try {
      // Backend supports bearer-token/service authentication, not customer email/password accounts.
      if (password.trim()) {
        await authService.connect(password.trim())
      } else {
        await apiRequest('/auth/me')
        localStorage.setItem('trustlayerLoggedIn', 'true')
        localStorage.setItem('trustlayerSessionEmail', email.trim() || 'local_dev')
      }
      localStorage.setItem('trustlayerEmail', email.trim())
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Backend authentication failed.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-10 text-white">
      <div className="grid w-full max-w-5xl overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl md:grid-cols-2">

        {/* Left branding section */}
        <div className="hidden flex-col justify-between bg-gradient-to-br from-cyan-950 via-slate-900 to-slate-950 p-12 md:flex">
          <div>
            <div className="flex items-center gap-3">
              <div className="rounded-xl bg-cyan-500/15 p-3">
                <ShieldCheck className="h-8 w-8 text-cyan-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold tracking-wide">
                  TRUSTLAYER
                </h1>
                <p className="text-xs text-slate-400">
                  Voice Security Platform
                </p>
              </div>
            </div>

            <div className="mt-24">
              <h2 className="text-4xl font-bold leading-tight">
                Don't just trust the voice.
                <span className="text-cyan-400">
                  {' '}Verify the identity.
                </span>
              </h2>
              <p className="mt-6 leading-7 text-slate-400">
                Detect voice cloning impersonation, verify speaker identity
                and protect sensitive transactions with intelligent security.
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-4">
            <p className="text-sm text-cyan-300">
              Adaptive Caller Trust & Transaction Security
            </p>
          </div>
        </div>

        {/* Login form */}
        <div className="flex items-center justify-center p-7 sm:p-12">
          <div className="w-full max-w-md">

            <div className="mb-8 text-center md:text-left">
              <div className="mb-5 flex justify-center md:hidden">
                <ShieldCheck className="h-12 w-12 text-cyan-400" />
              </div>
              <h2 className="text-3xl font-bold">
                Welcome Back
              </h2>
              <p className="mt-2 text-sm text-slate-400">
                Sign in to your TRUSTLAYER security console.
              </p>
            </div>

            <form onSubmit={handleLogin} className="space-y-5">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">
                  Email Address
                </label>
                <div className="flex items-center rounded-lg border border-slate-700 bg-slate-950 px-3 focus-within:border-cyan-400">
                  <Mail className="h-5 w-5 text-slate-500" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="admin@trustlayer.com"
                    className="w-full bg-transparent px-3 py-3 text-sm text-white outline-none placeholder:text-slate-600"
                  />
                </div>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-300">
                  Backend access token (leave blank for local development)
                </label>
                <div className="flex items-center rounded-lg border border-slate-700 bg-slate-950 px-3 focus-within:border-cyan-400">
                  <LockKeyhole className="h-5 w-5 text-slate-500" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Paste BACKEND_ACCESS_TOKEN or JWT (optional in local dev)"
                    className="w-full bg-transparent px-3 py-3 text-sm text-white outline-none placeholder:text-slate-600"
                  />
                  <button
                    type="button"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-slate-500 hover:text-white"
                  >
                    {showPassword ? <EyeOff size={19} /> : <Eye size={19} />}
                  </button>
                </div>
              </div>

              {error && (
                <p role="alert" className="text-sm text-red-400">
                  {error}
                </p>
              )}

              <button
                type="submit"
                className="w-full rounded-lg bg-cyan-500 py-3 font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Sign In
              </button>
            </form>
            <div className="text-right">
  <button
    type="button"
    onClick={() =>
      alert('Customer password recovery is unavailable: this backend currently supports bearer-token authentication, not customer password accounts.')
    }
    className="text-sm text-cyan-400 hover:text-cyan-300"
  >
    Forgot Password?
  </button>
</div>

            <p className="mt-7 text-center text-sm text-slate-400">
              Don't have an account?{' '}
              <Link
                to="/register"
                className="font-semibold text-cyan-400 hover:text-cyan-300"
              >
                Create account
              </Link>
            </p>

            <p className="mt-8 text-center text-xs text-slate-600">
              TRUSTLAYER · Development Build
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Login
