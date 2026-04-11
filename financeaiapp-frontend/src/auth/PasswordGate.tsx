import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { appPassword } from "../env";

const LS_KEY = "finbot.authed.v1";

interface PasswordGateProps {
  children: ReactNode;
}

function PasswordGate({ children }: PasswordGateProps): ReactNode {
  const [authed, setAuthed] = useState<boolean>(false);
  const [input, setInput] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem(LS_KEY);
    if (stored === "1") {
      setAuthed(true);
    }
  }, []);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!appPassword) {
      setAuthed(true);
      localStorage.setItem(LS_KEY, "1");
      return;
    }
    if (input === appPassword) {
      setAuthed(true);
      localStorage.setItem(LS_KEY, "1");
      setError(null);
    } else {
      setError("ACCESS DENIED");
      setInput("");
    }
  };

  if (authed) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg font-mono">
      <div className="w-full max-w-md border border-border p-6">
        <div className="bg-fg text-bg px-3 py-1 text-[11px] font-bold uppercase tracking-widest mb-6">
          FINBOT // ACCESS CONTROL
        </div>

        <div className="text-[12px] text-fg-dim mb-6 leading-relaxed">
          <div className="mb-1">$ whoami</div>
          <div className="text-muted">guest@finbot</div>
          <div className="mt-3 mb-1">$ auth --challenge</div>
          <div className="text-fg">enter password to continue</div>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <span className="text-fg text-[14px] font-bold">{">"}</span>
            <input
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              autoFocus
              placeholder="••••••••"
              className="flex-1 bg-transparent border-b border-border focus:border-fg outline-none text-[13px] text-fg font-mono py-1 placeholder:text-muted"
            />
          </div>
          {error && (
            <div className="text-[11px] text-down border border-down/40 px-2 py-1">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={!input}
            className="bg-fg text-bg py-2 text-[11px] font-bold uppercase tracking-wider hover:bg-fg/80 disabled:opacity-30 cursor-pointer"
          >
            [ authenticate ]
          </button>
        </form>

        <div className="mt-6 text-[10px] text-muted text-center">
          -- personal deployment · not for public use --
        </div>
      </div>
    </div>
  );
}

export default PasswordGate;
