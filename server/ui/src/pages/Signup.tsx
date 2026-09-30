import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export default function Signup() {
  const nav = useNavigate();
  const { signup } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [friendly, setFriendly] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await signup(email, password, friendly);
      nav("/");
    } catch (e: any) {
      setErr(e?.message ?? "signup failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm py-24">
      <h1 className="mb-6 text-2xl font-semibold text-slate-800">Create account</h1>
      <form onSubmit={onSubmit} className="space-y-3">
        <input
          className="w-full rounded border border-slate-300 px-3 py-2"
          placeholder="Friendly name"
          value={friendly}
          onChange={(e) => setFriendly(e.target.value)}
          required
        />
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
        {err ? <div className="text-sm text-red-500">{err}</div> : null}
        <button
          disabled={busy}
          className="w-full rounded bg-brand-500 py-2 text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {busy ? "…" : "Sign up"}
        </button>
      </form>
      <div className="mt-4 text-sm text-slate-600">
        Have an account?{" "}
        <Link to="/login" className="text-brand-600 hover:underline">
          Sign in
        </Link>
      </div>
    </div>
  );
}
