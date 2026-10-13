"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpDown,
  CheckCircle2,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  Filter,
  Layers,
  MapPin,
  RefreshCw,
  Search,
  Sparkles,
  TrendingUp,
  UploadCloud,
  X,
} from "lucide-react";
import { EChart } from "@/components/charts/EChart";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { PageHeader, Section } from "@/components/ui/PageHeader";
import { ProvenanceBadge } from "@/components/ui/ProvenanceBadge";
import {
  downloadBatchPdf,
  downloadClientCsv,
  downloadEnrichedCsv,
  postBatchCsvFile,
  postBatchCsvText,
  type BatchLocationRow,
  type BatchResult,
} from "@/lib/air/batch";
import { SAMPLE_INDIA_COORDINATES_CSV } from "@/lib/air/sampleCoordinates";

const PAGE_SIZE = 25;

export default function BatchAirQualityPage() {
  const [inputMode, setInputMode] = useState<"upload" | "paste">("paste");
  const [file, setFile] = useState<File | null>(null);
  const [csvText, setCsvText] = useState<string>(SAMPLE_INDIA_COORDINATES_CSV);
  const [forecastHours, setForecastHours] = useState<number>(24);
  const [chunkSize, setChunkSize] = useState<number>(100);
  const [apiKey, setApiKey] = useState<string>("");
  const [showApiKey, setShowApiKey] = useState<boolean>(false);
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [forceRefresh, setForceRefresh] = useState<boolean>(false);
  const [showHourlyOptions, setShowHourlyOptions] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [pdfLoading, setPdfLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [activeCsvContent, setActiveCsvContent] = useState<string>(SAMPLE_INDIA_COORDINATES_CSV);

  // Filters & sorting
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedState, setSelectedState] = useState<string>("ALL");
  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");
  const [sortBy, setSortBy] = useState<"pm25_desc" | "pm25_asc" | "place_asc" | "state_asc">("pm25_desc");
  const [page, setPage] = useState<number>(1);

  // Detail Modal for specific location trend
  const [selectedRow, setSelectedRow] = useState<BatchLocationRow | null>(null);

  // Execution
  async function handleSubmit() {
    setError(null);
    setLoading(true);
    setPage(1);

    try {
      let res: BatchResult;
      const opts = {
        forecastHours,
        batchSize: chunkSize,
        apiKey: apiKey.trim() || undefined,
        startDate: startDate.trim() || undefined,
        endDate: endDate.trim() || undefined,
        forceRefresh,
      };

      if (inputMode === "upload" && file) {
        setActiveCsvContent(await file.text());
        res = await postBatchCsvFile(file, opts);
      } else {
        if (!csvText.trim()) throw new Error("Please enter or paste CSV text.");
        setActiveCsvContent(csvText);
        res = await postBatchCsvText(csvText, opts);
      }
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process coordinates.");
    } finally {
      setLoading(false);
    }
  }

  function handleLoadSample() {
    setInputMode("paste");
    setCsvText(SAMPLE_INDIA_COORDINATES_CSV);
    setError(null);
  }

  function handleExportCsv(scope: "all" | "filtered" = "all") {
    if (!result) return;
    const rowsToExport = scope === "filtered" ? filteredRows : result.rows;
    downloadClientCsv(
      rowsToExport,
      result.fieldnames,
      scope === "filtered" ? "open_meteo_pm25_filtered" : "open_meteo_pm25_enriched",
    );
  }

  async function handleExportPdf(scope: "all" | "filtered" = "all") {
    if (!result) return;
    setPdfLoading(true);
    setError(null);
    try {
      const rowsToExport = scope === "filtered" ? filteredRows : result.rows;
      await downloadBatchPdf(
        result.summary,
        rowsToExport,
        scope === "filtered"
          ? `Batch PM2.5 Analysis - Filtered View (${filteredRows.length} Points)`
          : `Batch PM2.5 Analysis Report (${result.summary.valid_count} Points)`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate PDF report.");
    } finally {
      setPdfLoading(false);
    }
  }

  // Filtered rows
  const filteredRows = useMemo(() => {
    if (!result) return [];
    return result.rows
      .filter((r) => {
        if (!r.valid) return false;
        if (selectedState !== "ALL" && r.state !== selectedState) return false;
        if (selectedCategory !== "ALL" && r.aqi_category !== selectedCategory) return false;
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase();
          const matchPlace = r.place.toLowerCase().includes(q);
          const matchState = r.state.toLowerCase().includes(q);
          if (!matchPlace && !matchState) return false;
        }
        return true;
      })
      .sort((a, b) => {
        if (sortBy === "pm25_desc") return (b.current_pm25 ?? -1) - (a.current_pm25 ?? -1);
        if (sortBy === "pm25_asc") return (a.current_pm25 ?? 9999) - (b.current_pm25 ?? 9999);
        if (sortBy === "place_asc") return a.place.localeCompare(b.place);
        if (sortBy === "state_asc") return a.state.localeCompare(b.state);
        return 0;
      });
  }, [result, selectedState, selectedCategory, searchQuery, sortBy]);

  // Unique states for filter dropdown
  const statesList = useMemo(() => {
    if (!result) return [];
    const set = new Set<string>();
    result.rows.forEach((r) => {
      if (r.state && r.state !== "Unknown") set.add(r.state);
    });
    return Array.from(set).sort();
  }, [result]);

  // Paginated rows
  const paginatedRows = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filteredRows.slice(start, start + PAGE_SIZE);
  }, [filteredRows, page]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));

  // Hourly trend chart options for selected modal row
  const detailChartOption = useMemo(() => {
    if (!selectedRow || !selectedRow.hourly_times || !selectedRow.hourly_pm25) return null;
    const times = selectedRow.hourly_times.map((t) =>
      new Date(t).toLocaleString("en-IN", {
        timeZone: "Asia/Kolkata",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    );
    return {
      grid: { left: 45, right: 16, top: 20, bottom: 36 },
      tooltip: {
        trigger: "axis",
        formatter: (params: Array<{ name: string; value: number }>) => {
          if (!params || !params[0]) return "";
          return `<b>${params[0].name}</b><br/>PM2.5: <b>${params[0].value} µg/m³</b>`;
        },
      },
      xAxis: {
        type: "category",
        data: times,
        axisLabel: { color: "#9db0cc", fontSize: 11 },
        axisLine: { lineStyle: { color: "#22314d" } },
      },
      yAxis: {
        type: "value",
        name: "µg/m³",
        nameTextStyle: { color: "#9db0cc" },
        axisLabel: { color: "#9db0cc" },
        splitLine: { lineStyle: { color: "#16233a" } },
      },
      series: [
        {
          type: "line",
          data: selectedRow.hourly_pm25,
          smooth: true,
          color: selectedRow.aqi_color || "#22d3ee",
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: (selectedRow.aqi_color || "#22d3ee") + "66" },
                { offset: 1, color: "transparent" },
              ],
            },
          },
        },
      ],
    };
  }, [selectedRow]);

  return (
    <>
      <PageHeader
        title="Batch PM2.5 Coordinate Analysis"
        description="Upload or paste any CSV containing coordinates to query real-time & forecast PM2.5 concentrations directly from the Open-Meteo Air Quality atmospheric model across India or worldwide."
        actions={
          <ProvenanceBadge
            kind="atmospheric_model"
            detail="ECMWF CAMS atmospheric-chemistry model via Open-Meteo Air Quality API; coarse grid (~44 km)."
          />
        }
      />

      {/* Input & Upload Panel */}
      <div className="card mb-8 overflow-hidden border border-line bg-surface/90 shadow-2xl backdrop-blur-md">
        <div className="border-b border-line/80 bg-surface-2/40 px-5 py-3.5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/15 text-accent">
              <FileSpreadsheet className="h-4 w-4" />
            </span>
            <span className="text-sm font-semibold tracking-wide">Input Coordinates CSV</span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex rounded-md border border-line bg-surface p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setInputMode("paste")}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  inputMode === "paste" ? "bg-accent/20 text-accent font-semibold" : "text-muted hover:text-fg"
                }`}
              >
                Paste / Edit CSV
              </button>
              <button
                type="button"
                onClick={() => setInputMode("upload")}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  inputMode === "upload" ? "bg-accent/20 text-accent font-semibold" : "text-muted hover:text-fg"
                }`}
              >
                Upload File
              </button>
            </div>

            <Button
              variant="secondary"
              size="sm"
              onClick={handleLoadSample}
              className="text-xs border-accent/30 hover:border-accent/60 hover:bg-accent/10 text-accent"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Load Sample (378 India Locations)
            </Button>
          </div>
        </div>

        <div className="p-5">
          {inputMode === "upload" ? (
            <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-line/80 bg-surface-2/20 p-8 text-center transition-all hover:border-accent/50 hover:bg-surface-2/30">
              <UploadCloud className="h-10 w-10 text-accent/70 mb-3" />
              <p className="text-sm font-medium text-fg">
                {file ? file.name : "Drag and drop your coordinates CSV here"}
              </p>
              <p className="mt-1 text-xs text-muted max-w-md">
                Expects headers with Latitude and Longitude (e.g. State Name, Place, Latitude, Longitude).
              </p>
              <label className="mt-4 cursor-pointer">
                <span className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg shadow-sm hover:border-accent hover:text-accent">
                  Browse CSV File
                </span>
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) setFile(f);
                  }}
                />
              </label>
              {file && (
                <div className="mt-3 flex items-center gap-2 text-xs text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  <span>Selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)</span>
                </div>
              )}
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-1.5 text-xs text-muted">
                <span>CSV Text (comma or semicolon separated, header row required)</span>
                <span>{csvText.split("\n").filter((l) => l.trim()).length} lines</span>
              </div>
              <textarea
                value={csvText}
                onChange={(e) => setCsvText(e.target.value)}
                placeholder="State Name,Place,Latitude,Longitude&#10;Delhi,Central,28.61,77.21&#10;Andhra Pradesh,Ananthapuramu,14,77"
                rows={9}
                className="w-full rounded-lg border border-line bg-surface-2/40 px-3.5 py-2.5 font-mono text-xs text-fg placeholder:text-muted/60 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
          )}

          {error && (
            <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300">
              <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          {/* Rate Limit Advice Banner */}
          {inputMode === "paste" && csvText.split("\n").filter((l) => l.trim()).length > 500 && !apiKey && (
            <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-300">
              <Clock className="h-4 w-4 shrink-0 text-amber-400" />
              <span>
                <b>High coordinate count ({csvText.split("\n").filter((l) => l.trim()).length} lines):</b> Open-Meteo free tier has a 600 locations/minute quota. AEROCAST automatically paces requests and sleeps for ~60s after chunk 5 so all locations finish without 429 rate limit errors.
              </span>
            </div>
          )}

          {/* Optional Commercial API Key Row */}
          {showApiKey && (
            <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface-2/40 px-3.5 py-2.5 text-xs">
              <span className="text-muted font-medium shrink-0">Open-Meteo API Key:</span>
              <input
                type="password"
                placeholder="Paste key for commercial quota (customer-api.open-meteo.com)"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="flex-1 min-w-[200px] bg-transparent text-fg placeholder:text-muted/60 focus:outline-none font-mono text-xs"
              />
              <span className="text-[11px] text-muted/70">Optional - removes minutely rate cap</span>
            </div>
          )}

          {/* Hourly Checkpoint & Cache Options Panel */}
          {showHourlyOptions && (
            <div className="mt-4 rounded-lg border border-accent/30 bg-accent/5 p-3.5 text-xs space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-accent/15 pb-2">
                <span className="font-semibold text-fg flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5 text-accent" />
                  Incremental Hourly Range & State Checkpoint
                </span>
                <span className="text-[11px] text-muted">
                  Automatically checks local cache; only queries un-fetched delta hours!
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-muted font-medium">Start Date / Hour:</span>
                  <input
                    type="datetime-local"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="rounded border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:border-accent focus:outline-none"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-muted font-medium">End Date / Hour:</span>
                  <input
                    type="datetime-local"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="rounded border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:border-accent focus:outline-none"
                  />
                </div>
                {(startDate || endDate) && (
                  <button
                    type="button"
                    onClick={() => {
                      setStartDate("");
                      setEndDate("");
                    }}
                    className="text-[11px] text-rose-400 hover:underline"
                  >
                    Clear Range
                  </button>
                )}
                <label className="flex items-center gap-1.5 cursor-pointer text-muted hover:text-fg ml-auto font-medium">
                  <input
                    type="checkbox"
                    checked={forceRefresh}
                    onChange={(e) => setForceRefresh(e.target.checked)}
                    className="rounded border-line text-accent focus:ring-accent"
                  />
                  <span>Force re-fetch (bypass cache)</span>
                </label>
              </div>
            </div>
          )}

          {/* Action Footer */}
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-line/60">
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-accent" />
                Forecast Horizon:
              </span>
              <select
                value={forecastHours}
                onChange={(e) => setForecastHours(Number(e.target.value))}
                className="rounded border border-line bg-surface px-2 py-1 text-xs text-fg focus:border-accent focus:outline-none"
              >
                <option value={24}>Next 24 Hours</option>
                <option value={48}>Next 48 Hours</option>
              </select>

              <span className="flex items-center gap-1.5 ml-1">
                <Layers className="h-3.5 w-3.5 text-accent" />
                Chunk Size:
              </span>
              <select
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
                className="rounded border border-line bg-surface px-2 py-1 text-xs text-fg focus:border-accent focus:outline-none"
              >
                <option value={50}>50 loc / chunk</option>
                <option value={100}>100 loc / chunk (Recommended limit)</option>
              </select>
              <span className="text-muted/60 text-[11px]">(Max 100/req to stay within HTTP 414 URL limits)</span>

              <button
                type="button"
                onClick={() => setShowHourlyOptions(!showHourlyOptions)}
                className={`text-xs hover:underline flex items-center gap-1 ml-2 font-medium ${
                  showHourlyOptions || startDate || endDate ? "text-accent font-semibold" : "text-muted"
                }`}
              >
                ⏱ {showHourlyOptions ? "Hide Hourly Range" : "Hourly Range & Checkpoint"}
              </button>

              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="text-xs text-accent hover:underline flex items-center gap-1 ml-1"
              >
                {showApiKey ? "Hide Key" : "+ Commercial Key"}
              </button>
            </div>

            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                onClick={handleSubmit}
                disabled={loading}
                className="shadow-lg shadow-cyan-500/10 hover:shadow-cyan-500/20"
              >
                {loading ? (
                  <>
                    <RefreshCw className="h-4 w-4 animate-spin text-bg" />
                    Querying Open-Meteo...
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    Query Open-Meteo PM2.5
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Loading Progress State */}
      {loading && (
        <div className="card mb-8 p-6 text-center border-accent/40 bg-surface/80">
          <div className="flex justify-center mb-3">
            <RefreshCw className="h-8 w-8 animate-spin text-accent" />
          </div>
          <h3 className="text-base font-semibold text-fg">Querying Open-Meteo Air Quality API</h3>
          <p className="mt-1 text-xs text-muted max-w-md mx-auto">
            Batching coordinates in chunks of {chunkSize} locations (safe URL limit) to fetch real-time PM2.5 and hourly forecasts...
          </p>
          <p className="mt-2 text-[11px] text-muted/80 max-w-sm mx-auto">
            Free tier quota: 600 locations/min. If your CSV has more than 500 locations, queries will safely pause for ~60s between windows to prevent HTTP 429 rate limits.
          </p>
        </div>
      )}

      {/* Results View */}
      {result && !loading && (
        <div className="space-y-8">
          {/* Smart Checkpoint Active Banner */}
          {result.summary.cache_hits !== undefined && result.summary.cache_hits > 0 && (
            <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-xs text-emerald-300 flex flex-wrap items-center justify-between gap-3 shadow-sm">
              <div className="flex items-center gap-2.5">
                <Sparkles className="h-4 w-4 text-emerald-400 shrink-0" />
                <span>
                  <b>Incremental Checkpoint Active:</b> {result.summary.cache_hits} of {result.summary.valid_count} coordinates were served instantly from local hourly cache ({result.summary.api_calls_avoided} Open-Meteo API requests avoided!).
                </span>
              </div>
              <span className="font-mono text-[11px] text-emerald-400 font-bold bg-emerald-500/20 border border-emerald-500/30 px-2.5 py-1 rounded-md">
                ⚡ 0 Upstream Requests Needed
              </span>
            </div>
          )}

          {/* Executive KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="rounded-xl border border-line bg-surface/90 p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-muted font-medium">
                <span>Locations Queried</span>
                <MapPin className="h-3.5 w-3.5 text-accent" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-2xl font-bold text-fg">{result.summary.valid_count}</span>
                <span className="text-xs text-muted">/ {result.summary.total_rows} rows</span>
              </div>
              <p className="mt-1 text-[11px] text-emerald-400">
                100% parsed successfully via Open-Meteo CAMS
              </p>
            </div>

            <div className="rounded-xl border border-line bg-surface/90 p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-muted font-medium">
                <span>Dataset Mean PM2.5</span>
                <TrendingUp className="h-3.5 w-3.5 text-accent" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-2xl font-bold text-fg">
                  {result.summary.avg_pm25 ?? "—"}
                </span>
                <span className="text-xs text-muted">µg/m³</span>
              </div>
              <p className="mt-1 text-[11px] text-muted">
                National average across provided points
              </p>
            </div>

            <div className="rounded-xl border border-line bg-surface/90 p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-muted font-medium">
                <span>Highest Pollution Hotspot</span>
                <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-2xl font-bold text-rose-400">
                  {result.summary.max_location?.value ?? "—"}
                </span>
                <span className="text-xs text-muted">µg/m³</span>
              </div>
              <p className="mt-1 text-[11px] text-rose-300 truncate font-medium">
                {result.summary.max_location?.place}, {result.summary.max_location?.state}
              </p>
            </div>

            <div className="rounded-xl border border-line bg-surface/90 p-4 shadow-sm">
              <div className="flex items-center justify-between text-xs text-muted font-medium">
                <span>Cleanest Air Coordinate</span>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="font-mono text-2xl font-bold text-emerald-400">
                  {result.summary.min_location?.value ?? "—"}
                </span>
                <span className="text-xs text-muted">µg/m³</span>
              </div>
              <p className="mt-1 text-[11px] text-emerald-300 truncate font-medium">
                {result.summary.min_location?.place}, {result.summary.min_location?.state}
              </p>
            </div>
          </div>

          {/* CPCB AQI Distribution Breakdown Bar */}
          <Section title="CPCB National AQI Category Distribution (PM2.5)">
            <div className="rounded-xl border border-line bg-surface/90 p-4 space-y-3">
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2">
                {Object.entries(result.summary.category_distribution).map(([cat, count]) => {
                  if (count === 0) return null;
                  const pct = ((count / Math.max(1, result.summary.valid_count)) * 100).toFixed(1);
                  const color =
                    cat === "Good"
                      ? "#00b050"
                      : cat === "Satisfactory"
                      ? "#92d050"
                      : cat === "Moderately polluted"
                      ? "#eab308"
                      : cat === "Poor"
                      ? "#f97316"
                      : cat === "Very poor"
                      ? "#ef4444"
                      : "#b91c1c";
                  return (
                    <div
                      key={cat}
                      style={{ width: `${pct}%`, backgroundColor: color }}
                      title={`${cat}: ${count} locations (${pct}%)`}
                      className="transition-all hover:opacity-85"
                    />
                  );
                })}
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
                {Object.entries(result.summary.category_distribution).map(([cat, count]) => {
                  const isSelected = selectedCategory === cat;
                  return (
                    <button
                      key={cat}
                      type="button"
                      onClick={() => setSelectedCategory(isSelected ? "ALL" : cat)}
                      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 transition-all border ${
                        isSelected
                          ? "border-accent bg-accent/20 text-fg font-semibold shadow-sm"
                          : "border-line bg-surface-2/60 text-muted hover:text-fg hover:border-line/80"
                      }`}
                    >
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{
                          backgroundColor:
                            cat === "Good"
                              ? "#00b050"
                              : cat === "Satisfactory"
                              ? "#92d050"
                              : cat === "Moderately polluted"
                              ? "#eab308"
                              : cat === "Poor"
                              ? "#f97316"
                              : cat === "Very poor"
                              ? "#ef4444"
                              : "#b91c1c",
                        }}
                      />
                      <span>{cat}:</span>
                      <span className="font-mono font-medium text-fg">{count}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </Section>

          {/* State Summaries Pills */}
          {result.summary.state_summaries.length > 1 && (
            <Section title="State-Level PM2.5 Overview (Click to Filter)">
              <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin">
                <button
                  type="button"
                  onClick={() => setSelectedState("ALL")}
                  className={`shrink-0 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    selectedState === "ALL"
                      ? "border-accent bg-accent/15 text-accent font-semibold"
                      : "border-line bg-surface text-muted hover:text-fg"
                  }`}
                >
                  <span className="block font-medium">All States</span>
                  <span className="text-[11px] opacity-75">{result.summary.valid_count} locations</span>
                </button>
                {result.summary.state_summaries.map((st) => {
                  const isSel = selectedState === st.state;
                  return (
                    <button
                      key={st.state}
                      type="button"
                      onClick={() => setSelectedState(isSel ? "ALL" : st.state)}
                      className={`shrink-0 rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                        isSel
                          ? "border-accent bg-accent/15 text-accent font-semibold"
                          : "border-line bg-surface text-muted hover:text-fg hover:border-accent/40"
                      }`}
                    >
                      <div className="flex items-center gap-1.5 font-medium text-fg">
                        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: st.aqi_color }} />
                        <span>{st.state}</span>
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[11px]">
                        <span className="font-mono text-fg font-semibold">{st.avg_pm25} µg/m³</span>
                        <span className="text-muted">({st.count})</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Interactive Search, Filter and Table */}
          <Section
            title={`Detailed Location Table (${filteredRows.length} points)`}
            aside={
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleExportCsv("all")}
                  className="text-xs hover:border-accent/60"
                  title="Instant download of all enriched locations as CSV"
                >
                  <Download className="h-3.5 w-3.5 text-accent" />
                  Download CSV ({result.rows.length})
                </Button>
                {filteredRows.length < result.rows.length && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleExportCsv("filtered")}
                    className="text-xs"
                    title="Download currently filtered locations as CSV"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download Filtered CSV ({filteredRows.length})
                  </Button>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleExportPdf("all")}
                  disabled={pdfLoading}
                  className="text-xs border-accent/40 bg-accent/10 text-accent hover:bg-accent/20"
                  title="Download styled multi-page PDF executive report"
                >
                  <FileText className="h-3.5 w-3.5" />
                  {pdfLoading ? (
                    <>
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                      Generating PDF...
                    </>
                  ) : (
                    "Download PDF Report"
                  )}
                </Button>
              </div>
            }
          >
            {/* Filter Bar */}
            <div className="card mb-4 p-3.5 flex flex-wrap items-center justify-between gap-3 bg-surface/70">
              <div className="flex flex-wrap items-center gap-2.5">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
                  <input
                    type="text"
                    placeholder="Search place or state..."
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setPage(1);
                    }}
                    className="h-8 w-44 sm:w-56 rounded-md border border-line bg-surface-2 px-2.5 pl-8 text-xs text-fg placeholder:text-muted focus:border-accent focus:outline-none"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery("")}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-fg"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </div>

                <select
                  value={selectedState}
                  onChange={(e) => {
                    setSelectedState(e.target.value);
                    setPage(1);
                  }}
                  className="h-8 rounded-md border border-line bg-surface-2 px-2.5 text-xs text-fg focus:border-accent focus:outline-none"
                >
                  <option value="ALL">All States ({statesList.length})</option>
                  {statesList.map((st) => (
                    <option key={st} value={st}>
                      {st}
                    </option>
                  ))}
                </select>

                <select
                  value={selectedCategory}
                  onChange={(e) => {
                    setSelectedCategory(e.target.value);
                    setPage(1);
                  }}
                  className="h-8 rounded-md border border-line bg-surface-2 px-2.5 text-xs text-fg focus:border-accent focus:outline-none"
                >
                  <option value="ALL">All Categories</option>
                  <option value="Good">Good (0–30)</option>
                  <option value="Satisfactory">Satisfactory (31–60)</option>
                  <option value="Moderately polluted">Moderately polluted (61–90)</option>
                  <option value="Poor">Poor (91–120)</option>
                  <option value="Very poor">Very poor (121–250)</option>
                  <option value="Severe">Severe (&gt;250)</option>
                </select>
              </div>

              <div className="flex items-center gap-2">
                <span className="text-xs text-muted flex items-center gap-1">
                  <ArrowUpDown className="h-3 w-3" /> Sort:
                </span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as any)}
                  className="h-8 rounded-md border border-line bg-surface-2 px-2.5 text-xs text-fg focus:border-accent focus:outline-none"
                >
                  <option value="pm25_desc">Highest PM2.5 First</option>
                  <option value="pm25_asc">Lowest PM2.5 First</option>
                  <option value="place_asc">Place Name (A–Z)</option>
                  <option value="state_asc">State Name (A–Z)</option>
                </select>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-line bg-surface-2/40 text-xs font-semibold uppercase tracking-wider text-muted">
                  <tr>
                    <th scope="col" className="px-4 py-3">#</th>
                    <th scope="col" className="px-4 py-3">State</th>
                    <th scope="col" className="px-4 py-3">Place</th>
                    <th scope="col" className="px-4 py-3">Coordinates</th>
                    <th scope="col" className="px-4 py-3">Current PM2.5</th>
                    <th scope="col" className="px-4 py-3">24h Forecast Avg</th>
                    <th scope="col" className="px-4 py-3">Range (Min–Max)</th>
                    <th scope="col" className="px-4 py-3">AQI Category</th>
                    <th scope="col" className="px-4 py-3">Elevation</th>
                    <th scope="col" className="px-4 py-3 text-right">Trend</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/70">
                  {paginatedRows.map((row) => (
                    <tr
                      key={row.index}
                      className="transition-colors hover:bg-surface-2/40 cursor-pointer"
                      onClick={() => setSelectedRow(row)}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-muted">{row.index}</td>
                      <td className="px-4 py-3 font-medium text-fg">{row.state}</td>
                      <td className="px-4 py-3 font-semibold text-fg">
                        <div className="flex items-center gap-1.5">
                          <span>{row.place}</span>
                          {row.from_cache && (
                            <span
                              className="text-[10px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/25 px-1.5 py-0.2 rounded font-mono font-normal"
                              title="Loaded from local hourly checkpoint (0 API calls)"
                            >
                              ⚡ Cache
                            </span>
                          )}
                          {row.continued_from && (
                            <span
                              className="text-[10px] text-cyan-400 bg-cyan-500/10 border border-cyan-500/25 px-1.5 py-0.2 rounded font-mono font-normal"
                              title={`Resumed from ${row.continued_from}`}
                            >
                              ▶ Resumed
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted">
                        {row.latitude?.toFixed(2)}°N, {row.longitude?.toFixed(2)}°E
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-base font-bold" style={{ color: row.aqi_color }}>
                          {row.current_pm25 ?? "—"}
                        </span>
                        <span className="ml-1 text-xs text-muted">µg/m³</span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted">
                        {row.forecast_24h_avg ? `${row.forecast_24h_avg} µg/m³` : "—"}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted">
                        {row.forecast_min !== null && row.forecast_max !== null
                          ? `${row.forecast_min} – ${row.forecast_max}`
                          : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium"
                          style={{
                            backgroundColor: `${row.aqi_color}22`,
                            color: row.aqi_color,
                            border: `1px solid ${row.aqi_color}44`,
                          }}
                        >
                          <span
                            className="h-1.5 w-1.5 rounded-full"
                            style={{ backgroundColor: row.aqi_color }}
                          />
                          {row.aqi_category}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted">
                        {row.elevation_m ? `${Math.round(row.elevation_m)} m` : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedRow(row);
                          }}
                          className="rounded px-2 py-1 text-xs text-accent hover:bg-accent/10 transition-colors"
                        >
                          View 24h
                        </button>
                      </td>
                    </tr>
                  ))}
                  {filteredRows.length === 0 && (
                    <tr>
                      <td colSpan={10} className="px-4 py-8 text-center text-sm text-muted">
                        No locations match the active search and filter criteria.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-muted">
                  <span>
                    Showing {(page - 1) * PAGE_SIZE + 1} to{" "}
                    {Math.min(page * PAGE_SIZE, filteredRows.length)} of {filteredRows.length} entries
                  </span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      disabled={page === 1}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      className="rounded border border-line bg-surface px-2.5 py-1 text-fg disabled:opacity-40 hover:bg-surface-2 transition-colors"
                    >
                      Previous
                    </button>
                    <span className="px-2 font-mono">
                      {page} / {totalPages}
                    </span>
                    <button
                      type="button"
                      disabled={page === totalPages}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      className="rounded border border-line bg-surface px-2.5 py-1 text-fg disabled:opacity-40 hover:bg-surface-2 transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          </Section>
        </div>
      )}

      {/* Hourly Trend Dialog for Clicked Coordinate */}
      <Dialog
        open={selectedRow !== null}
        onClose={() => setSelectedRow(null)}
        title={
          selectedRow
            ? `${selectedRow.place}, ${selectedRow.state} — PM2.5 Hourly Forecast`
            : "Location Trend"
        }
      >
        {selectedRow && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div className="rounded-lg border border-line bg-surface-2/40 p-2.5">
                <span className="text-muted block">Current PM2.5</span>
                <span
                  className="font-mono text-lg font-bold"
                  style={{ color: selectedRow.aqi_color }}
                >
                  {selectedRow.current_pm25 ?? "—"} µg/m³
                </span>
              </div>
              <div className="rounded-lg border border-line bg-surface-2/40 p-2.5">
                <span className="text-muted block">24h Average</span>
                <span className="font-mono text-lg font-bold text-fg">
                  {selectedRow.forecast_24h_avg ?? "—"} µg/m³
                </span>
              </div>
              <div className="rounded-lg border border-line bg-surface-2/40 p-2.5">
                <span className="text-muted block">Min – Max</span>
                <span className="font-mono text-sm font-semibold text-fg">
                  {selectedRow.forecast_min} – {selectedRow.forecast_max}
                </span>
              </div>
              <div className="rounded-lg border border-line bg-surface-2/40 p-2.5">
                <span className="text-muted block">Elevation</span>
                <span className="font-mono text-sm font-semibold text-fg">
                  {selectedRow.elevation_m ? `${Math.round(selectedRow.elevation_m)} m` : "—"}
                </span>
              </div>
            </div>

            <div>
              <p className="text-xs text-muted mb-2">Hourly Concentration Forecast (Open-Meteo ECMWF CAMS)</p>
              {detailChartOption ? (
                <EChart
                  option={detailChartOption}
                  height={220}
                  ariaLabel={`Hourly PM2.5 for ${selectedRow.place}`}
                />
              ) : (
                <p className="text-xs text-muted py-6 text-center">No hourly series available.</p>
              )}
            </div>

            <div className="rounded-lg border border-line/60 bg-surface-2/20 p-2.5 text-[11px] text-muted flex items-center justify-between">
              <span>
                Coordinates: {selectedRow.latitude}°N, {selectedRow.longitude}°E
              </span>
              <span
                className="font-semibold"
                style={{ color: selectedRow.aqi_color }}
              >
                Category: {selectedRow.aqi_category}
              </span>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
