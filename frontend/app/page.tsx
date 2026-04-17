"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

// ─── Shared Types ─────────────────────────────────────────────────────

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

// ─── Itinerary Types ──────────────────────────────────────────────────

type TravelIntent = {
	destination: string;
	travel_dates: string | null;
	duration_days: number | null;
	budget_range: string | null;
	currency: string;
	interests: string[];
	group_type: string | null;
	constraints: string[];
};

type PlannedTask = {
	task_id: string;
	query: string;
	day: number;
};

type ItineraryActivity = {
	time_of_day: string;
	title: string;
	provider: string;
	price: string;
	currency: string;
	booking_url: string;
	reason_selected: string;
	notes: string | null;
};

type ItineraryDay = {
	day_number: number;
	date: string | null;
	activities: ItineraryActivity[];
	estimated_cost: string | null;
	notes: string | null;
};

type ItineraryResult = {
	days: ItineraryDay[];
	total_estimated_cost: string;
	summary: string;
};

type PipelineStage =
	| "idle"
	| "extracting_intent"
	| "planning"
	| "searching"
	| "synthesizing"
	| "done"
	| "error";

type StreamEvent = {
	type: string;
	session_id?: string;
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
	query?: string;
	intent?: TravelIntent;
	destination?: string;
	task_count?: number;
	tasks?: PlannedTask[];
	task_id?: string;
	completed_count?: number;
	total_results?: number;
	day_count?: number;
	total_estimated_cost?: string;
};

// ─── Constants ────────────────────────────────────────────────────────

const API_BASE_URL =
	process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const CURRENCY_OPTIONS = ["USD", "EUR", "GBP", "SGD", "JPY", "KRW", "HKD"];

const INITIAL_SEARCH_FORM = {
	searchText: "",
	dateHint: "",
	currency: "",
	maxResults: 3,
	providerLimit: 4,
	blockMarketplaceProviders: true,
	stealth: false,
};

const PIPELINE_STAGE_DEFINITIONS: { key: PipelineStage; label: string }[] = [
	{ key: "extracting_intent", label: "Understanding" },
	{ key: "planning", label: "Planning" },
	{ key: "searching", label: "Searching" },
	{ key: "synthesizing", label: "Composing" },
];

const STAGE_STATUS_MESSAGES: Partial<Record<PipelineStage, string>> = {
	extracting_intent: "Analyzing your travel preferences...",
	planning: "Designing activities for each day...",
	searching: "Finding the best deals across the web...",
	synthesizing: "Crafting your personalized itinerary...",
};

// ─── Helpers ──────────────────────────────────────────────────────────

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
		[siteId]: { ...current, ...patch },
	};
}

function pipelineStageIndex(stage: PipelineStage): number {
	return PIPELINE_STAGE_DEFINITIONS.findIndex((s) => s.key === stage);
}

const TIME_OF_DAY_ORDER: Record<string, number> = {
	morning: 0,
	afternoon: 1,
	evening: 2,
};

function compareByTimeOfDay(
	a: ItineraryActivity,
	b: ItineraryActivity,
): number {
	const orderA = TIME_OF_DAY_ORDER[a.time_of_day.toLowerCase()] ?? 3;
	const orderB = TIME_OF_DAY_ORDER[b.time_of_day.toLowerCase()] ?? 3;
	return orderA - orderB;
}

// ─── Main Component ───────────────────────────────────────────────────

