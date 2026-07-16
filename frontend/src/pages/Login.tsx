import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login, signup } = useAuth();
  const navigate = useNavigate();

  const switchMode = () => {
  
    setMode((m) => (m === "login" ? "signup" : "login"));
    setEmail("");
    setPassword("");
    setError("");
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "login") await login(email, password);
      else await signup(email, password);
      navigate("/documents");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[85vh] flex items-center justify-center px-4 bg-app-gradient">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <h1 className="font-display font-bold text-2xl bg-brand-gradient bg-clip-text text-transparent tracking-tight">
            Research Assistant
          </h1>
          <p className="text-sm text-surface-500 mt-2">
            {mode === "login" ? "Welcome back" : "Create your account"}
          </p>
        </div>

        <div className="card p-7 animate-fade-in-up">
          <form onSubmit={onSubmit} className="space-y-3.5">
            <input
              type="email"
              required
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-field"
            />
            <input
              type="password"
              required
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-field"
            />
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button type="submit" disabled={loading} className="btn-primary w-full">
              {loading ? "Please wait…" : mode === "login" ? "Log in" : "Sign up"}
            </button>
          </form>
          <button
            onClick={switchMode}
            className="mt-4 text-sm text-brand-600 hover:text-brand-700 hover:underline w-full text-center"
          >
            {mode === "login" ? "Need an account? Sign up" : "Already have an account? Log in"}
          </button>
        </div>
      </div>
    </div>
  );
}
