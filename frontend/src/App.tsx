import { Navigate, Route, Routes, Link, useLocation } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import { JobsProvider, useChatSession, useUpload } from "./context/JobsContext";
import Login from "./pages/Login";
import Documents from "./pages/Documents";
import Chat from "./pages/Chat";
import Evaluation from "./pages/Evaluation";


function UploadIndicator() {
  const { phase, progress, fileCount } = useUpload();
  if (phase === "idle") return null;

  return (
    <Link
      to="/documents"
      className="hidden md:flex items-center gap-2 text-xs font-medium text-brand-700 bg-brand-50 border border-brand-100 rounded-full px-3 py-1.5 animate-fade-in"
      title="Go to Documents to see details"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-brand-500 animate-pulse-soft" />
      {phase === "uploading"
        ? `Uploading ${fileCount} file${fileCount > 1 ? "s" : ""}… ${progress}%`
        : "Indexing document…"}
    </Link>
  );
}

function ChatIndicator() {
  const { sending } = useChatSession();
  const { pathname } = useLocation();

  if (!sending || pathname === "/chat") return null;

  return (
    <Link
      to="/chat"
      className="hidden md:flex items-center gap-2 text-xs font-medium text-accent-600 bg-accent-400/15 border border-accent-400/30 rounded-full px-3 py-1.5 animate-fade-in"
      title="Go to Chat to see the reply as it arrives"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-accent-500 animate-pulse-soft" />
      Generating reply…
    </Link>
  );
}

const icons = {
  documents: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M5 2.5h6.17L15 6.33V17.5H5V2.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M11 2.5V6.5H15" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M7.3 10.2h5.4M7.3 12.6h5.4M7.3 14.9h3.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  chat: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path
        d="M3 5.5A2.5 2.5 0 0 1 5.5 3h9A2.5 2.5 0 0 1 17 5.5v6A2.5 2.5 0 0 1 14.5 14H8l-3.6 3V14h-.9A2.5 2.5 0 0 1 3 11.5v-6Z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  ),
  eval: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M4 16.5V9M10 16.5V3.5M16 16.5v-6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  logout: (
    <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4">
      <path d="M8 3H4.5A1.5 1.5 0 0 0 3 4.5v11A1.5 1.5 0 0 0 4.5 17H8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="M13 13.5 17 10l-4-3.5M17 10H7.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

function NavBar() {
  const { isAuthenticated, email, logout } = useAuth();
  const { pathname } = useLocation();
  if (!isAuthenticated) return null;

  const linkClass = (path: string) =>
    `flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-medium transition-colors ${
      pathname === path
        ? "bg-brand-50 text-brand-700"
        : "text-surface-500 hover:bg-surface-100 hover:text-surface-800"
    }`;

  const initial = (email || "?").charAt(0).toUpperCase();

  return (
    <nav className="sticky top-0 z-30 flex items-center justify-between px-6 py-3 bg-white/80 backdrop-blur-md border-b border-surface-200">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <span className="font-display font-bold text-lg bg-brand-gradient bg-clip-text text-transparent tracking-tight">
            Research Assistant
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Link to="/documents" className={linkClass("/documents")}>
            {icons.documents}
            <span className="hidden sm:inline">Documents</span>
          </Link>
          <Link to="/chat" className={linkClass("/chat")}>
            {icons.chat}
            <span className="hidden sm:inline">Chat</span>
          </Link>
          <Link to="/evaluation" className={linkClass("/evaluation")}>
            {icons.eval}
            <span className="hidden sm:inline">Evaluation</span>
          </Link>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <UploadIndicator />
        <ChatIndicator />
        <div className="hidden sm:flex items-center gap-2 text-sm text-surface-500">
          <div className="w-6 h-6 rounded-full bg-surface-200 text-surface-600 flex items-center justify-center text-xs font-semibold">
            {initial}
          </div>
          <span>{email}</span>
        </div>
        <button onClick={logout} className="btn-ghost" title="Log out">
          {icons.logout}
          <span className="hidden sm:inline">Logout</span>
        </button>
      </div>
    </nav>
  );
}

function Protected({ children }: { children: JSX.Element }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <JobsProvider>
      <div className="h-screen flex flex-col overflow-hidden bg-app-gradient">
        <NavBar />
        <main className="flex-1 flex flex-col min-h-0 overflow-y-auto">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/documents" element={<Protected><Documents /></Protected>} />
            <Route path="/chat" element={<Protected><Chat /></Protected>} />
            <Route path="/evaluation" element={<Protected><Evaluation /></Protected>} />
            <Route path="*" element={<Navigate to="/documents" replace />} />
          </Routes>
        </main>
      </div>
    </JobsProvider>
  );
}
