import { useMemo } from 'react';
import type { PageNavigationItem } from '@ansible/ansible-ui-framework';
import { DashboardPage } from '../pages/DashboardPage';
import { NewScanPage } from '../pages/NewScanPage';
import { ScansPage } from '../pages/ScansPage';
import { ScanDetailPage } from '../pages/ScanDetailPage';
import { SessionsPage } from '../pages/SessionsPage';
import { SessionDetailPage } from '../pages/SessionDetailPage';
import { TopViolationsPage } from '../pages/TopViolationsPage';
import { FixTrackerPage } from '../pages/FixTrackerPage';
import { AiMetricsPage } from '../pages/AiMetricsPage';
import { HealthPage } from '../pages/HealthPage';
import { SettingsPage } from '../pages/SettingsPage';

export function useApmeNavigation(): PageNavigationItem[] {
  return useMemo<PageNavigationItem[]>(
    () => [
      { id: 'dashboard', path: '', label: 'Dashboard', element: <DashboardPage /> },
      { id: 'new-scan', path: 'new-scan', label: 'New Scan', element: <NewScanPage /> },
      { id: 'scans', path: 'scans', label: 'Scans', element: <ScansPage /> },
      { id: 'scan-detail', path: 'scans/:scanId', element: <ScanDetailPage />, hidden: true },
      { id: 'sessions', path: 'sessions', label: 'Sessions', element: <SessionsPage /> },
      { id: 'session-detail', path: 'sessions/:sessionId', element: <SessionDetailPage />, hidden: true },
      { id: 'violations', path: 'violations', label: 'Top Violations', element: <TopViolationsPage /> },
      { id: 'fix-tracker', path: 'fix-tracker', label: 'Fix Tracker', element: <FixTrackerPage /> },
      { id: 'ai-metrics', path: 'ai-metrics', label: 'AI Metrics', element: <AiMetricsPage /> },
      { id: 'health', path: 'health', label: 'Health', element: <HealthPage /> },
      { id: 'settings', path: 'settings', label: 'Settings', element: <SettingsPage /> },
    ],
    [],
  );
}
