import { Navigate, Route, Routes } from "react-router-dom";
import Shell from "./components/Shell";
import LibraryPage from "./pages/Library";
import LoginPage from "./pages/Login";
import SignupPage from "./pages/Signup";
import RecentlySavedPage from "./pages/RecentlySaved";
import DeletedPage from "./pages/Deleted";
import GoogleCallbackPage from "./pages/GoogleCallback";
import { useAuth } from "./lib/auth";

function Protected({ children }: { children: JSX.Element }) {
  const { user, bootstrapping } = useAuth();
  if (bootstrapping) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/oauth/google/callback" element={<GoogleCallbackPage />} />
      <Route
        path="/"
        element={
          <Protected>
            <Shell>
              <LibraryPage />
            </Shell>
          </Protected>
        }
      />
      <Route
        path="/recently-saved"
        element={
          <Protected>
            <Shell>
              <RecentlySavedPage />
            </Shell>
          </Protected>
        }
      />
      <Route
        path="/deleted"
        element={
          <Protected>
            <Shell>
              <DeletedPage />
            </Shell>
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
