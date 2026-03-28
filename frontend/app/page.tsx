"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

type Provider = {
  provider_name: string;
  url: string;
  why_relevant: string;
};

type ResultItem = {
  title?: string;
  provider?: string;
  price?: string;
  original_price?: string;
  discount_text?: string;
  short_reason_it_is_a_good_deal?: string;
  booking_url?: string;
};

type SiteResult = {
  provider_name: string;
  start_url: string;
  summary?: string | null;
  error?: string | null;
  results: ResultItem[];
};

type FinalPayload = {
  search_query?: string;
  searched_category: string;
  summary: string;
  provider_discovery?: {
    providers?: Provider[];
    search_summary?: string;
  } | null;
  site_results?: SiteResult[];
};

type AgentCardState = {
  siteId: string;
  providerName: string;
  startUrl: string;
  status: string;
  runId?: string;
  streamingUrl?: string;
  previewUrl?: string;
  progress: string[];
  summary?: string;
  resultCount?: number;
  error?: string;
  recommendation?: string;
  failureCategory?: string;
};

type StreamEvent = {
  type: string;
  site_id?: string;
  provider_name?: string;
  start_url?: string;
  run_id?: string;
  purpose?: string;
  streaming_url?: string;
  preview_url?: string;
  summary?: string;
  result_count?: number;
  providers?: Provider[];
  payload?: FinalPayload;
  error?: string;
  recommendation?: string;
  failure_category?: string;
  attempt?: number;
  max_attempts?: number;
};

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const CURRENCY_OPTIONS = ["USD", "EUR", "GBP", "SGD", "JPY", "KRW", "HKD"];

const INITIAL_FORM = {
  searchText: "",
  dateHint: "",
  currency: "",
  maxResults: 3,
  providerLimit: 4,
  stealth: false,
};

function upsertAgent(
  previous: Record<string, AgentCardState>,
  siteId: string,
  patch: Partial<AgentCardState>,
): Record<string, AgentCardState> {
  const current = previous[siteId] ?? {
    siteId,
    providerName: patch.providerName ?? "Waiting for provider",
    startUrl: patch.startUrl ?? "",
    status: "queued",
    progress: [],
  };

  return {
    ...previous,
    [siteId]: {
      ...current,
      ...patch,
    },
  };
}

