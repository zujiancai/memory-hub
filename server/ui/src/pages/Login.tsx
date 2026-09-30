import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { api } from "../lib/api";

export default function Login() {
  const nav = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      nav("/");
    } catch (err: any) {
      setError(err?.message ?? "login failed");
    } finally {
      setBusy(false);
    }
  }

  async function loginWithGoogle() {
    try {
      const { authorize_url, code_verifier, state } = await api<{
        authorize_url: string;
        code_verifier: string;
        state: string;
      }>("/api/user/oauth/google/start", { auth: false });
      sessionStorage.setItem("google_pkce_verifier", code_verifier);
      sessionStorage.setItem("google_pkce_state", state);
      window.location.href = authorize_url;
    } catch (err: any) {
      setError(err?.message ?? "google not configured");
    }
  }

  return (
    <div className="mx-auto max-w-sm py-24">
      <h1 className="mb-6 text-2xl font-semibold text-slate-800">Sign in</h1>
      <form onSubmit={onSubmit} className="space-y-3">
        <input
          type="email"
          placeholder="Email"
          className="w-full rounded border border-slate-300 px-3 py-2"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <input
          type="password"
          placeholder="Password"
          className="w-full rounded border border-slate-300 px-3 py-2"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error ? <div className="text-sm text-red-500">{error}</div> : null}
        <button
          disabled={busy}
          className="w-full rounded bg-brand-500 py-2 text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {busy ? "…" : "Sign in"}
        </button>
      </form>
      <button
        onClick={loginWithGoogle}
        className="mt-2 w-full rounded border border-slate-300 py-2 text-sm text-slate-700 hover:bg-slate-100"
      >
        Continue with Google
      </button>
      <div className="mt-4 text-sm text-slate-600">
        No account?{" "}
        <Link to="/signup" className="text-brand-600 hover:underline">
          Sign up
        </Link>
      </div>
    </div>
  );
}
