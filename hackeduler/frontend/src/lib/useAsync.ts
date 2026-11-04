import { useCallback, useEffect, useRef, useState } from 'react'
import { validationMessage } from '../api/client'

/** Load data with loading / error state; `reload` re-runs the loader. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)
  const run = useCallback(() => {
    const id = ++seq.current
    setLoading(true)
    setError(null)
    loader()
      .then((d) => id === seq.current && setData(d))
      .catch((e) => id === seq.current && setError(validationMessage(e)))
      .finally(() => id === seq.current && setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => {
    run()
  }, [run])
  return { data, error, loading, reload: run, setData }
}
