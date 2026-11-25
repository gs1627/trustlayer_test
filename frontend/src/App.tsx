import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom'

import AppLayout from './components/common/AppLayout'

import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Enrollment from './pages/Enrollment'
import LiveMonitoring from './pages/LiveMonitoring'
import Forensics from './pages/Forensics'
import ConversationIntelligence from './pages/ConversationIntelligence'
import Transactions from './pages/Transactions'
import CustomerApproval from './pages/CustomerApproval'
import Analytics from './pages/Analytics'
import Admin from './pages/Admin'
import Profile from './pages/Profile'

function ProtectedRoute() {
  const isLoggedIn =
    localStorage.getItem('trustlayerLoggedIn') === 'true'

  return isLoggedIn ? <AppLayout /> : <Navigate to="/" replace />
}


function App() {
  return (
    <BrowserRouter>
      <Routes>

        {/* Login and registration without sidebar */}
        <Route path="/" element={<Login />} />
        <Route path="/register" element={<Register />} />

        {/* All other pages use AppLayout */}
        <Route element={<ProtectedRoute />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/enrollment" element={<Enrollment />} />
          <Route path="/monitoring" element={<LiveMonitoring />} />
          <Route path="/forensics" element={<Forensics />} />
          <Route path="/intelligence" element={<ConversationIntelligence />} />
          <Route path="/transactions" element={<Transactions />} />
          <Route path="/approval" element={<CustomerApproval />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/profile" element={<Profile />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />

      </Routes>
    </BrowserRouter>
  )
}

export default App