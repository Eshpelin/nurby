"use client";

import { useCallback, useEffect, useState } from "react";

interface Camera {
  id: string;
  name: string;
}

interface Person {
  id: string;
  display_name: string;
}

interface SearchResult {
  id: string;
  camera_id: string;
  camera_name: string;
  started_at: string;
  object_detections: { objects: { label: string; confidence: number }[]; count: number } | null;
  person_detections: { faces: { person_name: string | null; person_id: string | null }[]; count: number } | null;
  vlm_description: string | null;
  confidence: number | null;
  thumbnail_path: string | null;
}

const OBJECT_LABELS = [
  "person", "car", "truck", "bicycle", "motorcycle",
  "dog", "cat", "bird", "backpack", "handbag",
  "suitcase", "umbrella",
];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  // Filters
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [filterCamera, setFilterCamera] = useState("");
  const [filterPerson, setFilterPerson] = useState("");
  const [filterObject, setFilterObject] = useState("");
  const [filterTimeFrom, setFilterTimeFrom] = useState("");
  const [filterTimeTo, setFilterTimeTo] = useState("");
  const [showFilters, setShowFilters] = useState(false);

  // AI answer
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiNote, setAiNote] = useState<string | null>(null);
  const [askingAi, setAskingAi] = useState(false);

  // Expanded result
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/cameras").then((r) => r.ok ? r.json() : []).then(setCameras).catch(() => {});
    fetch("/api/persons").then((r) => r.ok ? r.json() : []).then(setPersons).catch(() => {});
  }, []);

  const handleSearch = useCallback(async () => {
    setSearching(true);
    setHasSearched(true);
    setAiAnswer(null);
    setAiNote(null);

    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (filterCamera) params.set("camera_id", filterCamera);
    if (filterPerson) params.set("person", filterPerson);
    if (filterObject) params.set("object", filterObject);
    if (filterTimeFrom) params.set("time_from", new Date(filterTimeFrom).toISOString());
    if (filterTimeTo) params.set("time_to", new Date(filterTimeTo).toISOString());

    try {
      const res = await fetch(`/api/search?${params}`);
      if (res.ok) {
        const data = await res.json();
        setResults(data.results);
      }
    } catch {
      /* silent */
    } finally {
      setSearching(false);
    }
  }, [query, filterCamera, filterPerson, filterObject, filterTimeFrom, filterTimeTo]);

  const handleAskAi = async () => {
    if (!query.trim()) return;
    setAskingAi(true);
    try {
      const res = await fetch("/api/search/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query.trim() }),
      });
      if (res.ok) {
        const data = await res.json();
        setAiAnswer(data.answer);
        setAiNote(data.note || null);
        if (data.sources?.length > 0 && results.length === 0) {
          setResults(data.sources);
        }
      }
    } catch {
      /* silent */
    } finally {
      setAskingAi(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleSearch();
    }
  };

  const activeFilterCount = [filterCamera, filterPerson, filterObject, filterTimeFrom, filterTimeTo].filter(Boolean).length;

  return (
    <div className="px-6 py-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight mb-1">
          Search your footage
        </h1>
        <p className="text-sm text-muted-foreground">
          Ask anything about what has happened across your cameras
        </p>
      </div>

      {/* Search bar */}
      <div className="relative mb-3">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="when did the fedex driver come this week"
          className="w-full bg-card border border-border focus:border-accent rounded-lg pl-12 pr-28 py-4 text-base focus:outline-none transition-colors"
        />
        <svg
          className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2">
          {query.trim() && (
            <button
              onClick={handleAskAi}
              disabled={askingAi}
              className="px-2 py-1 text-xs rounded bg-accent text-black font-medium hover:opacity-90 disabled:opacity-50"
            >
              {askingAi ? "Thinking." : "Ask AI"}
            </button>
          )}
          <button
            onClick={handleSearch}
            disabled={searching}
            className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-muted border border-border text-muted-foreground hover:bg-border transition-colors"
          >
            {searching ? "..." : "search"}
          </button>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`px-3 py-1 text-xs rounded-full border transition-colors ${
            showFilters || activeFilterCount > 0
              ? "border-accent text-accent"
              : "border-border text-muted-foreground hover:bg-muted"
          }`}
        >
          Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>
        {filterCamera && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-muted border border-border flex items-center gap-1">
            {cameras.find((c) => c.id === filterCamera)?.name || "Camera"}
            <button onClick={() => setFilterCamera("")} className="text-muted-foreground hover:text-foreground">x</button>
          </span>
        )}
        {filterPerson && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-muted border border-border flex items-center gap-1">
            {filterPerson}
            <button onClick={() => setFilterPerson("")} className="text-muted-foreground hover:text-foreground">x</button>
          </span>
        )}
        {filterObject && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-muted border border-border flex items-center gap-1">
            {filterObject}
            <button onClick={() => setFilterObject("")} className="text-muted-foreground hover:text-foreground">x</button>
          </span>
        )}
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className="rounded-lg border border-border bg-card p-4 mb-6 grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Camera</label>
            <select
              value={filterCamera}
              onChange={(e) => setFilterCamera(e.target.value)}
              className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
            >
              <option value="">All cameras</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Person</label>
            <select
              value={filterPerson}
              onChange={(e) => setFilterPerson(e.target.value)}
              className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
            >
              <option value="">Any person</option>
              {persons.map((p) => (
                <option key={p.id} value={p.display_name}>{p.display_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Object</label>
            <select
              value={filterObject}
              onChange={(e) => setFilterObject(e.target.value)}
              className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-sm"
            >
              <option value="">Any object</option>
              {OBJECT_LABELS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground block mb-1">Time range</label>
            <div className="flex gap-1">
              <input
                type="datetime-local"
                value={filterTimeFrom}
                onChange={(e) => setFilterTimeFrom(e.target.value)}
                className="w-full px-1.5 py-1.5 rounded-md bg-background border border-border text-xs"
              />
              <input
                type="datetime-local"
                value={filterTimeTo}
                onChange={(e) => setFilterTimeTo(e.target.value)}
                className="w-full px-1.5 py-1.5 rounded-md bg-background border border-border text-xs"
              />
            </div>
          </div>
        </div>
      )}

      {/* AI Answer */}
      {aiAnswer && (
        <div className="rounded-lg border border-accent/40 bg-accent/5 p-4 mb-6">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" />
            <span className="text-xs font-medium text-accent uppercase tracking-wider">
              AI Answer
            </span>
          </div>
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{aiAnswer}</p>
        </div>
      )}
      {aiNote && !aiAnswer && (
        <div className="rounded-lg border border-border bg-card p-3 mb-6">
          <p className="text-xs text-muted-foreground">{aiNote}</p>
        </div>
      )}

      {/* Results */}
      {!hasSearched ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <p className="text-muted-foreground text-sm">
            Type a query and press enter to search your observation history.
            Use filters to narrow by camera, person, object, or time range.
          </p>
        </div>
      ) : searching ? (
        <div className="text-sm text-muted-foreground py-16 text-center">
          Searching.
        </div>
      ) : results.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <p className="text-muted-foreground text-sm">
            No observations match your search. Try broadening your query or adjusting filters.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground mb-3">
            {results.length} result{results.length !== 1 ? "s" : ""}
          </div>
          {results.map((r) => (
            <div
              key={r.id}
              onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
              className="rounded-lg border border-border bg-card p-4 cursor-pointer hover:border-muted-foreground/30 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-medium">{r.camera_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(r.started_at).toLocaleString()}
                    </span>
                  </div>
                  {r.vlm_description && (
                    <p className="text-sm text-foreground/80 mb-2 line-clamp-2">
                      {r.vlm_description}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-1">
                    {r.object_detections?.objects?.map((obj, i) => (
                      <span
                        key={i}
                        className="px-1.5 py-0.5 text-[10px] rounded bg-blue-900/30 text-blue-300 border border-blue-800/40"
                      >
                        {obj.label} {Math.round(obj.confidence * 100)}%
                      </span>
                    ))}
                    {r.person_detections?.faces?.map((face, i) => (
                      <span
                        key={`f${i}`}
                        className={`px-1.5 py-0.5 text-[10px] rounded border ${
                          face.person_name
                            ? "bg-green-900/30 text-green-300 border-green-800/40"
                            : "bg-yellow-900/30 text-yellow-300 border-yellow-800/40"
                        }`}
                      >
                        {face.person_name || "Unknown face"}
                      </span>
                    ))}
                  </div>
                </div>
                {r.thumbnail_path && (
                  <img
                    src={`/api/observations/${r.id}/thumbnail`}
                    alt=""
                    className="w-20 h-14 rounded object-cover border border-border ml-3 flex-shrink-0"
                  />
                )}
              </div>

              {/* Expanded details */}
              {expandedId === r.id && (
                <div className="mt-3 pt-3 border-t border-border space-y-2">
                  {r.thumbnail_path && (
                    <img
                      src={`/api/observations/${r.id}/thumbnail`}
                      alt=""
                      className="w-full max-w-md rounded border border-border"
                    />
                  )}
                  {r.vlm_description && (
                    <div>
                      <span className="text-xs text-muted-foreground">VLM Description</span>
                      <p className="text-sm">{r.vlm_description}</p>
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-muted-foreground">Camera</span>
                      <div>{r.camera_name}</div>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Time</span>
                      <div>{new Date(r.started_at).toLocaleString()}</div>
                    </div>
                    {r.confidence !== null && (
                      <div>
                        <span className="text-muted-foreground">Confidence</span>
                        <div>{Math.round(r.confidence * 100)}%</div>
                      </div>
                    )}
                    <div>
                      <span className="text-muted-foreground">Objects</span>
                      <div>{r.object_detections?.count || 0} detected</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
