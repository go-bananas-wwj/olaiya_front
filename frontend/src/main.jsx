import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

const Root = import.meta.env.VITE_APP_MODE === 'showcase'
  ? React.lazy(() => import('./showcase/Showcase')) : App

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <React.Suspense fallback={<p className="p-6" role="status">正在打开成分对照台…</p>}><Root /></React.Suspense>
  </React.StrictMode>,
)
