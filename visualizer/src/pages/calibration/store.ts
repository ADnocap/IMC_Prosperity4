// In-memory pipeline state for the Calibration tab.
//
// Each stage owns an opaque `result` payload; the page coordinates transitions
// and invalidates downstream stages on `resetFrom`.
//
// We keep this as a small useState-based store rather than pulling in Zustand
// — the page is self-contained and doesn't need to share state across routes.

import { useCallback, useState } from 'react';
import { STAGES, StageId, StageState, StageStatus } from './types';

export type StageMap = Record<StageId, StageState>;

function initialMap(): StageMap {
  const out: Partial<StageMap> = {};
  for (const stage of STAGES) {
    out[stage.id] = { status: 'pending' };
  }
  return out as StageMap;
}

export function useStagesStore() {
  const [stages, setStages] = useState<StageMap>(initialMap());

  const update = useCallback((id: StageId, patch: Partial<StageState>) => {
    setStages(prev => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }, []);

  const setStatus = useCallback((id: StageId, status: StageStatus) => {
    setStages(prev => ({ ...prev, [id]: { ...prev[id], status } }));
  }, []);

  /**
   * Invalidate everything from `id` onward. Called when a user goes Back to an
   * earlier stage — downstream results are no longer valid against the revised
   * upstream output.
   */
  const resetFrom = useCallback((id: StageId) => {
    const idx = STAGES.findIndex(s => s.id === id);
    if (idx < 0) return;
    setStages(prev => {
      const next = { ...prev };
      for (let i = idx; i < STAGES.length; i++) {
        next[STAGES[i].id] = { status: 'pending' };
      }
      return next;
    });
  }, []);

  const reset = useCallback(() => setStages(initialMap()), []);

  return { stages, update, setStatus, resetFrom, reset };
}
