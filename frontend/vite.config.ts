import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.HATCH_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/v1/events": { target: api.replace(/^http/, "ws"), ws: true },
      "/api": api,
      "/healthz": api,
    },
  },
});
