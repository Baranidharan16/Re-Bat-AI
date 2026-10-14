import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Bot, Send, Sparkles, X } from "lucide-react";
import { api } from "../lib/api";
import { useAnalysis } from "../lib/store";
import { chatContext } from "../lib/twin";

type Msg = { role: "user" | "assistant"; text: string; provider?: string; note?: string };

const SUGGEST = [
  "Is this battery good for solar storage?",
  "Why did this battery age?",
  "Which minerals can we recover from it?",
  "Explain its ledger block and SHA-256 hash",
  "What do the 10 measured parameters say?",
];

/** **bold** and bullet lines, rendered as React nodes (no HTML injection). */
function Rich({ text }: { text: string }) {
  const inline = (s: string, k: number): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") && p.endsWith("**") ? <strong key={`${k}-${i}`} className="text-fog-100">{p.slice(2, -2)}</strong> : p));
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let list: ReactNode[] = [];
  const flush = () => { if (list.length) { out.push(<ul key={`u${out.length}`} className="my-1 list-disc space-y-0.5 pl-4">{list}</ul>); list = []; } };
  lines.forEach((l, i) => {
    const m = l.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (m) list.push(<li key={i}>{inline(m[1], i)}</li>);
    else { flush(); if (l.trim()) out.push(<p key={i} className="my-1">{inline(l.replace(/^#+\s*/, ""), i)}</p>); }
  });
  flush();
  return <>{out}</>;
}

export default function ChatAssistant() {
  const { result } = useAnalysis();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ provider: string; key_configured: boolean } | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const bid = result?.battery_id;

  useEffect(() => { if (open && !status) api.chatStatus().then(setStatus).catch(() => {}); }, [open]);
  useEffect(() => { setMsgs([]); }, [bid]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  async function ask(q: string) {
    if (!q.trim() || busy) return;
    const hist = msgs.map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setText(""); setBusy(true);
    try {
      let ev: string | null = null;
      try { ev = localStorage.getItem("rebat.evmodel"); } catch { /* ignore */ }
      const r = await api.chat(q, hist, chatContext(result, { ev_model_in_3d_view: ev }));
      setMsgs((m) => [...m, { role: "assistant", text: r.answer, provider: r.provider, note: r.note }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `Sorry — ${e.message}` }]);
    } finally { setBusy(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); ask(text); };

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} aria-label="Open battery AI assistant"
          className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-volt/60 bg-ink-950/90 px-4 py-3 text-sm font-medium text-volt shadow-[0_8px_30px_rgba(0,0,0,.45)] backdrop-blur hover:bg-ink-900">
          <Sparkles className="h-4 w-4" />Ask about {bid ?? "this battery"}
        </button>
      )}
      {open && (
        <section role="dialog" aria-label="Battery AI assistant"
          className="fixed bottom-5 right-5 z-40 flex h-[min(600px,calc(100vh-40px))] w-[min(400px,calc(100vw-40px))] flex-col overflow-hidden rounded-xl border border-ink-600 bg-ink-900 shadow-[0_20px_60px_rgba(0,0,0,.55)]">
          <header className="flex items-center gap-3 border-b border-ink-700 px-4 py-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-volt/15"><Bot className="h-4 w-4 text-volt" /></span>
            <div className="min-w-0">
              <div className="font-display font-semibold">Battery assistant</div>
              <div className="truncate text-2xs text-fog-400">{bid ? `${bid} · SOH ${result!.soh.soh.toFixed(1)}% · ${result!.circular.pathway.toLowerCase()}` : "no battery loaded"} · {status ? (status.key_configured ? "Gemini" : "offline mode") : "…"}</div>
            </div>
            <button className="ml-auto rounded p-1 text-fog-400 hover:text-fog-100" onClick={() => setOpen(false)} aria-label="Close assistant"><X className="h-4 w-4" /></button>
          </header>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
            {!msgs.length && (
              <div>
                <p className="text-fog-300">Ask anything about <span className="font-semibold text-fog-100">{bid ?? "the battery"}</span> — its health, remaining life, best reuse, the minerals inside, why it aged, or its ledger passport.</p>
                <div className="mt-3 flex flex-wrap gap-2">{SUGGEST.map((s) => <button key={s} onClick={() => ask(s)} className="rounded-full border border-ink-600 px-3 py-1.5 text-left text-xs text-fog-300 hover:border-volt hover:text-volt">{s}</button>)}</div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={m.role === "user" ? "ml-8 rounded-lg rounded-br-sm bg-volt/15 px-3 py-2 text-fog-100" : "mr-4 rounded-lg rounded-bl-sm border border-ink-700 bg-ink-850 px-3 py-2 text-fog-300"}>
                {m.role === "assistant" ? <Rich text={m.text} /> : m.text}
                {m.provider && <div className="mt-1 text-[10px] text-fog-500">{m.provider}{m.note ? ` · ${m.note}` : ""}</div>}
              </div>
            ))}
            {busy && <div className="mr-4 flex items-center gap-2 rounded-lg border border-ink-700 px-3 py-2 text-xs text-fog-400"><span className="h-2 w-2 rounded-full bg-volt live-dot" />Thinking…</div>}
            <div ref={end} />
          </div>
          <form onSubmit={submit} className="flex items-center gap-2 border-t border-ink-700 p-3">
            <label htmlFor="chat-q" className="sr-only">Your question</label>
            <input id="chat-q" className="input" placeholder="Ask about this battery…" value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} />
            <button className="btn-primary px-3" disabled={busy || !text.trim()} aria-label="Send"><Send className="h-4 w-4" /></button>
          </form>
        </section>
      )}
    </>
  );
}
