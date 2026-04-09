/**
 * Hook that loads notifications from the Gateway REST API, connects to the
 * SSE stream for real-time updates, and pushes everything into the vendored
 * notification drawer (zustand) and alert toaster (context) stores.
 */

import { useEffect, useRef } from 'react';
import { usePageNotifications } from '@ansible/ansible-ui-framework';
import { usePageAlertToaster } from '@ansible/ansible-ui-framework/PageAlertToaster';
import type { IPageNotification } from '@ansible/ansible-ui-framework/PageNotifications/PageNotification';
import type { IPageNotificationGroup } from '@ansible/ansible-ui-framework/PageNotifications/PageNotificationGroup';
import { listNotifications, markNotificationRead } from '../services/api';
import type { NotificationItem } from '../types/api';

const GROUP_LABELS: Record<string, string> = {
  scan_complete: 'Scans',
  secrets_detected: 'Security',
  health_changed: 'Health',
};

function groupKey(n: NotificationItem): string {
  return GROUP_LABELS[n.type] ?? 'Other';
}

function toPageNotification(n: NotificationItem): IPageNotification {
  return {
    id: String(n.id),
    title: n.title,
    description: n.message,
    timestamp: n.created_at,
    variant: n.variant,
    to: n.link || undefined,
  };
}

function buildGroups(items: NotificationItem[]): Record<string, IPageNotificationGroup> {
  const groups: Record<string, IPageNotificationGroup> = {};
  for (const item of items) {
    const key = groupKey(item);
    if (!groups[key]) {
      groups[key] = { title: key, notifications: [] };
    }
    groups[key].notifications.push(toPageNotification(item));
  }
  return groups;
}

function mergeNotification(
  existing: Record<string, IPageNotificationGroup>,
  item: NotificationItem,
): Record<string, IPageNotificationGroup> {
  const key = groupKey(item);
  const next = { ...existing };
  const group = next[key]
    ? { ...next[key], notifications: [...next[key].notifications] }
    : { title: key, notifications: [] };
  group.notifications.unshift(toPageNotification(item));
  next[key] = group;
  return next;
}

const NO_DISMISS_TYPES = new Set(['secrets_detected']);

export function useNotificationStream(): void {
  const { setNotificationGroups } = usePageNotifications();
  const alertToaster = usePageAlertToaster();
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    let es: EventSource | undefined;

    const startStream = async () => {
      try {
        const resp = await listNotifications(100, 0);
        if (!mountedRef.current) return;
        setNotificationGroups(() => buildGroups(resp.items));
      } catch {
        // Gateway may be unavailable — silent degradation
        if (!mountedRef.current) return;
      }

      if (!mountedRef.current) return;

      const proto = window.location.protocol === 'https:' ? 'https:' : 'http:';
      const sseUrl = `${proto}//${window.location.host}/api/v1/notifications/stream`;
      es = new EventSource(sseUrl);

      es.onmessage = (event) => {
        if (!mountedRef.current) return;
        let item: NotificationItem;
        try {
          item = JSON.parse(event.data as string) as NotificationItem;
        } catch {
          return;
        }

        setNotificationGroups((prev) => mergeNotification(prev, item));

        const timeout = NO_DISMISS_TYPES.has(item.type) ? undefined : 8000;
        const alertKey = `notif-${item.id}`;
        alertToaster.addAlert({
          key: alertKey,
          title: item.title,
          children: item.message,
          variant: item.variant,
          timeout,
          actionClose: undefined,
        });

        markNotificationRead(item.id).catch(() => {});
      };

      es.onerror = () => {
        // EventSource auto-reconnects — nothing to do
      };
    };

    void startStream();

    return () => {
      mountedRef.current = false;
      es?.close();
    };
  }, [setNotificationGroups, alertToaster]);
}
