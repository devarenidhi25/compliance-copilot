import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-serif/latin-400.css';
import '@fontsource/ibm-plex-serif/latin-600.css';
import './styles.css';
import { SessionProvider, useSession } from './session';
import { Shell } from './components/Shell';
import { SignIn } from './pages/SignIn';
import { Home } from './pages/Home';
import { Library } from './pages/Library';
import { Ask } from './pages/Ask';
import { Changes } from './pages/Changes';
import { Gaps } from './pages/Gaps';
import { Audit } from './pages/Audit';

function App() {
  const { session } = useSession();
  if (!session) return <SignIn />;
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Home />} />
        <Route path="ask" element={<Ask />} />
        <Route path="library" element={<Library />} />
        <Route path="changes" element={<Changes />} />
        <Route path="gaps" element={<Gaps />} />
        <Route path="audit" element={<Audit />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SessionProvider>
      <HashRouter>
        <App />
      </HashRouter>
    </SessionProvider>
  </StrictMode>,
);
