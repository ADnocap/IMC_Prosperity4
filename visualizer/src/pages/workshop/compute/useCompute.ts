import { useEffect, useMemo, useRef, useState } from 'react';
import { TaskInput, TaskOutput, WorkerResponse } from './types.ts';

// Lazily-instantiated singleton worker, shared across panels.
let sharedWorker: Worker | null = null;
function getWorker(): Worker {
  if (sharedWorker === null) {
    sharedWorker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });
  }
  return sharedWorker;
}

let nextId = 1;

type Extract<K extends TaskInput['kind']> =
  TaskOutput extends infer T
    ? T extends { kind: K; output: infer O }
      ? O
      : never
    : never;

/**
 * Runs a compute task on the shared Web Worker, with automatic cancellation
 * when the caller unmounts or the input changes. The hook keeps the previous
 * successful result visible while a new task is in flight so charts don't flash
 * empty during re-computation.
 */
export function useCompute<K extends TaskInput['kind']>(
  task: (TaskInput & { kind: K }) | null,
): { data: Extract<K> | null; loading: boolean; error: Error | null } {
  const [data, setData] = useState<Extract<K> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const latestIdRef = useRef<number>(0);

  // Serialize task shape to know when to re-run; Float64Arrays in the input
  // make deep-equality impractical, so key on identity of the wrapper object.
  const cacheKey = useMemo(() => {
    if (task === null) return null;
    return task;
  }, [task]);

  useEffect(() => {
    if (cacheKey === null) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }

    const id = (nextId += 1);
    latestIdRef.current = id;
    const worker = getWorker();
    setLoading(true);
    setError(null);

    const listener = (event: MessageEvent<WorkerResponse>): void => {
      if (event.data.id !== id) return;
      worker.removeEventListener('message', listener);
      if (latestIdRef.current !== id) return;
      if (event.data.ok) {
        const result = event.data.result;
        if (result.kind === cacheKey.kind) {
          setData(result.output as Extract<K>);
        }
        setError(null);
      } else {
        setError(new Error(event.data.error));
      }
      setLoading(false);
    };

    worker.addEventListener('message', listener);
    worker.postMessage({ id, task: cacheKey });

    return () => {
      worker.removeEventListener('message', listener);
    };
  }, [cacheKey]);

  return { data, loading, error };
}
