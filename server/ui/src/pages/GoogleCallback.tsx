import { useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, setAccessToken } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function GoogleCallback() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { setUser } = useAuth();

  useEffect(() => {
    const code = params.get("code");
    const returnedState = params.get("state");
    const verifier = sessionStorage.getItem("google_pkce_verifier");
    const state = sessionStorage.getItem("google_pkce_state");
    if (!code || !verifier || state !== returnedState) {
      nav("/login");
      return;
    }
    (async () => {
      try {
        const body = await api<{ access_token: string; user: any }>(
          "/api/user/oauth/google/callback",
          {
            method: "POST",
            body: JSON.stringify({ code, code_verifier: verifier }),
            auth: false,
          },
        );
        setAccessToken(body.access_token);
        setUser(body.user);
        nav("/");
      } catch {
        nav("/login");
      } finally {
        sessionStorage.removeItem("google_pkce_verifier");
        sessionStorage.removeItem("google_pkce_state");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div className="p-8 text-slate-500">Completing sign in…</div>;
}
