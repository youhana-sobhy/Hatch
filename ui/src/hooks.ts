import { useCallback, useEffect, useRef, useState } from "react";
import { eventsUrl } from "./api";
import type { HatchEvent } from "./types";

/** Load data, and reload it on demand. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const loader = useRef(load);
  loader.current = load;

  const reload = useCallback(async () => {
    try {
      setData(await loader.current());
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload };
}

type Listener = (event: HatchEvent) => void;
const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
let connected = false;
const statusListeners = new Set<(up: boolean) => void>();

function connect() {
  if (socket) return;
  socket = new WebSocket(eventsUrl());
  socket.onopen = () => {
    connected = true;
    statusListeners.forEach((l) => l(true));
  };
  socket.onmessage = (message) => {
    const event = JSON.parse(message.data) as HatchEvent;
    if (event.type !== "ping") listeners.forEach((l) => l(event));
  };
  socket.onclose = () => {
    socket = null;
    connected = false;
    statusListeners.forEach((l) => l(false));
    if (listeners.size) setTimeout(connect, 2000);
  };
}

/** Subscribe to the live event stream (one shared WebSocket, auto-reconnecting). */
export function useEvents(onEvent: Listener) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    const listener: Listener = (e) => handler.current(e);
    listeners.add(listener);
    connect();
    return () => {
      listeners.delete(listener);
    };
  }, []);
}

export function useLive(): boolean {
  const [up, setUp] = useState(connected);
  useEvents(() => undefined); // keeps the shared socket open on every page
  useEffect(() => {
    setUp(connected);
    statusListeners.add(setUp);
    return () => {
      statusListeners.delete(setUp);
    };
  }, []);
  return up;
}

/** Re-run `reload` (debounced) whenever an event matches. */
export function useLiveReload(reload: () => void, match: (e: HatchEvent) => boolean = () => true) {
  const timer = useRef<number | undefined>(undefined);
  useEvents((event) => {
    if (!match(event)) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(reload, 250);
  });
}
