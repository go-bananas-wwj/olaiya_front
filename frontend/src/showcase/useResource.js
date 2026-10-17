import { useEffect, useState } from 'react'

// Keep one resource's failures independent, and never render a previous identity's result.
export function useResource(load, dependencies) {
  const identity = JSON.stringify(dependencies)
  const [state, setState] = useState({ identity, loading: true })
  useEffect(() => {
    let current = true
    setState({ identity, loading: true })
    Promise.resolve().then(load).then(data => {
      if (current) setState({ identity, data })
    }).catch(error => { if (current) setState({ identity, error: error.message }) })
    return () => { current = false }
  }, dependencies)
  return state.identity === identity ? state : { loading: true }
}
