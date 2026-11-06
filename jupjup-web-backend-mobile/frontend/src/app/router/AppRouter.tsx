import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthCallbackPage } from '@/pages/auth/AuthCallbackPage'
import { AuthPage } from '@/pages/auth/AuthPage'
import { HomePage } from '@/pages/home/HomePage'
import { NotFoundPage } from '@/pages/not-found/NotFoundPage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { ArchiveLayout } from '@/features/archive/ArchiveLayout'
import { HomeDashboardPage } from '@/pages/archive/HomeDashboardPage'
import { SearchResultsPage } from '@/pages/archive/SearchResultsPage'
import { ContentsPage } from '@/pages/archive/ContentsPage'
import { NewContentPage } from '@/pages/archive/NewContentPage'
import { ContentDetailPage } from '@/pages/archive/ContentDetailPage'
import { CollectionsPage } from '@/pages/archive/CollectionsPage'
import { CollectionDetailPage } from '@/pages/archive/CollectionDetailPage'
import { OnboardingRoute } from '@/pages/onboarding/OnboardingRoute'

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/signup" element={<AuthPage mode="signup" />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/onboarding" element={<OnboardingRoute />} />
        <Route element={<ArchiveLayout />}>
          <Route path="/dashboard" element={<HomeDashboardPage />} />
          <Route path="/search" element={<SearchResultsPage />} />
          <Route path="/contents" element={<ContentsPage />} />
          <Route path="/contents/new" element={<NewContentPage />} />
          <Route path="/contents/:contentId" element={<ContentDetailPage />} />
          <Route path="/collections" element={<CollectionsPage />} />
          <Route path="/collections/:collectionId" element={<CollectionDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
