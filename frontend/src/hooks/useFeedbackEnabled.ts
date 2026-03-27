import { useEffect, useState } from 'react';
import { getFeedbackEnabled } from '../services/api';

export function useFeedbackEnabled(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    getFeedbackEnabled()
      .then((r) => setEnabled(r.enabled))
      .catch(() => setEnabled(false));
  }, []);

  return enabled;
}
