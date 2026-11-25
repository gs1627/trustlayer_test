import { authService } from '../../services/auth'

import { useState, useEffect } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import {
  ShieldCheck,
  LayoutDashboard,
  UserRound,
  Radio,
  ScanSearch,
  BrainCircuit,
  ArrowLeftRight,
  BarChart3,
  Settings,
  Bell,
  Search,
  Menu,
  X,
  LogOut,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-react'

const navigation = [
  { name: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
  { name: 'Enrollment', path: '/enrollment', icon: UserRound },
  { name: 'Live Monitoring', path: '/monitoring', icon: Radio },
  { name: 'Forensics', path: '/forensics', icon: ScanSearch },
  { name: 'Conversation AI', path: '/intelligence', icon: BrainCircuit },
  { name: 'Transactions', path: '/transactions', icon: ArrowLeftRight },
  { name: 'Customer Approval', path: '/approval', icon: ShieldCheck },
  { name: 'Analytics', path: '/analytics', icon: BarChart3 },
  { name: 'Admin', path: '/admin', icon: Settings },
]

function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [notificationOpen, setNotificationOpen] = useState(false)
  const [searchText, setSearchText] = useState('')

  const [firstName, setFirstName] = useState(
    localStorage.getItem('trustlayerFirstName') || 'Admin'
  )

  const [lastName, setLastName] = useState(
    localStorage.getItem('trustlayerLastName') || ''
  )

  const updateProfileName = (first: string, last: string) => {
    setFirstName(first)
    setLastName(last)
  }

  const handleProfileUpdate = (event: Event) => {
    const customEvent = event as CustomEvent<{
      firstName: string
      lastName: string
    }>

    updateProfileName(
      customEvent.detail.firstName,
      customEvent.detail.lastName
    )
  }

  useEffect(() => {
    window.addEventListener(
      'trustlayer-profile-updated',
      handleProfileUpdate
    )

    return () => {
      window.removeEventListener(
        'trustlayer-profile-updated',
        handleProfileUpdate
      )
    }
  }, [])

  // Automatic logout after 15 minutes of inactivity
  useEffect(() => {
    let timeout: ReturnType<typeof setTimeout>

    const logoutOnInactivity = () => {
      clearTimeout(timeout)

      timeout = setTimeout(() => {
        authService.logout()

        navigate('/', { replace: true })
      }, 15 * 60 * 1000)
    }

    const activityEvents = [
      'mousemove',
      'keydown',
      'click',
      'scroll',
      'touchstart',
    ]

    activityEvents.forEach((event) => {
      window.addEventListener(event, logoutOnInactivity)
    })

    logoutOnInactivity()

    return () => {
      clearTimeout(timeout)

      activityEvents.forEach((event) => {
        window.removeEventListener(event, logoutOnInactivity)
      })
    }
  }, [navigate])

  const initials =
    `${firstName.trim().charAt(0)}${lastName.trim().charAt(0) || (lastName ? '' : firstName.trim().charAt(1))}`.toUpperCase()

  const fullName = `${firstName} ${lastName}`.trim()

  const currentPage =
    location.pathname === '/profile'
      ? 'My Profile'
      : navigation.find((item) => item.path === location.pathname)?.name ?? 'TRUSTLAYER'

  const filteredPages = navigation.filter((item) =>
    item.name.toLowerCase().includes(searchText.toLowerCase())
  )

  const openPage = (path: string) => {
    navigate(path)
    setSearchOpen(false)
    setNotificationOpen(false)
    setSearchText('')
  }

  const handleLogout = () => {
    localStorage.removeItem('trustlayerLoggedIn')
    localStorage.removeItem('trustlayerSessionEmail')
    localStorage.removeItem('trustlayerFirstName')
    localStorage.removeItem('trustlayerLastName')
    navigate('/')
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">

      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-0 z-50 flex h-screen w-64 flex-col border-r border-slate-800 bg-slate-900 transition-transform duration-300 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } md:translate-x-0`}
      >
        <div className="flex h-20 items-center justify-between border-b border-slate-800 px-5">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-500/10">
              <ShieldCheck className="h-6 w-6 text-cyan-400" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-wide">TRUSTLAYER</h1>
              <p className="text-xs text-slate-400">Voice Security Platform</p>
            </div>
          </div>

          <button
            type="button"
            aria-label="Close sidebar"
            onClick={() => setSidebarOpen(false)}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 md:hidden"
          >
            <X size={20} />
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-4">
          <p className="mb-3 px-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Main Menu
          </p>

          {navigation.map((item) => {
            const Icon = item.icon

            return (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={() => setSidebarOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition-all ${
                    isActive
                      ? 'border border-cyan-500/20 bg-cyan-500/10 text-cyan-400'
                      : 'text-slate-400 hover:bg-slate-800 hover:text-white'
                  }`
                }
              >
                <Icon size={19} />
                <span>{item.name}</span>
              </NavLink>
            )
          })}
        </nav>

        {/* Logout icon and sidebar footer */}
        <div className="border-t border-slate-800 p-4">
          <button
            type="button"
            onClick={handleLogout}
            title="Logout"
            className="mb-4 flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium text-rose-400 transition hover:bg-rose-500/10"
          >
            <LogOut size={19} />
            <span>Logout</span>
          </button>

          <div className="rounded-xl border border-slate-700 bg-slate-800/60 p-3">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              <span className="text-xs font-medium text-slate-300">
                Development Mode
              </span>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              TRUSTLAYER Security Console
            </p>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="min-h-screen md:ml-64">

        <header className="sticky top-0 z-30 flex h-20 items-center justify-between border-b border-slate-800 bg-slate-900/95 px-4 backdrop-blur md:px-8">

          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Open sidebar"
              onClick={() => setSidebarOpen(true)}
              className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 md:hidden"
            >
              <Menu size={22} />
            </button>

            <div>
              <h2 className="text-lg font-semibold">{currentPage}</h2>
              <p className="hidden text-xs text-slate-500 sm:block">
                Adaptive Caller Trust & Transaction Security
              </p>
            </div>
          </div>

          {/* Right navbar */}
          <div className="flex items-center gap-2 sm:gap-4">

            {/* Search */}
            <div className="relative">
              <button
                type="button"
                aria-label="Search pages"
                onClick={() => {
                  setSearchOpen(!searchOpen)
                  setNotificationOpen(false)
                }}
                className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <Search size={20} />
              </button>

              {searchOpen && (
                <div className="absolute right-0 top-12 z-50 w-72 rounded-xl border border-slate-700 bg-slate-900 p-3 shadow-2xl sm:w-80">
                  <input
                    autoFocus
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    placeholder="Search dashboard pages..."
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500"
                  />

                  <p className="mb-2 mt-3 text-xs text-slate-500">
                    NAVIGATION RESULTS
                  </p>

                  <div className="max-h-64 space-y-1 overflow-y-auto">
                    {filteredPages.map((item) => {
                      const Icon = item.icon

                      return (
                        <button
                          key={item.path}
                          type="button"
                          onClick={() => openPage(item.path)}
                          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-800 hover:text-cyan-400"
                        >
                          <Icon size={17} />
                          {item.name}
                        </button>
                      )
                    })}

                    {filteredPages.length === 0 && (
                      <p className="px-3 py-3 text-sm text-slate-500">
                        No matching pages found.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Notifications */}
            <div className="relative">
              <button
                type="button"
                aria-label="Notifications"
                onClick={() => {
                  setNotificationOpen(!notificationOpen)
                  setSearchOpen(false)
                }}
                className="relative rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <Bell size={20} />
                <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-rose-500" />
              </button>

              {notificationOpen && (
                <div className="absolute right-0 top-12 z-50 w-80 rounded-xl border border-slate-700 bg-slate-900 p-4 shadow-2xl">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="font-semibold text-white">Notifications</h3>
                    <span className="text-xs text-slate-500">Demo alerts</span>
                  </div>

                  <div className="space-y-3">
                    <div className="flex gap-3 rounded-lg bg-slate-800/70 p-3">
                      <AlertTriangle size={18} className="shrink-0 text-amber-400" />
                      <div>
                        <p className="text-sm text-white">Suspicious call flagged</p>
                        <p className="mt-1 text-xs text-slate-400">
                          A sample call requires review.
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3 rounded-lg bg-slate-800/70 p-3">
                      <ShieldCheck size={18} className="shrink-0 text-cyan-400" />
                      <div>
                        <p className="text-sm text-white">Verification required</p>
                        <p className="mt-1 text-xs text-slate-400">
                          A sample transaction is awaiting approval.
                        </p>
                      </div>
                    </div>

                    <div className="flex gap-3 rounded-lg bg-slate-800/70 p-3">
                      <CheckCircle2 size={18} className="shrink-0 text-emerald-400" />
                      <div>
                        <p className="text-sm text-white">Enrollment submitted</p>
                        <p className="mt-1 text-xs text-slate-400">
                          Sample customer enrollment activity.
                        </p>
                      </div>
                    </div>
                  </div>

                  <p className="mt-3 text-center text-xs text-slate-500">
                    These are illustrative notifications, not live alerts.
                  </p>
                </div>
              )}
            </div>

            {/* Profile */}
            <button
              type="button"
              onClick={() => navigate('/profile')}
              title="Open Profile"
              className="flex items-center gap-2 border-l border-slate-700 pl-3 text-left sm:pl-4"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-cyan-500/15 font-bold text-cyan-400 transition hover:bg-cyan-500/25">
                {initials || 'AD'}
              </span>

              <span className="hidden sm:block">
                <span className="block text-sm font-medium text-white">
                  {fullName}
                </span>
                <span className="block text-xs text-slate-500">
                  Security Team
                </span>
              </span>
            </button>
          </div>
        </header>

        <main className="min-h-[calc(100vh-5rem)] p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default AppLayout
