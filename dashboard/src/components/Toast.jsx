import { useState, useCallback, useEffect, useRef } from 'react'
import { CheckCircleIcon, AlertIcon, InfoIcon, CloseIcon } from './Icons.jsx'

let _addToast = null
export function toast(msg, type = 'info') { _addToast?.(msg, type) }
export function toastSuccess(msg) { toast(msg, 'success') }
export function toastError(msg)   { toast(msg, 'error') }
export function toastInfo(msg)    { toast(msg, 'info') }

export function ToastContainer() {
  const [toasts, setToasts] = useState([])
  const id = useRef(0)

  const add = useCallback((message, type = 'info') => {
    const key = ++id.current
    setToasts(t => [...t, { key, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.key !== key)), 4000)
  }, [])

  useEffect(() => { _addToast = add; return () => { _addToast = null } }, [add])

  const Icon = { success: CheckCircleIcon, error: AlertIcon, info: InfoIcon }

  return (
    <div className="toast-container">
      {toasts.map(({ key, message, type }) => {
        const I = Icon[type] || InfoIcon
        return (
          <div key={key} className={`toast toast-${type}`}>
            <I size={15} />
            <span style={{ flex: 1 }}>{message}</span>
            <CloseIcon size={13} style={{ cursor:'pointer', opacity:0.6 }}
              onClick={() => setToasts(t => t.filter(x => x.key !== key))} />
          </div>
        )
      })}
    </div>
  )
}
