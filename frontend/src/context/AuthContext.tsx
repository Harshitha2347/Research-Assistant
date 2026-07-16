import { createContext, useContext, useState, ReactNode } from "react";
import { login as apiLogin, signup as apiSignup } from "../api/client";

interface AuthState {
  userId: string | null;
  email: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState<string | null>(localStorage.getItem("user_id"));
  const [email, setEmail] = useState<string | null>(localStorage.getItem("email"));
  const [token, setToken] = useState<string | null>(localStorage.getItem("access_token"));

  const persist = (token: string, uid: string, em: string) => {
    localStorage.setItem("access_token", token);
    localStorage.setItem("user_id", uid);
    localStorage.setItem("email", em);
    setUserId(uid);
    setEmail(em);
    setToken(token);
  };

  const login = async (e: string, password: string) => {
    const res = await apiLogin(e, password);
    persist(res.data.access_token, res.data.user_id, res.data.email);
  };

  const signup = async (e: string, password: string) => {
    const res = await apiSignup(e, password);
    persist(res.data.access_token, res.data.user_id, res.data.email);
  };

  const logout = () => {
    localStorage.clear();
    setUserId(null);
    setEmail(null);
    setToken(null);
  };

  return (
    <AuthContext.Provider
      value={{ userId, email, isAuthenticated: !!userId && !!token, login, signup, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
