import { StrictMode } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { consumeHandoff } from './lib/session';
import './index.css';

// Pick up a cross-origin session handoff (auth.cyphward.com → app.cyphward.com)
// before anything reads the session store.
consumeHandoff();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
