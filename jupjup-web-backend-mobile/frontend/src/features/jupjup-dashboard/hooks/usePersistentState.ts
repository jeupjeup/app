import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

export function usePersistentState<T>(key: string, fallback: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const parsed: unknown = JSON.parse(raw);
        if (Array.isArray(fallback) && Array.isArray(parsed)) return parsed as T;
      }
    } catch { /* Private browsing or invalid data: keep the demo defaults. */ }
    return fallback;
  });
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(value)); }
    catch { /* Local-only demo still works when storage is blocked. */ }
  }, [key, value]);
  return [value, setValue];
}
