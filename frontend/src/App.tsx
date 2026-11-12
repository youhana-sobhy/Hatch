import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import { useLive } from "./hooks";
import type { Me } from "./types";
import { Dashboard } from "./pages/Dashboard";
import { OnboardingList } from "./pages/OnboardingList";
import { NewOnboarding } from "./pages/NewOnboarding";
import { OnboardingView } from "./pages/OnboardingView";
import { Templates } from "./pages/Templates";
import { Inventory } from "./pages/Inventory";
import { AuditLog } from "./pages/AuditLog";
import { Login } from "./pages/Login";

export function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const onLogout = () => setMe(null);
    window.addEventListener("hatch:logout", onLogout);
    if (getToken()) {
      api.me().then(setMe).catch(() => setMe(null)).finally(() => setChecked(true));
    } else setChecked(true);
    return () => window.removeEventListener("hatch:logout", onLogout);
  }, []);

  if (!checked) return null;
  if (!me) return <Login onLogin={setMe} />;

  return (
    <div className="shell">
      <Sidebar me={me} onLogout={() => { setToken(null); setMe(null); }} />
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/onboardings" element={<OnboardingList />} />
          <Route path="/onboardings/new" element={<NewOnboarding />} />
          <Route path="/onboardings/:id" element={<OnboardingView me={me} />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/audit" element={<AuditLog />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}

function Sidebar({ me, onLogout }: { me: Me; onLogout: () => void }) {
  const live = useLive();
  const links = [
    ["/", "Overview"],
    ["/onboardings", "Onboardings"],
    ["/onboardings/new", "New onboarding"],
    ["/templates", "Golden templates"],
    ["/inventory", "Inventory"],
    ["/audit", "Audit log"],
  ];
  return (
    <aside className="sidebar">
      <div className="brand">
        <Logo />
        <div>
          <strong>Hatch</strong>
          <small>Plug it in. Hatch does the rest.</small>
        </div>
      </div>
      <nav>
        {links.map(([to, text]) => (
          <NavLink key={to} to={to} end={to === "/" || to === "/onboardings"}>
            {text}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className={`live ${live ? "on" : ""}`}>{live ? "Live updates" : "Connecting…"}</div>
        <div className="who">
          <span>{me.user}</span>
          <small>{me.role}</small>
        </div>
        <button className="ghost small" onClick={onLogout}>Sign out</button>
      </div>
    </aside>
  );
}

export function Logo() {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden>
      <ellipse cx="17" cy="19" rx="11" ry="13" fill="var(--accent)" />
      <path d="M6.5 17 L11 13 L15 18 L19 12 L23 17 L27.5 14" stroke="var(--bg-side)" strokeWidth="2.4" fill="none" strokeLinejoin="round" />
    </svg>
  );
}
