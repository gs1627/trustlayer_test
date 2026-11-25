
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ShieldCheck,
  User,
  Mail,
  Phone,
  Lock,
  Eye,
  EyeOff,
  ArrowRight,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react'

function Register() {
  const navigate = useNavigate()

const [form, setForm] = useState({
  firstName: '',
  lastName: '',
  email: '',
  phone: '',
  password: '',
  confirmPassword: '',
})

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const updateField = (field: string, value: string) => {
    setForm((previous) => ({ ...previous, [field]: value }))
    setError('')
  }

  const handleRegister = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError('')
    const registeredEmail = localStorage.getItem('trustlayerEmail')

if (
  registeredEmail &&
  registeredEmail.toLowerCase() === form.email.trim().toLowerCase()
) {
  setError('This email is already registered. Please sign in instead.')
  return
}

    if (
  !form.firstName.trim() ||
  !form.lastName.trim() ||
  !form.email.trim() ||
  !form.phone.trim()
) {
      setError('Please complete all required fields.')
      return
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      setError('Please enter a valid email address.')
      return
    }

    if (!/^\+?[0-9\s-]{10,15}$/.test(form.phone.trim())) {
      setError('Please enter a valid phone number.')
      return
    }

    if (form.password.length < 8) {
      setError('Password must contain at least 8 characters.')
      return
    }

    if (form.password !== form.confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    if (!consent) {
      setError('Please accept the consent statement to continue.')
      return
    }
    localStorage.setItem('trustlayerFirstName', form.firstName.trim())
localStorage.setItem('trustlayerLastName', form.lastName.trim())
localStorage.setItem('trustlayerEmail', form.email.trim())
localStorage.setItem('trustlayerPhone', form.phone.trim())
    // Frontend demonstration only. No account is created yet.
    setSuccess(true)
  }

  return (
    <div className="min-h-screen bg-[#020617] flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-6xl grid grid-cols-1 lg:grid-cols-2 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">

        {/* Left branding panel */}
        <div className="hidden lg:flex flex-col justify-between bg-gradient-to-br from-[#0f2742] to-[#020617] p-10">
          <div>
            <div className="flex items-center gap-3">
              <div className="rounded-xl bg-cyan-500/15 p-3">
                <ShieldCheck size={32} className="text-cyan-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">TRUSTLAYER</h1>
                <p className="text-sm text-slate-400">
                  Voice Security Platform
                </p>
              </div>
            </div>

            <div className="mt-20">
              <p className="text-cyan-400 text-sm font-semibold tracking-widest">
                CREATE YOUR ACCOUNT
              </p>
              <h2 className="text-4xl font-bold text-white leading-tight mt-4">
                Security starts with
                <span className="text-cyan-400"> verified identity.</span>
              </h2>
              <p className="text-slate-400 leading-7 mt-5">
                Join TRUSTLAYER to explore adaptive caller trust,
                voice authenticity verification and transaction security.
              </p>
            </div>
          </div>

          <div className="border-t border-slate-700 pt-5">
            <p className="text-sm text-slate-500">
              Don't just trust the voice. Verify the identity. Protect the action.
            </p>
          </div>
        </div>

        {/* Registration form */}
        <div className="p-6 sm:p-10 lg:p-12">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <ShieldCheck size={30} className="text-cyan-400" />
            <span className="text-xl font-bold text-white">TRUSTLAYER</span>
          </div>

          <div className="mb-7">
            <p className="text-cyan-400 text-sm font-semibold">
              ACCOUNT REGISTRATION
            </p>
            <h2 className="text-3xl font-bold text-white mt-2">
              Create Account
            </h2>
            <p className="text-slate-400 text-sm mt-2">
              Enter your details to get started.
            </p>
          </div>

          {success ? (
            <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-6 text-center">
              <CheckCircle2 size={44} className="mx-auto text-emerald-400" />
              <h3 className="text-xl font-semibold text-white mt-4">
                Form completed!
              </h3>
              <p className="text-slate-400 text-sm mt-2 leading-6">
                Your registration details passed frontend validation.
                No account has been created because backend registration
                is not connected yet.
              </p>
              <button
                onClick={() => navigate('/')}
                className="mt-6 w-full rounded-lg bg-cyan-500 py-3 font-semibold text-slate-950 hover:bg-cyan-400"
              >
                Return to Login
              </button>
            </div>
          ) : (
            <form onSubmit={handleRegister} className="space-y-4">

              {/* First Name */}
<div>
  <label className="text-sm text-slate-300 mb-2 block">
    First Name
  </label>
  <div className="relative">
    <User size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
    <input
      value={form.firstName}
      onChange={(e) => updateField('firstName', e.target.value)}
      placeholder="Enter your first name"
      className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-4 text-sm text-white outline-none focus:border-cyan-500"
    />
  </div>
</div>

{/* Last Name */}
<div>
  <label className="text-sm text-slate-300 mb-2 block">
    Last Name
  </label>
  <div className="relative">
    <User size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
    <input
      value={form.lastName}
      onChange={(e) => updateField('lastName', e.target.value)}
      placeholder="Enter your last name"
      className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-4 text-sm text-white outline-none focus:border-cyan-500"
    />
  </div>
</div>

              {/* Email */}
              <div>
                <label className="text-sm text-slate-300 mb-2 block">
                  Email Address
                </label>
                <div className="relative">
                  <Mail size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => updateField('email', e.target.value)}
                    placeholder="you@example.com"
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-4 text-sm text-white outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              {/* Phone */}
              <div>
                <label className="text-sm text-slate-300 mb-2 block">
                  Mobile Number
                </label>
                <div className="relative">
                  <Phone size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type="tel"
                    value={form.phone}
                    onChange={(e) => updateField('phone', e.target.value)}
                    placeholder="Enter mobile number"
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-4 text-sm text-white outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              {/* Password */}
              <div>
                <label className="text-sm text-slate-300 mb-2 block">
                  Password
                </label>
                <div className="relative">
                  <Lock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={form.password}
                    onChange={(e) => updateField('password', e.target.value)}
                    placeholder="Minimum 8 characters"
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-12 text-sm text-white outline-none focus:border-cyan-500"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                    aria-label="Toggle password visibility"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {/* Confirm password */}
              <div>
                <label className="text-sm text-slate-300 mb-2 block">
                  Confirm Password
                </label>
                <div className="relative">
                  <Lock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    value={form.confirmPassword}
                    onChange={(e) => updateField('confirmPassword', e.target.value)}
                    placeholder="Re-enter your password"
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-12 text-sm text-white outline-none focus:border-cyan-500"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                    aria-label="Toggle confirm password visibility"
                  >
                    {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {/* Consent */}
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="mt-1 accent-cyan-500"
                />
                <span className="text-xs text-slate-400 leading-5">
                  I understand that TRUSTLAYER processes account information
                  for platform security and that voice biometric enrollment,
                  if used, requires separate informed consent.
                </span>
              </label>

              {/* Error */}
              {error && (
                <div className="flex gap-2 rounded-lg border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">
                  <AlertCircle size={18} className="shrink-0" />
                  {error}
                </div>
              )}

              <button
                type="submit"
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-cyan-500 py-3.5 font-semibold text-slate-950 transition hover:bg-cyan-400"
              >
                Create Account
                <ArrowRight size={18} />
              </button>

              <p className="text-center text-sm text-slate-400 pt-2">
                Already have an account?{' '}
                <Link
                  to="/"
                  className="font-semibold text-cyan-400 hover:text-cyan-300"
                >
                  Sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

export default Register