export default function HomePage() {
  const [form, setForm] = useState(INITIAL_FORM);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionStatus, setSessionStatus] = useState<
    "idle" | "running" | "done" | "error"
  >("idle");
  const [agents, setAgents] = useState<Record<string, AgentCardState>>({});
  const [providers, setProviders] = useState<Provider[]>([]);
  const [finalPayload, setFinalPayload] = useState<FinalPayload | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const isRunning = sessionStatus === "running";

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  function handleStreamEvent(event: StreamEvent) {
    if (event.type === "providers.discovered") {
      setProviders(event.providers ?? []);
      return;
    }

    if (event.type === "session.completed" && event.payload) {
      setFinalPayload(event.payload);
      setSessionStatus("done");
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      return;
    }

    if (event.type === "session.failed") {
      setErrorMessage(event.error ?? "Search session failed.");
      setSessionStatus("error");
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      return;
    }

    if (!event.site_id) {
      return;
    }

    if (event.type === "agent.queued") {
      setAgents((previous) =>
        upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Queued provider",
          startUrl: event.start_url ?? "",
          status: "queued",
        }),
      );
      return;
    }

    if (event.type === "agent.started") {
      setAgents((previous) =>
        upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Running provider",
          startUrl: event.start_url ?? "",
          runId: event.run_id,
          status: "running",
        }),
      );
      return;
    }

    if (event.type === "agent.streaming_url") {
      setAgents((previous) =>
        upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Running provider",
          startUrl: event.start_url ?? "",
          runId: event.run_id,
          streamingUrl: event.streaming_url,
          previewUrl: event.preview_url,
          status: "streaming",
        }),
      );
      return;
    }

    if (event.type === "agent.progress") {
      setAgents((previous) => {
        const next = upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Running provider",
          startUrl: event.start_url ?? "",
          runId: event.run_id,
          status: "running",
        });
        const card = next[event.site_id!];
        return {
          ...next,
          [event.site_id!]: {
            ...card,
            progress: [...card.progress, event.purpose ?? "Working..."].slice(-12),
          },
        };
      });
      return;
    }

    if (event.type === "agent.retrying") {
      setAgents((previous) => {
        const next = upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Retrying provider",
          startUrl: event.start_url ?? "",
          runId: event.run_id,
          status: "retrying",
          error: event.error,
        });
        const card = next[event.site_id!];
        const retryLabel =
          event.attempt && event.max_attempts
            ? `Retrying after attempt ${event.attempt} of ${event.max_attempts}.`
            : "Retrying after a transient connection error.";
        return {
          ...next,
          [event.site_id!]: {
            ...card,
            progress: [...card.progress, retryLabel].slice(-12),
          },
        };
      });
      return;
    }

    if (event.type === "agent.completed") {
      setAgents((previous) =>
        upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Completed provider",
          startUrl: event.start_url ?? "",
          status: "completed",
          summary: event.summary,
          resultCount: event.result_count,
        }),
      );
      return;
    }

    if (event.type === "agent.failed") {
      setAgents((previous) =>
        upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Failed provider",
          startUrl: event.start_url ?? "",
          status: "failed",
          error: event.error,
          recommendation: event.recommendation,
          failureCategory: event.failure_category,
        }),
      );
      return;
    }

    if (event.type === "agent.blocked") {
      setAgents((previous) =>
        upsertAgent(previous, event.site_id!, {
          providerName: event.provider_name ?? "Blocked provider",
          startUrl: event.start_url ?? "",
          status: "blocked",
          error: event.error,
          recommendation: event.recommendation,
          failureCategory: event.failure_category,
        }),
      );
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSessionStatus("running");
    setErrorMessage(null);
    setSessionId(null);
    setProviders([]);
    setFinalPayload(null);
    setAgents({});

    eventSourceRef.current?.close();

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/searches`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          category: form.searchText.trim(),
          date_hint: form.dateHint || null,
          currency: form.currency || "USD",
          max_results: form.maxResults,
          discover_providers: true,
          provider_limit: form.providerLimit,
          stealth: form.stealth,
        }),
      });
    } catch {
      setSessionStatus("error");
      setErrorMessage(
        `Could not reach the backend at ${API_BASE_URL}. Start the FastAPI server with \`travel-deals-agent-api\` and make sure the URL is correct.`,
      );
      return;
    }

    if (!response.ok) {
      const text = await response.text();
      setSessionStatus("error");
      setErrorMessage(text || "Failed to start the search session.");
      return;
    }

    const data = (await response.json()) as { session_id: string };
    setSessionId(data.session_id);

    const source = new EventSource(
      `${API_BASE_URL}/api/searches/${data.session_id}/events`,
    );
    source.onmessage = (message) => {
      const payload = JSON.parse(message.data) as StreamEvent;
      handleStreamEvent(payload);
    };
    source.onerror = () => {
      if (eventSourceRef.current !== source) {
        return;
      }
      setErrorMessage(
        "The live event stream disconnected before the session completed.",
      );
      setSessionStatus("error");
      source.close();
      eventSourceRef.current = null;
    };
    eventSourceRef.current = source;
  }

  const agentCards = Object.values(agents);

  return (
    <main className="shell">
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Concurrent TinyFish Search</p>
          <h1>Search once. Watch every ticket site agent move in parallel.</h1>
          <p className="lede">
            Gemini finds the provider shortlist, TinyFish fans out across the web,
            and the dashboard streams each agent as it works.
          </p>
        </div>
        <form className="search-panel" onSubmit={handleSubmit}>
          <label className="field field-large">
            <span>Search</span>
            <input
              value={form.searchText}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  searchText: event.target.value,
                }))
              }
              placeholder="Universal Studios Japan tickets, Alcatraz tour San Francisco, Tokyo museum tickets..."
              required
              disabled={isRunning}
            />
          </label>

          <div className="field-grid">
            <label className="field">
              <span>Date</span>
              <input
                type="date"
                value={form.dateHint}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    dateHint: event.target.value,
                  }))
                }
                disabled={isRunning}
              />
            </label>
            <label className="field">
              <span>Currency</span>
              <select
                value={form.currency}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    currency: event.target.value,
                  }))
                }
                disabled={isRunning}
                className={form.currency ? "" : "placeholder-select"}
              >
                <option value="">Choose currency</option>
                {CURRENCY_OPTIONS.map((currency) => (
                  <option key={currency} value={currency}>
                    {currency}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Providers</span>
              <input
                type="number"
                min={3}
                max={5}
                value={form.providerLimit}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    providerLimit: Number(event.target.value),
                  }))
                }
                disabled={isRunning}
              />
            </label>
            <label className="field">
              <span>Results per site</span>
              <input
                type="number"
                min={1}
                max={10}
                value={form.maxResults}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    maxResults: Number(event.target.value),
                  }))
                }
                disabled={isRunning}
              />
            </label>
            <label className="field checkbox-field">
              <span>Stealth profile</span>
              <input
                type="checkbox"
                checked={form.stealth}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    stealth: event.target.checked,
                  }))
                }
                disabled={isRunning}
              />
            </label>
          </div>

          <button className="search-button" type="submit" disabled={isRunning}>
            {sessionStatus === "running"
              ? "Scanning providers..."
              : "Launch concurrent search"}
          </button>

          <div className="status-row">
            <span className={`status-chip status-${sessionStatus}`}>
              {sessionStatus}
            </span>
            {sessionId ? (
              <span className="session-id">Session {sessionId}</span>
            ) : null}
          </div>
          {errorMessage ? <p className="error-banner">{errorMessage}</p> : null}
        </form>
      </section>

      <section className="providers-panel">
        <div className="section-heading">
          <h2>Provider shortlist</h2>
          <p>
            The grounded Gemini discovery pass picks the sites TinyFish will
            search in parallel.
          </p>
        </div>
        <div className="provider-grid">
          {providers.length === 0 ? (
            <div className="empty-card">
              Provider discovery results will appear here once a search starts.
            </div>
          ) : (
            providers.map((provider) => (
              <article className="provider-card" key={provider.url}>
                <h3>{provider.provider_name}</h3>
                <p>{provider.why_relevant}</p>
                <a href={provider.url} target="_blank" rel="noreferrer">
                  {provider.url}
                </a>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="streams-panel">
        <div className="section-heading">
          <h2>Live agent streams</h2>
          <p>
            Each card tracks one TinyFish run. If TinyFish exposes a browser
            preview URL, it is embedded here.
          </p>
        </div>
        <div className="stream-grid">
          {agentCards.length === 0 ? (
            <div className="empty-card">
              Start a search to see concurrent TinyFish agents appear.
            </div>
          ) : (
            agentCards.map((agent) => (
              <article className="agent-card" key={agent.siteId}>
                <div className="agent-header">
                  <div>
                    <p className="agent-kicker">{agent.status}</p>
                    <h3>{agent.providerName}</h3>
                  </div>
                  <a href={agent.startUrl} target="_blank" rel="noreferrer">
                    open site
                  </a>
                </div>

                {agent.previewUrl ? (
                  <>
                    <iframe
                      className="stream-frame"
                      src={agent.previewUrl}
                      title={`${agent.providerName} live view`}
                    />
                    <a
                      className="stream-link"
                      href={agent.previewUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      open live TinyFish browser
                    </a>
                  </>
                ) : (
                  <div className="stream-placeholder">
                    <p>
                      {agent.status === "blocked"
                        ? "This provider appears to be blocking automation."
                        : "No embeddable stream URL yet."}
                    </p>
                    {agent.streamingUrl ? <code>{agent.streamingUrl}</code> : null}
                  </div>
                )}

                <div className="agent-meta">
                  {agent.runId ? <span>Run {agent.runId}</span> : null}
                  {typeof agent.resultCount === "number" ? (
                    <span>{agent.resultCount} results</span>
                  ) : null}
                </div>

                {agent.summary ? <p className="agent-summary">{agent.summary}</p> : null}
                {agent.error ? <p className="agent-error">{agent.error}</p> : null}
                {agent.recommendation ? (
                  <p className="agent-summary">{agent.recommendation}</p>
                ) : null}

                <ul className="progress-log">
                  {agent.progress.length === 0 ? (
                    <li>Waiting for progress events...</li>
                  ) : (
                    agent.progress.map((item, index) => (
                      <li key={`${agent.siteId}-${index}`}>{item}</li>
                    ))
                  )}
                </ul>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="results-panel">
        <div className="section-heading">
          <h2>Aggregated results</h2>
          <p>Combined deal summaries land here once the concurrent session finishes.</p>
        </div>

        {finalPayload ? (
          <div className="results-shell">
            <div className="results-summary">
              <h3>
                {finalPayload.search_query || finalPayload.searched_category}
              </h3>
              <p>{finalPayload.summary}</p>
            </div>

            <div className="site-results-grid">
              {finalPayload.site_results?.map((site) => (
                <article
                  className="site-result-card"
                  key={`${site.provider_name}-${site.start_url}`}
                >
                  <div className="agent-header">
                    <div>
                      <p className="agent-kicker">Site summary</p>
                      <h3>{site.provider_name}</h3>
                    </div>
                    <a href={site.start_url} target="_blank" rel="noreferrer">
                      visit
                    </a>
                  </div>
                  <p className="agent-summary">
                    {site.summary || site.error || "No summary returned."}
                  </p>
                  <div className="result-list">
                    {site.results.length === 0 ? (
                      <p className="muted-copy">No deals returned from this site.</p>
                    ) : (
                      site.results.map((result, index) => (
                        <div
                          className="result-item"
                          key={`${site.provider_name}-${index}`}
                        >
                          <h4>{result.title || "Untitled option"}</h4>
                          <p>
                            {result.price || "n/a"}{" "}
                            {result.original_price
                              ? `· was ${result.original_price}`
                              : ""}
                          </p>
                          <p>
                            {result.discount_text ||
                              result.short_reason_it_is_a_good_deal ||
                              "No extra detail."}
                          </p>
                          {result.booking_url ? (
                            <a
                              href={result.booking_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              booking link
                            </a>
                          ) : null}
                        </div>
                      ))
                    )}
                  </div>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <div className="empty-card">No aggregated results yet.</div>
        )}
      </section>
    </main>
  );
}
