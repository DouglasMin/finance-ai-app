import { useCallback, useEffect, useState } from "react";
import { streamInvocation } from "../../api/agentcore";
import type { InvokePayload } from "../../api/agentcore";

const PROVIDERS = [
  { value: "openai", label: "OpenAI GPT" },
  { value: "bedrock", label: "Bedrock Claude" },
] as const;

function parseSseEvent(chunk: string): Record<string, unknown> | null {
  for (const line of chunk.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    try {
      return JSON.parse(trimmed.slice("data:".length).trim());
    } catch {
      // ignore
    }
  }
  return null;
}

function LlmProviderSelect() {
  const [provider, setProvider] = useState<string>("openai");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      const payload = { action: "get_llm_provider" } as InvokePayload;
      for await (const chunk of streamInvocation(payload, controller.signal)) {
        const evt = parseSseEvent(chunk);
        if (evt?.event === "llm_provider" && typeof evt.provider === "string") {
          setProvider(evt.provider);
        }
      }
    })();
    return () => controller.abort();
  }, []);

  const handleChange = useCallback(
    async (e: React.ChangeEvent<HTMLSelectElement>) => {
      const newProvider = e.target.value;
      setLoading(true);
      setProvider(newProvider);
      try {
        const controller = new AbortController();
        const payload = {
          action: "set_llm_provider",
          provider: newProvider,
        } as unknown as InvokePayload;
        for await (const chunk of streamInvocation(
          payload,
          controller.signal,
        )) {
          const evt = parseSseEvent(chunk);
          if (
            evt?.event === "llm_provider" &&
            typeof evt.provider === "string"
          ) {
            setProvider(evt.provider);
          }
        }
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] text-muted uppercase tracking-wider">
        LLM
      </span>
      <select
        value={provider}
        onChange={handleChange}
        disabled={loading}
        className="bg-bg border border-border-dim text-fg text-[11px] px-2 py-0.5 rounded cursor-pointer hover:border-fg disabled:opacity-50"
      >
        {PROVIDERS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      {loading && (
        <span className="text-[9px] text-muted animate-pulse">...</span>
      )}
    </div>
  );
}

export default LlmProviderSelect;
