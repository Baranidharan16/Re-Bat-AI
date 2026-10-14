import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Analysis } from "./api";

type Source = { kind: "demo" | "csv" | "manual" | "live"; id: string };

type Ctx = {
  result: Analysis | null;
  source: Source | null;
  loading: boolean;
  error: string | null;
  loadDemo: (id: string) => Promise<void>;
  setAnalysis: (a: Analysis, s: Source) => void;
  refresh: () => Promise<void>;
  lastTest: any | null;
  setLastTest: (x: any | null) => void;
};

const AnalysisContext = createContext<Ctx | null>(null);
const KEY = "rebat.source";

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [result, setResult] = useState<Analysis | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTest, setLastTest] = useState<any | null>(null);

  const loadDemo = useCallback(async (id: string) => {
    setLoading(true); setError(null);
    try {
      const a = await api.demo(id);
      setResult(a); setSource({ kind: "demo", id }); setLastTest(null);
      try { localStorage.setItem(KEY, id); } catch { /* storage unavailable */ }
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  }, []);

  const setAnalysis = useCallback((a: Analysis, s: Source) => { setResult(a); setSource(s); setError(null); }, []);

  const refresh = useCallback(async () => {
    if (source?.kind === "demo") await loadDemo(source.id);
  }, [source, loadDemo]);

  useEffect(() => {
    let id = "RB-B02";
    try { id = localStorage.getItem(KEY) || id; } catch { /* ignore */ }
    loadDemo(id);
  }, [loadDemo]);

  return (
    <AnalysisContext.Provider value={{ result, source, loading, error, loadDemo, setAnalysis, refresh, lastTest, setLastTest }}>
      {children}
    </AnalysisContext.Provider>
  );
}

export function useAnalysis() {
  const c = useContext(AnalysisContext);
  if (!c) throw new Error("useAnalysis outside provider");
  return c;
}
