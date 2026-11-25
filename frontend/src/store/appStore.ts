import { create } from 'zustand'
interface AppState { backendOnline: boolean | null; setBackendOnline: (online: boolean) => void; activeCallId: string | null; setActiveCallId: (id: string | null) => void }
export const useAppStore = create<AppState>((set) => ({ backendOnline: null, setBackendOnline: (backendOnline) => set({ backendOnline }), activeCallId: null, setActiveCallId: (activeCallId) => set({ activeCallId }) }))