export default function HomePage() {
	const [activeTab, setActiveTab] = useState<"search" | "itinerary">(
		"itinerary",
	);

	// ── Search state ──
	const [searchForm, setSearchForm] = useState(INITIAL_SEARCH_FORM);
	const [searchSessionId, setSearchSessionId] = useState<string | null>(
		null,
	);
	const [searchStatus, setSearchStatus] = useState<
		"idle" | "running" | "done" | "error"
	>("idle");
	const [agents, setAgents] = useState<Record<string, AgentCardState>>({});
	const [providers, setProviders] = useState<Provider[]>([]);
	const [finalPayload, setFinalPayload] = useState<FinalPayload | null>(
		null,
	);
	const [searchError, setSearchError] = useState<string | null>(null);
	const searchEventSourceRef = useRef<EventSource | null>(null);

	// ── Itinerary state ──
	const [itineraryQuery, setItineraryQuery] = useState("");
	const [itineraryCurrency, setItineraryCurrency] = useState("USD");
	const [itinerarySessionId, setItinerarySessionId] = useState<
		string | null
	>(null);
	const [pipelineStage, setPipelineStage] =
		useState<PipelineStage>("idle");
	const [intent, setIntent] = useState<TravelIntent | null>(null);
	const [plannedTasks, setPlannedTasks] = useState<PlannedTask[]>([]);
	const [itineraryAgents, setItineraryAgents] = useState<
		Record<string, AgentCardState>
	>({});
	const [itineraryResult, setItineraryResult] =
		useState<ItineraryResult | null>(null);
	const [itineraryError, setItineraryError] = useState<string | null>(
		null,
	);
	const [searchCompletionStats, setSearchCompletionStats] = useState<{
		completed: number;
		totalResults: number;
	} | null>(null);

	const itineraryEventSourceRef = useRef<EventSource | null>(null);
	const itinerarySessionIdRef = useRef<string | null>(null);
	const synthesisCompleteRef = useRef(false);

	const isSearchRunning = searchStatus === "running";
	const isItineraryRunning =
		pipelineStage !== "idle" &&
		pipelineStage !== "done" &&
		pipelineStage !== "error";

	useEffect(() => {
		return () => {
			searchEventSourceRef.current?.close();
			itineraryEventSourceRef.current?.close();
		};
	}, []);

	// ── Fetch final itinerary via polling endpoint ──
	const fetchItineraryResult = useCallback(async (sessionId: string) => {
		try {
			const response = await fetch(
				`${API_BASE_URL}/api/itinerary/${sessionId}`,
			);
			if (!response.ok) {
				throw new Error(
					`Failed to fetch itinerary: ${response.statusText}`,
				);
			}
			const data = await response.json();
			if (data.done && data.result) {
				setItineraryResult(data.result as ItineraryResult);
				setPipelineStage("done");
			} else if (data.error) {
				setItineraryError(data.error);
				setPipelineStage("error");
			}
		} catch (err) {
			setItineraryError(
				err instanceof Error
					? err.message
					: "Failed to fetch itinerary result.",
			);
			setPipelineStage("error");
		}
	}, []);

	// ── Search SSE event handler ──
	function handleSearchEvent(event: StreamEvent) {
		if (event.type === "providers.discovered") {
			setProviders(event.providers ?? []);
			return;
		}

		if (event.type === "session.completed" && event.payload) {
			setFinalPayload(event.payload);
			setSearchStatus("done");
			searchEventSourceRef.current?.close();
			searchEventSourceRef.current = null;
			return;
		}

		if (event.type === "session.failed") {
			setSearchError(event.error ?? "Search session failed.");
			setSearchStatus("error");
			searchEventSourceRef.current?.close();
			searchEventSourceRef.current = null;
			return;
		}

		if (!event.site_id) return;
		const siteId = event.site_id;

		switch (event.type) {
			case "agent.queued":
				setAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Queued provider",
						startUrl: event.start_url ?? "",
						status: "queued",
					}),
				);
				break;
			case "agent.started":
				setAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Running provider",
						startUrl: event.start_url ?? "",
						runId: event.run_id,
						status: "running",
					}),
				);
				break;
			case "agent.streaming_url":
				setAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Running provider",
						streamingUrl: event.streaming_url,
						previewUrl: event.preview_url,
						status: "streaming",
					}),
				);
				break;
			case "agent.progress":
				setAgents((prev) => {
					const next = upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Running provider",
						status: "running",
					});
					const card = next[siteId];
					return {
						...next,
						[siteId]: {
							...card,
							progress: [
								...card.progress,
								event.purpose ?? "Working...",
							].slice(-12),
						},
					};
				});
				break;
			case "agent.retrying":
				setAgents((prev) => {
					const next = upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Retrying provider",
						status: "retrying",
						error: event.error,
					});
					const card = next[siteId];
					const retryLabel =
						event.attempt && event.max_attempts
							? `Retrying after attempt ${event.attempt} of ${event.max_attempts}.`
							: "Retrying after a transient connection error.";
					return {
						...next,
						[siteId]: {
							...card,
							progress: [...card.progress, retryLabel].slice(
								-12,
							),
						},
					};
				});
				break;
			case "agent.completed":
				setAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Completed provider",
						status: "completed",
						summary: event.summary,
						resultCount: event.result_count,
					}),
				);
				break;
			case "agent.failed":
				setAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Failed provider",
						status: "failed",
						error: event.error,
						recommendation: event.recommendation,
						failureCategory: event.failure_category,
					}),
				);
				break;
			case "agent.blocked":
				setAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Blocked provider",
						status: "blocked",
						error: event.error,
						recommendation: event.recommendation,
						failureCategory: event.failure_category,
					}),
				);
				break;
		}
	}

	// ── Itinerary inner-search agent event handler ──
	function handleItineraryAgentEvent(event: StreamEvent) {
		if (!event.site_id) return;
		const siteId = event.site_id;

		switch (event.type) {
			case "agent.queued":
				setItineraryAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Queued provider",
						startUrl: event.start_url ?? "",
						status: "queued",
					}),
				);
				break;
			case "agent.started":
				setItineraryAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Running provider",
						startUrl: event.start_url ?? "",
						runId: event.run_id,
						status: "running",
					}),
				);
				break;
			case "agent.streaming_url":
				setItineraryAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Running provider",
						streamingUrl: event.streaming_url,
						previewUrl: event.preview_url,
						status: "streaming",
					}),
				);
				break;
			case "agent.progress":
				setItineraryAgents((prev) => {
					const next = upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Running provider",
						status: "running",
					});
					const card = next[siteId];
					return {
						...next,
						[siteId]: {
							...card,
							progress: [
								...card.progress,
								event.purpose ?? "Working...",
							].slice(-12),
						},
					};
				});
				break;
			case "agent.completed":
				setItineraryAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Completed provider",
						status: "completed",
						summary: event.summary,
						resultCount: event.result_count,
					}),
				);
				break;
			case "agent.failed":
				setItineraryAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Failed provider",
						status: "failed",
						error: event.error,
					}),
				);
				break;
			case "agent.blocked":
				setItineraryAgents((prev) =>
					upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Blocked provider",
						status: "blocked",
						error: event.error,
					}),
				);
				break;
			case "agent.retrying":
				setItineraryAgents((prev) => {
					const next = upsertAgent(prev, siteId, {
						providerName:
							event.provider_name ?? "Retrying provider",
						status: "retrying",
					});
					const card = next[siteId];
					return {
						...next,
						[siteId]: {
							...card,
							progress: [
								...card.progress,
								"Retrying...",
							].slice(-12),
						},
					};
				});
				break;
		}
	}

	// ── Itinerary pipeline SSE event handler ──
	function handleItineraryEvent(event: StreamEvent) {
		switch (event.type) {
			case "intent.extraction_started":
				setPipelineStage("extracting_intent");
				break;
			case "intent.extraction_completed":
				if (event.intent) setIntent(event.intent);
				break;
			case "planner.started":
				setPipelineStage("planning");
				break;
			case "planner.completed":
				setPlannedTasks(event.tasks ?? []);
				break;
			case "searches.started":
				setPipelineStage("searching");
				break;
			case "searches.completed":
				setSearchCompletionStats({
					completed: event.completed_count ?? 0,
					totalResults: event.total_results ?? 0,
				});
				break;
			case "synthesis.started":
				setPipelineStage("synthesizing");
				break;
			case "synthesis.completed": {
				synthesisCompleteRef.current = true;
				const sessionId = itinerarySessionIdRef.current;
				if (sessionId) fetchItineraryResult(sessionId);
				break;
			}
			case "itinerary.failed":
				setItineraryError(
					event.error ?? "Itinerary planning failed.",
				);
				setPipelineStage("error");
				itineraryEventSourceRef.current?.close();
				itineraryEventSourceRef.current = null;
				break;
			default:
				if (event.site_id) handleItineraryAgentEvent(event);
				break;
		}
	}

	// ── Search submit ──
	async function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setSearchStatus("running");
		setSearchError(null);
		setSearchSessionId(null);
		setProviders([]);
		setFinalPayload(null);
		setAgents({});
		searchEventSourceRef.current?.close();

		let response: Response;
		try {
			response = await fetch(`${API_BASE_URL}/api/searches`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					category: searchForm.searchText.trim(),
					date_hint: searchForm.dateHint || null,
					currency: searchForm.currency || "USD",
					max_results: searchForm.maxResults,
					discover_providers: true,
					provider_limit: searchForm.providerLimit,
					block_marketplace_providers:
						searchForm.blockMarketplaceProviders,
					stealth: searchForm.stealth,
				}),
			});
		} catch {
			setSearchStatus("error");
			setSearchError(
				`Could not reach the backend at ${API_BASE_URL}. Start the FastAPI server and make sure the URL is correct.`,
			);
			return;
		}

		if (!response.ok) {
			const text = await response.text();
			setSearchStatus("error");
			setSearchError(text || "Failed to start the search session.");
			return;
		}

		const data = (await response.json()) as { session_id: string };
		setSearchSessionId(data.session_id);

		const source = new EventSource(
			`${API_BASE_URL}/api/searches/${data.session_id}/events`,
		);
		source.onmessage = (message) => {
			handleSearchEvent(JSON.parse(message.data) as StreamEvent);
		};
		source.onerror = () => {
			if (searchEventSourceRef.current !== source) return;
			setSearchError(
				"The live event stream disconnected before the session completed.",
			);
			setSearchStatus("error");
			source.close();
			searchEventSourceRef.current = null;
		};
		searchEventSourceRef.current = source;
	}

	// ── Itinerary submit ──
	async function handleItinerarySubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setPipelineStage("idle");
		setItineraryError(null);
		setItinerarySessionId(null);
		itinerarySessionIdRef.current = null;
		setIntent(null);
		setPlannedTasks([]);
		setItineraryAgents({});
		setItineraryResult(null);
		setSearchCompletionStats(null);
		synthesisCompleteRef.current = false;
		itineraryEventSourceRef.current?.close();

		let response: Response;
		try {
			response = await fetch(`${API_BASE_URL}/api/itinerary`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					query: itineraryQuery.trim(),
					currency: itineraryCurrency,
				}),
			});
		} catch {
			setPipelineStage("error");
			setItineraryError(
				`Could not reach the backend at ${API_BASE_URL}. Start the FastAPI server and make sure the URL is correct.`,
			);
			return;
		}

		if (!response.ok) {
			const text = await response.text();
			setPipelineStage("error");
			setItineraryError(
				text || "Failed to start the itinerary session.",
			);
			return;
		}

		const data = (await response.json()) as { session_id: string };
		setItinerarySessionId(data.session_id);
		itinerarySessionIdRef.current = data.session_id;
		setPipelineStage("extracting_intent");

		const source = new EventSource(
			`${API_BASE_URL}/api/itinerary/${data.session_id}/events`,
		);
		source.onmessage = (message) => {
			handleItineraryEvent(JSON.parse(message.data) as StreamEvent);
		};
		source.onerror = () => {
			if (itineraryEventSourceRef.current !== source) return;
			if (synthesisCompleteRef.current) {
				source.close();
				itineraryEventSourceRef.current = null;
				return;
			}
			setItineraryError(
				"The live event stream disconnected unexpectedly.",
			);
			setPipelineStage("error");
			source.close();
			itineraryEventSourceRef.current = null;
		};
		itineraryEventSourceRef.current = source;
	}

	// ── Derived ──
	const agentCards = Object.values(agents);
	const itineraryAgentCards = Object.values(itineraryAgents);
	const currentStageIndex = pipelineStageIndex(pipelineStage);

	return (
		<main className="shell">
			<nav className="tab-nav">
				<span className="brand">TravellingFish</span>
				<div className="tab-buttons">
					<button
						className={`tab-button ${activeTab === "itinerary" ? "active" : ""}`}
						onClick={() => setActiveTab("itinerary")}
					>
						Itinerary Planner
					</button>
					<button
						className={`tab-button ${activeTab === "search" ? "active" : ""}`}
						onClick={() => setActiveTab("search")}
					>
						Deal Search
					</button>
				</div>
			</nav>

			{/* ─── Itinerary Tab ─── */}
			{activeTab === "itinerary" && (
				<>
					<section className="hero">
						<div className="hero-copy">
							<p className="eyebrow">AI Itinerary Planner</p>
							<h2 className="hero-title">
								Plan your perfect trip.
							</h2>
							<p className="lede">
								Describe your dream trip and our AI will
								research activities, compare providers, and
								build a day-by-day itinerary with real prices
								and booking links.
							</p>
						</div>
						<form
							className="search-panel"
							onSubmit={handleItinerarySubmit}
						>
							<label className="field field-large">
								<span>Describe your trip</span>
								<input
									value={itineraryQuery}
									onChange={(e) =>
										setItineraryQuery(e.target.value)
									}
									placeholder="5 day Kyoto trip for a couple interested in culture and food"
									required
									disabled={isItineraryRunning}
								/>
							</label>
							<div className="field-grid">
								<label className="field">
									<span>Currency</span>
									<select
										value={itineraryCurrency}
										onChange={(e) =>
											setItineraryCurrency(
												e.target.value,
											)
										}
										disabled={isItineraryRunning}
									>
										{CURRENCY_OPTIONS.map((c) => (
											<option key={c} value={c}>
												{c}
											</option>
										))}
									</select>
								</label>
							</div>
							<button
								className="search-button"
								type="submit"
								disabled={isItineraryRunning}
							>
								{isItineraryRunning
									? "Planning your trip..."
									: "Plan my itinerary"}
							</button>
							{itinerarySessionId && (
								<div className="status-row">
									<span
										className={`status-chip status-${pipelineStage === "done" ? "done" : pipelineStage === "error" ? "error" : "running"}`}
									>
										{pipelineStage === "idle"
											? "ready"
											: pipelineStage.replace(/_/g, " ")}
									</span>
									<span className="session-id">
										Session {itinerarySessionId}
									</span>
								</div>
							)}
							{itineraryError && (
								<p className="error-banner">
									{itineraryError}
								</p>
							)}
						</form>
					</section>

					{pipelineStage !== "idle" && (
						<section className="pipeline-tracker-section">
							<div className="pipeline-tracker">
								{PIPELINE_STAGE_DEFINITIONS.map(
									(stage, index) => {
										const isCompleted =
											pipelineStage === "done" ||
											currentStageIndex > index;
										const isActive =
											currentStageIndex === index;
										return (
											<div
												key={stage.key}
												className={`pipeline-stage${isCompleted ? " completed" : ""}${isActive ? " active" : ""}`}
											>
												<div className="stage-indicator">
													{isCompleted ? (
														<svg
															viewBox="0 0 24 24"
															fill="none"
															stroke="currentColor"
															strokeWidth="3"
														>
															<polyline points="20 6 9 17 4 12" />
														</svg>
													) : (
														<span>
															{index + 1}
														</span>
													)}
												</div>
												<span className="stage-label">
													{stage.label}
												</span>
											</div>
										);
									},
								)}
							</div>
							{STAGE_STATUS_MESSAGES[pipelineStage] && (
								<p className="pipeline-status-message">
									{STAGE_STATUS_MESSAGES[pipelineStage]}
								</p>
							)}
						</section>
					)}

					{intent && (
						<section className="intent-section">
							<div className="section-heading">
								<h2>Trip Overview</h2>
							</div>
							<div className="intent-card">
								<div className="intent-grid">
									<div className="intent-field">
										<span className="intent-label">
											Destination
										</span>
										<span className="intent-value">
											{intent.destination}
										</span>
									</div>
									{intent.travel_dates && (
										<div className="intent-field">
											<span className="intent-label">
												Dates
											</span>
											<span className="intent-value">
												{intent.travel_dates}
											</span>
										</div>
									)}
									{intent.duration_days && (
										<div className="intent-field">
											<span className="intent-label">
												Duration
											</span>
											<span className="intent-value">
												{intent.duration_days} days
											</span>
										</div>
									)}
									{intent.budget_range && (
										<div className="intent-field">
											<span className="intent-label">
												Budget
											</span>
											<span className="intent-value">
												{intent.budget_range}
											</span>
										</div>
									)}
									{intent.group_type && (
										<div className="intent-field">
											<span className="intent-label">
												Travelers
											</span>
											<span className="intent-value">
												{intent.group_type}
											</span>
										</div>
									)}
								</div>
								{intent.interests.length > 0 && (
									<div className="intent-tags">
										{intent.interests.map((interest) => (
											<span
												key={interest}
												className="interest-tag"
											>
												{interest}
											</span>
										))}
									</div>
								)}
								{intent.constraints.length > 0 && (
									<div className="intent-tags">
										{intent.constraints.map(
											(constraint) => (
												<span
													key={constraint}
													className="constraint-tag"
												>
													{constraint}
												</span>
											),
										)}
									</div>
								)}
							</div>
						</section>
					)}

					{plannedTasks.length > 0 && (
						<section className="tasks-section">
							<div className="section-heading">
								<h2>Search Plan</h2>
								<p>
									{plannedTasks.length}{" "}
									{plannedTasks.length === 1
										? "activity"
										: "activities"}{" "}
									to research across your trip
								</p>
							</div>
							<div className="task-list">
								{plannedTasks.map((task) => (
									<div
										key={task.task_id}
										className="task-item"
									>
										<span className="task-day">
											Day {task.day}
										</span>
										<span className="task-query">
											{task.query}
										</span>
									</div>
								))}
							</div>
						</section>
					)}

					{pipelineStage === "searching" &&
						itineraryAgentCards.length > 0 && (
							<section className="streams-panel">
								<div className="section-heading">
									<h2>Searching Providers</h2>
									<p>
										TinyFish agents are browsing the web for
										the best deals
									</p>
								</div>
								<div className="stream-grid">
									{itineraryAgentCards.map((agent) => (
										<article
											className="agent-card"
											key={agent.siteId}
										>
											<div className="agent-header">
												<div>
													<p className="agent-kicker">
														{agent.status}
													</p>
													<h3>
														{agent.providerName}
													</h3>
												</div>
												{agent.startUrl && (
													<a
														href={agent.startUrl}
														target="_blank"
														rel="noreferrer"
													>
														open site
													</a>
												)}
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
														open live TinyFish
														browser
													</a>
												</>
											) : (
												<div className="stream-placeholder">
													<p>
														{agent.status ===
														"blocked"
															? "This provider appears to be blocking automation."
															: "No embeddable stream URL yet."}
													</p>
													{agent.streamingUrl && (
														<code>
															{
																agent.streamingUrl
															}
														</code>
													)}
												</div>
											)}
											<div className="agent-meta">
												{agent.runId && (
													<span>
														Run {agent.runId}
													</span>
												)}
												{typeof agent.resultCount ===
													"number" && (
													<span>
														{agent.resultCount}{" "}
														results
													</span>
												)}
											</div>
											{agent.summary && (
												<p className="agent-summary">
													{agent.summary}
												</p>
											)}
											{agent.error && (
												<p className="agent-error">
													{agent.error}
												</p>
											)}
											<ul className="progress-log">
												{agent.progress.length ===
												0 ? (
													<li>
														Waiting for progress
														events...
													</li>
												) : (
													agent.progress.map(
														(item, i) => (
															<li
																key={`${agent.siteId}-${i}`}
															>
																{item}
															</li>
														),
													)
												)}
											</ul>
										</article>
									))}
								</div>
							</section>
						)}

					{searchCompletionStats && pipelineStage !== "idle" && (
						<div className="search-stats-banner">
							Searched {searchCompletionStats.completed}{" "}
							{searchCompletionStats.completed === 1
								? "task"
								: "tasks"}{" "}
							and found {searchCompletionStats.totalResults}{" "}
							{searchCompletionStats.totalResults === 1
								? "result"
								: "results"}
						</div>
					)}

					{itineraryResult && (
						<section className="itinerary-result-section">
							<div className="section-heading">
								<h2>Your Itinerary</h2>
							</div>

							<div className="itinerary-summary-card">
								<p className="itinerary-summary-text">
									{itineraryResult.summary}
								</p>
								<div className="itinerary-total-cost">
									<span className="cost-label">
										Estimated total
									</span>
									<span className="cost-value">
										{itineraryResult.total_estimated_cost}
									</span>
								</div>
							</div>

							<div className="itinerary-days">
								{itineraryResult.days.map((day) => (
									<article
										key={day.day_number}
										className="day-card"
									>
										<div className="day-header">
											<div className="day-title-group">
												<h3 className="day-number">
													Day {day.day_number}
												</h3>
												{day.date && (
													<span className="day-date">
														{day.date}
													</span>
												)}
											</div>
											{day.estimated_cost && (
												<span className="day-cost">
													{day.estimated_cost}
												</span>
											)}
										</div>

										<div className="day-activities">
											{[...day.activities]
												.sort(compareByTimeOfDay)
												.map((activity, actIndex) => (
													<div
														key={`d${day.day_number}-${actIndex}`}
														className="activity-item"
													>
														<div className="activity-time-col">
															<span
																className={`time-badge time-${activity.time_of_day.toLowerCase()}`}
															>
																{
																	activity.time_of_day
																}
															</span>
														</div>
														<div className="activity-content">
															<h4 className="activity-title">
																{activity.title}
															</h4>
															<div className="activity-meta-row">
																<span className="activity-provider">
																	{
																		activity.provider
																	}
																</span>
																<span className="activity-price">
																	{
																		activity.price
																	}
																</span>
															</div>
															<p className="activity-reason">
																{
																	activity.reason_selected
																}
															</p>
															{activity.notes && (
																<p className="activity-notes">
																	{
																		activity.notes
																	}
																</p>
															)}
															{activity.booking_url && (
																<a
																	className="booking-link"
																	href={
																		activity.booking_url
																	}
																	target="_blank"
																	rel="noreferrer"
																>
																	Book now
																</a>
															)}
														</div>
													</div>
												))}
										</div>

										{day.notes && (
											<p className="day-notes">
												{day.notes}
											</p>
										)}
									</article>
								))}
							</div>
						</section>
					)}
				</>
			)}

			{/* ─── Search Tab ─── */}
			{activeTab === "search" && (
				<>
					<section className="hero">
						<div className="hero-copy">
							<p className="eyebrow">
								Concurrent TinyFish Search
							</p>
							<h2 className="hero-title">
								Search once. See every option.
							</h2>
							<p className="lede">
								Gemini finds the provider shortlist, TinyFish
								fans out across the web, and the dashboard
								streams each agent as it works.
							</p>
						</div>
						<form
							className="search-panel"
							onSubmit={handleSearchSubmit}
						>
							<label className="field field-large">
								<span>Search</span>
								<input
									value={searchForm.searchText}
									onChange={(e) =>
										setSearchForm((c) => ({
											...c,
											searchText: e.target.value,
										}))
									}
									placeholder="Universal Studios Japan express tickets, Singapore Zoo child ticket"
									required
									disabled={isSearchRunning}
								/>
							</label>
							<div className="field-grid">
								<label className="field">
									<span>Date</span>
									<input
										type="date"
										value={searchForm.dateHint}
										onChange={(e) =>
											setSearchForm((c) => ({
												...c,
												dateHint: e.target.value,
											}))
										}
										disabled={isSearchRunning}
									/>
								</label>
								<label className="field">
									<span>Currency</span>
									<select
										value={searchForm.currency}
										onChange={(e) =>
											setSearchForm((c) => ({
												...c,
												currency: e.target.value,
											}))
										}
										disabled={isSearchRunning}
										className={
											searchForm.currency
												? ""
												: "placeholder-select"
										}
									>
										<option value="">
											Choose currency
										</option>
										{CURRENCY_OPTIONS.map((c) => (
											<option key={c} value={c}>
												{c}
											</option>
										))}
									</select>
								</label>
								<label className="field">
									<span>Providers</span>
									<input
										type="number"
										min={1}
										max={10}
										value={searchForm.providerLimit}
										onChange={(e) =>
											setSearchForm((c) => ({
												...c,
												providerLimit: Number(
													e.target.value,
												),
											}))
										}
										disabled={isSearchRunning}
									/>
								</label>
								<label className="field">
									<span>Results per site</span>
									<input
										type="number"
										min={1}
										max={10}
										value={searchForm.maxResults}
										onChange={(e) =>
											setSearchForm((c) => ({
												...c,
												maxResults: Number(
													e.target.value,
												),
											}))
										}
										disabled={isSearchRunning}
									/>
								</label>
								<label className="field checkbox-field">
									<span>Direct providers only</span>
									<input
										type="checkbox"
										checked={
											searchForm.blockMarketplaceProviders
										}
										onChange={(e) =>
											setSearchForm((c) => ({
												...c,
												blockMarketplaceProviders:
													e.target.checked,
											}))
										}
										disabled={isSearchRunning}
									/>
								</label>
								<label className="field checkbox-field">
									<span>Stealth profile</span>
									<input
										type="checkbox"
										checked={searchForm.stealth}
										onChange={(e) =>
											setSearchForm((c) => ({
												...c,
												stealth: e.target.checked,
											}))
										}
										disabled={isSearchRunning}
									/>
								</label>
							</div>
							<button
								className="search-button"
								type="submit"
								disabled={isSearchRunning}
							>
								{searchStatus === "running"
									? "Scanning providers..."
									: "Launch concurrent search"}
							</button>
							<div className="status-row">
								<span
									className={`status-chip status-${searchStatus}`}
								>
									{searchStatus}
								</span>
								{searchSessionId && (
									<span className="session-id">
										Session {searchSessionId}
									</span>
								)}
							</div>
							{searchError && (
								<p className="error-banner">{searchError}</p>
							)}
						</form>
					</section>

					<section className="providers-panel">
						<div className="section-heading">
							<h2>Website Shortlist</h2>
							<p>
								The grounded Gemini discovery pass picks the
								sites TinyFish will search in parallel.
							</p>
						</div>
						<div className="provider-grid">
							{providers.length === 0 ? (
								<div className="empty-card">
									Provider discovery results will appear here
									once a search starts.
								</div>
							) : (
								providers.map((provider) => (
									<article
										className="provider-card"
										key={provider.url}
									>
										<h3>{provider.provider_name}</h3>
										<p>{provider.why_relevant}</p>
										<a
											href={provider.url}
											target="_blank"
											rel="noreferrer"
										>
											{provider.url}
										</a>
									</article>
								))
							)}
						</div>
					</section>

					<section className="streams-panel">
						<div className="section-heading">
							<h2>Live Agent Streams</h2>
							<p>
								Each card tracks one TinyFish run. If TinyFish
								exposes a browser preview URL, it is embedded
								here.
							</p>
						</div>
						<div className="stream-grid">
							{agentCards.length === 0 ? (
								<div className="empty-card">
									Start a search to see concurrent TinyFish
									agents appear.
								</div>
							) : (
								agentCards.map((agent) => (
									<article
										className="agent-card"
										key={agent.siteId}
									>
										<div className="agent-header">
											<div>
												<p className="agent-kicker">
													{agent.status}
												</p>
												<h3>{agent.providerName}</h3>
											</div>
											<a
												href={agent.startUrl}
												target="_blank"
												rel="noreferrer"
											>
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
												{agent.streamingUrl && (
													<code>
														{agent.streamingUrl}
													</code>
												)}
											</div>
										)}
										<div className="agent-meta">
											{agent.runId && (
												<span>
													Run {agent.runId}
												</span>
											)}
											{typeof agent.resultCount ===
												"number" && (
												<span>
													{agent.resultCount} results
												</span>
											)}
										</div>
										{agent.summary && (
											<p className="agent-summary">
												{agent.summary}
											</p>
										)}
										{agent.error && (
											<p className="agent-error">
												{agent.error}
											</p>
										)}
										{agent.recommendation && (
											<p className="agent-summary">
												{agent.recommendation}
											</p>
										)}
										<ul className="progress-log">
											{agent.progress.length === 0 ? (
												<li>
													Waiting for progress
													events...
												</li>
											) : (
												agent.progress.map(
													(item, i) => (
														<li
															key={`${agent.siteId}-${i}`}
														>
															{item}
														</li>
													),
												)
											)}
										</ul>
									</article>
								))
							)}
						</div>
					</section>

					<section className="results-panel">
						<div className="section-heading">
							<h2>Results</h2>
							<p>
								Deal summaries land here once the concurrent
								session finishes.
							</p>
						</div>
						{finalPayload ? (
							<div className="results-shell">
								<div className="results-summary">
									<h3>
										{finalPayload.search_query ||
											finalPayload.searched_category}
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
													<p className="agent-kicker">
														Site summary
													</p>
													<h3>
														{site.provider_name}
													</h3>
												</div>
												<a
													href={site.start_url}
													target="_blank"
													rel="noreferrer"
												>
													visit
												</a>
											</div>
											<p className="agent-summary">
												{site.summary ||
													site.error ||
													"No summary returned."}
											</p>
											<div className="result-list">
												{site.results.length === 0 ? (
													<p className="muted-copy">
														No deals returned from
														this site.
													</p>
												) : (
													site.results.map(
														(result, i) => (
															<div
																className="result-item"
																key={`${site.provider_name}-${i}`}
															>
																<h4>
																	{result.title ||
																		"Untitled option"}
																</h4>
																<p>
																	{result.price ||
																		"n/a"}{" "}
																	{result.original_price
																		? `\u00B7 was ${result.original_price}`
																		: ""}
																</p>
																<p>
																	{result.discount_text ||
																		result.short_reason_it_is_a_good_deal ||
																		"No extra detail."}
																</p>
																{result.booking_url && (
																	<a
																		href={
																			result.booking_url
																		}
																		target="_blank"
																		rel="noreferrer"
																	>
																		booking
																		link
																	</a>
																)}
															</div>
														),
													)
												)}
											</div>
										</article>
									))}
								</div>
							</div>
						) : (
							<div className="empty-card">
								No aggregated results yet.
							</div>
						)}
					</section>
				</>
			)}
		</main>
	);
}
