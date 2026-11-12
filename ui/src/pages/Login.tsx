import { useState } from "react";
import { api, setToken } from "../api";
import { Logo } from "../App";
import type { Me } from "../types";

const DEV = [
  ["dev-requester", "Requester", "Network engineer requesting onboardings"],
  ["dev-approver", "Approver", "Lead engineer approving core devices"],
  ["dev-maintainer", "Maintainer", "Owns golden templates"],
  ["dev-admin", "Admin", "Everything"],
];

export function Login({ onLogin }: { onLogin: (me: Me) => void }) {
  const [token, setValue] = useState("");
  const [error, setError] = useState("");

  async function signIn(value: string) {
    setToken(value);
    try {
      onLogin(await api.me());
    } catch {
      setToken(null);
      setError("That token was not accepted.");
    }
  }

  return (
    <div className="login">
      <div className="login-card">
        <div className="brand big">
          <Logo />
          <div>
            <strong>Hatch</strong>
            <small>Zero-touch device onboarding</small>
          </div>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); void signIn(token); }}>
          <label>
            API token
            <input type="password" value={token} onChange={(e) => setValue(e.target.value)} placeholder="Bearer token" autoFocus />
          </label>
          {error && <div className="alert bad">{error}</div>}
          <button className="primary" disabled={!token}>Sign in</button>
        </form>
        <div className="divider">development tokens</div>
        <div className="persona-grid">
          {DEV.map(([value, name, hint]) => (
            <button key={value} className="persona" onClick={() => void signIn(value)}>
              <strong>{name}</strong>
              <small>{hint}</small>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
