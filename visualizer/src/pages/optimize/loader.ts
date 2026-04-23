// API client for the optimizer endpoints exposed by dashboard_server.py.
//
// Both endpoints live under `/__prosperity4mcbt__/optimizer/`. The payloads
// mirror the types in `./types.ts`.

import axios from 'axios';
import { StudyDetail, StudyListItem } from './types.ts';

const BASE = '/__prosperity4mcbt__/optimizer';

export async function fetchStudyList(): Promise<StudyListItem[]> {
  const resp = await axios.get<{ studies: StudyListItem[] }>(`${BASE}/list`);
  return resp.data.studies ?? [];
}

export async function fetchStudyDetail(name: string): Promise<StudyDetail> {
  // Normalize optional / missing fields once so every panel downstream can
  // trust that `trials` and `paramNames` are arrays and validators/retest
  // are either valid objects or null. Stalled studies (only study.db on
  // disk) commonly return partial payloads from the backend.
  const resp = await axios.get<Partial<StudyDetail>>(`${BASE}/study`, { params: { name } });
  const raw = resp.data ?? {};
  return {
    name: raw.name ?? name,
    trials: Array.isArray(raw.trials) ? raw.trials : [],
    paramNames: Array.isArray(raw.paramNames) ? raw.paramNames : [],
    validators: raw.validators ?? null,
    retest: raw.retest ?? null,
  };
}
