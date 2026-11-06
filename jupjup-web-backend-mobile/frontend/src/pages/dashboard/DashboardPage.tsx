import { useNavigate } from 'react-router-dom'
import DashboardApp from '@/features/jupjup-dashboard/DashboardApp'
import '@/features/jupjup-dashboard/styles.css'

export function DashboardPage() {
  const navigate = useNavigate()

  return <DashboardApp onOpenSettings={() => navigate('/settings')} />
}
