

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  UserRound,
  Mail,
  Phone,
  ShieldCheck,
  Fingerprint,
  Lock,
  Edit3,
  Save,
  ArrowLeft,
  Eye,
  EyeOff,
} from 'lucide-react'

function Profile() {
  const navigate = useNavigate()

  const [firstName, setFirstName] = useState(
    localStorage.getItem('trustlayerFirstName') || 'Admin'
  )
  const [lastName, setLastName] = useState(
    localStorage.getItem('trustlayerLastName') || ''
  )
  const [email, setEmail] = useState(
    localStorage.getItem('trustlayerEmail') || ''
  )
  const [phone, setPhone] = useState(
    localStorage.getItem('trustlayerPhone') || ''
  )

  const [editing, setEditing] = useState(false)
  const [message, setMessage] = useState('')

  // Change password states
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPasswords, setShowPasswords] = useState(false)
  const [passwordMessage, setPasswordMessage] = useState('')
  const [passwordError, setPasswordError] = useState('')

  const initials =
    `${firstName.trim().charAt(0)}${lastName.trim().charAt(0) || (lastName ? '' : firstName.trim().charAt(1))}`.toUpperCase()

  const fullName = `${firstName} ${lastName}`.trim()

  const handleSave = () => {
    if (!firstName.trim() || !lastName.trim()) {
      setMessage('Please enter both first name and last name.')
      return
    }

    localStorage.setItem('trustlayerFirstName', firstName.trim())
    localStorage.setItem('trustlayerLastName', lastName.trim())

    window.dispatchEvent(
      new CustomEvent('trustlayer-profile-updated', {
        detail: {
          firstName: firstName.trim(),
          lastName: lastName.trim(),
        },
      })
    )

    localStorage.setItem('trustlayerEmail', email.trim())
    localStorage.setItem('trustlayerPhone', phone.trim())

    setEditing(false)
    setMessage('Profile updated successfully in this browser.')
  }

  const handlePasswordChange = () => {
    setPasswordMessage('')
    setPasswordError('')

    if (!currentPassword || !newPassword || !confirmPassword) {
      setPasswordError('Please fill in all password fields.')
      return
    }

    if (newPassword.length < 8) {
      setPasswordError('New password must be at least 8 characters.')
      return
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match.')
      return
    }

    if (currentPassword === newPassword) {
      setPasswordError(
        'New password must differ from current password.'
      )
      return
    }

    setPasswordMessage(
      'Demo validation successful! Real password changes require backend authentication.'
    )

    setCurrentPassword('')
    setNewPassword('')
    setConfirmPassword('')
  }

  return (
    <div className="space-y-6">

      {/* Heading */}
      <div>
        <div className="flex items-center gap-2 text-cyan-400 text-sm font-medium">
          <UserRound size={18} />
          ACCOUNT MANAGEMENT
        </div>

        <h1 className="mt-2 text-2xl font-bold text-white">
          My Profile
        </h1>

        <p className="mt-1 text-slate-400">
          View and manage your TRUSTLAYER account information.
        </p>
      </div>

      {/* Demo notice */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
        <p className="text-sm font-semibold text-amber-300">
          Frontend demonstration mode
        </p>
        <p className="mt-1 text-sm text-slate-400">
          Profile information is stored locally in this browser.
          It is not yet connected to backend account management.
        </p>
      </div>

      {/* Profile header */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center">

          <div className="flex h-24 w-24 shrink-0 items-center justify-center rounded-full border-4 border-cyan-500/20 bg-cyan-500/10 text-3xl font-bold text-cyan-400">
            {initials || 'AD'}
          </div>

          <div className="flex-1">
            <h2 className="text-2xl font-bold text-white">
              {fullName}
            </h2>

            <p className="mt-1 text-sm text-slate-400">
              TRUSTLAYER Security Team
            </p>

            <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-400">
              <ShieldCheck size={14} />
              Demo account
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              setEditing(!editing)
              setMessage('')
            }}
            className="flex items-center justify-center gap-2 rounded-lg border border-slate-700 px-4 py-2.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            <Edit3 size={16} />
            {editing ? 'Cancel editing' : 'Edit Profile'}
          </button>
        </div>
      </div>

      {/* Personal information */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h3 className="mb-6 text-lg font-semibold text-white">
          Personal Information
        </h3>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              First Name
            </label>
            <div className="relative">
              <UserRound size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={firstName}
                disabled={!editing}
                onChange={(e) => setFirstName(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-3 text-sm text-white outline-none focus:border-cyan-500 disabled:opacity-70"
              />
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              Last Name
            </label>
            <div className="relative">
              <UserRound size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={lastName}
                disabled={!editing}
                onChange={(e) => setLastName(e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-3 text-sm text-white outline-none focus:border-cyan-500 disabled:opacity-70"
              />
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              Email Address
            </label>
            <div className="relative">
              <Mail size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="email"
                value={email}
                disabled={!editing}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-3 text-sm text-white outline-none focus:border-cyan-500 disabled:opacity-70"
              />
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              Mobile Number
            </label>
            <div className="relative">
              <Phone size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                type="tel"
                value={phone}
                disabled={!editing}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="Enter your mobile number"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 py-3 pl-10 pr-3 text-sm text-white outline-none focus:border-cyan-500 disabled:opacity-70"
              />
            </div>
          </div>
        </div>

        {message && (
          <p className="mt-4 text-sm text-cyan-400">
            {message}
          </p>
        )}

        {editing && (
          <button
            type="button"
            onClick={handleSave}
            className="mt-6 flex items-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-400"
          >
            <Save size={17} />
            Save Changes
          </button>
        )}
      </div>

      {/* Security information */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <h3 className="mb-5 text-lg font-semibold text-white">
          Security Overview
        </h3>

        <div className="space-y-4">

          <div className="flex items-center gap-3 rounded-lg bg-slate-950 p-4">
            <div className="rounded-lg bg-cyan-500/10 p-3">
              <Fingerprint className="text-cyan-400" size={21} />
            </div>
            <div>
              <p className="text-sm font-medium text-white">
                Voice Biometric Enrollment
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Check enrollment status in the Enrollment module.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-lg bg-slate-950 p-4">
            <div className="rounded-lg bg-emerald-500/10 p-3">
              <ShieldCheck className="text-emerald-400" size={21} />
            </div>
            <div>
              <p className="text-sm font-medium text-white">
                Account Status
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Frontend demo account — backend verification pending.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 rounded-lg bg-slate-950 p-4">
            <div className="rounded-lg bg-amber-500/10 p-3">
              <Lock className="text-amber-400" size={21} />
            </div>
            <div>
              <p className="text-sm font-medium text-white">
                Authentication
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Secure backend authentication is not connected yet.
              </p>
            </div>
          </div>

        </div>
      </div>

      {/* Change Password */}
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-5 flex items-center gap-3">
          <div className="rounded-lg bg-cyan-500/10 p-3">
            <Lock className="text-cyan-400" size={21} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">
              Change Password
            </h3>
            <p className="text-xs text-slate-500">
              Update your account password
            </p>
          </div>
        </div>

        <div className="space-y-4">

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              Current Password
            </label>
            <div className="relative">
              <input
                type={showPasswords ? 'text' : 'password'}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Enter current password"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 pr-12 text-sm text-white outline-none focus:border-cyan-500"
              />
              <button
                type="button"
                onClick={() => setShowPasswords(!showPasswords)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-cyan-400"
                aria-label={showPasswords ? 'Hide passwords' : 'Show passwords'}
              >
                {showPasswords ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              New Password
            </label>
            <input
              type={showPasswords ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Enter new password"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none focus:border-cyan-500"
            />
            <p className="mt-1 text-xs text-slate-500">
              Password must contain at least 8 characters.
            </p>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-400">
              Confirm New Password
            </label>
            <input
              type={showPasswords ? 'text' : 'password'}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none focus:border-cyan-500"
            />
          </div>

        </div>

        {passwordError && (
          <p className="mt-4 text-sm text-red-400">
            {passwordError}
          </p>
        )}

        {passwordMessage && (
          <p className="mt-4 text-sm text-emerald-400">
            {passwordMessage}
          </p>
        )}

        <button
          type="button"
          onClick={handlePasswordChange}
          className="mt-6 flex items-center gap-2 rounded-lg bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-400"
        >
          <Lock size={17} />
          Update Password
        </button>

        <p className="mt-3 text-xs text-slate-500">
          Demo only: this form validates the fields but does not change or store a real password. Backend authentication is required for actual password updates.
        </p>
      </div>

      {/* Back to Dashboard */}
      <button
        type="button"
        onClick={() => navigate('/dashboard')}
        className="flex items-center gap-2 text-sm text-slate-400 hover:text-cyan-400"
      >
        <ArrowLeft size={17} />
        Back to Dashboard
      </button>

    </div>
  )
}

export default Profile
