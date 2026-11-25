import { apiRequest, setAccessToken } from './api'

export interface AuthPrincipal { subject: string; role: string; auth_type: string; scopes: string[] }
export const authService = {
  async connect(token: string): Promise<AuthPrincipal> {
    setAccessToken(token.trim())
    try {
      const principal = await apiRequest<AuthPrincipal>('/auth/me')
      localStorage.setItem('trustlayerLoggedIn', 'true')
      localStorage.setItem('trustlayerSessionEmail', principal.subject)
      return principal
    } catch (error) {
      setAccessToken(null)
      throw error
    }
  },
  async inspect(): Promise<AuthPrincipal> { return apiRequest<AuthPrincipal>('/auth/me') },
  logout() {
    setAccessToken(null)
    ;['trustlayerLoggedIn', 'trustlayerSessionEmail', 'trustlayerEmail', 'trustlayerFirstName', 'trustlayerLastName'].forEach((key) => localStorage.removeItem(key))
  },
}
