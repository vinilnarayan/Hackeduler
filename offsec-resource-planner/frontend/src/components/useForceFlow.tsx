import { useState } from 'react'
import { ApiError, validationMessage } from '../api/client'
import type { ForcePayload, OverrideDetails } from '../api/types'
import { useToast } from '../lib/toast'
import { ForceAllocateDialog } from './ForceAllocateDialog'

/**
 * Runs an admin action. If the backend answers 409 override_required, shows the Force Allocate
 * warning dialog; on explicit confirmation the action is retried with {force: {confirm, reason}}.
 */
export function useForceFlow() {
  const toast = useToast()
  const [details, setDetails] = useState<OverrideDetails | null>(null)
  const [pending, setPending] = useState<((f: ForcePayload) => Promise<void>) | null>(null)

  async function run<T>(action: (force?: ForcePayload) => Promise<T>, onDone: (r: T) => void) {
    try {
      onDone(await action())
    } catch (e) {
      if (e instanceof ApiError && e.code === 'override_required' && e.details?.requires_force) {
        setDetails(e.details)
        setPending(() => async (f: ForcePayload) => {
          try {
            const r = await action(f)
            setDetails(null)
            toast('success', 'Force Allocate completed and recorded in the audit trail')
            onDone(r)
          } catch (err) { toast('error', validationMessage(err)) }
        })
      } else toast('error', validationMessage(e))
    }
  }

  const dialog = (
    <ForceAllocateDialog open={!!details} details={details} onClose={() => setDetails(null)} onConfirm={async (f) => { if (pending) await pending(f) }} />
  )
  return { run, dialog }
}
