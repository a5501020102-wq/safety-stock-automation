"use client";

import { useCallback, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { useWorkflow } from "@/lib/workflow-context";
import type { CalculationResponse, SkuResult, StockStatus } from "@/lib/types";

/**
 * ResultsTable
 * ---------------------------------------------------------------------------
 * The main results table for Section 03.
 *
 * - In compare mode we show two sibling tables (Split vs Consolidated).
 * - In single modes we show one table.
 *
 * Controls:
 *   - Tab: all / shortage / healthy / overstock (status filter)
 *   - Search: sku or name substring
 *   - Site filter: dropdown (only shown when >1 site exists in the data)
 *   - Sort: click column headers to toggle asc/desc
 *   - Pagination: page size 50, arrow + page numbers
 *
 * All state is local to this component (no need to persist these UI prefs).
 */
export function ResultsTable() {
  const { calculationResult } = useWorkflow();
  if (!calculationResult) return null;

  if (calculationResult.mode === "compare") {
    const { allSummary, totalSummary } = calculationResult;
    return (
      <div className="mt-16 flex flex-col gap-20">
        <ExportBar result={calculationResult} />
        <TableBlock
          heading="Split · Per site"
          italicAccent="spread"
          deck="Each shipping point computed independently."
          results={allSummary.results}
          mode="all"
        />
        <TableBlock
          heading="Consolidated · Single"
          italicAccent="warehouse"
          deck="All sites pooled into one virtual warehouse."
          results={totalSummary.results}
          mode="total"
        />
      </div>
    );
  }

  return (
    <div className="mt-16">
      <ExportBar result={calculationResult} />
      <TableBlock
        heading={calculationResult.mode === "total" ? "Consolidated" : "Per site"}
        italicAccent="results"
        deck="All SKUs that passed the minimum-months filter."
        results={calculationResult.results}
        mode={calculationResult.mode}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export bar (Excel / SAP)
// ---------------------------------------------------------------------------

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function ExportBar({ result }: { result: CalculationResponse }) {
  const granularity = result.parameters?.granularity ?? "monthly";
  const [exporting, setExporting] = useState<string | null>(null);

  const handleExportExcel = async () => {
    setExporting("excel");
    try {
      let resp: { blob: Blob; filename: string };
      const siteFilter = sapSite !== "all" ? sapSite : undefined;
      const selectedWeeks = result.parameters?.selectedWeeks as string[] | undefined;
      const calcParams = result.parameters ? { ...result.parameters } : undefined;
      if (result.mode === "compare") {
        resp = await api.exportExcel({
          mode: "compare",
          siteFilter,
          granularity,
          selectedWeeks,
          calcParams,
          allSummary: { summary: result.allSummary.summary, results: result.allSummary.results },
          totalSummary: { summary: result.totalSummary.summary, results: result.totalSummary.results },
          comparison: result.comparison,
        });
      } else {
        resp = await api.exportExcel({
          mode: result.mode,
          siteFilter,
          granularity,
          selectedWeeks,
          calcParams,
          summary: "summary" in result ? result.summary : undefined,
          results: "results" in result ? result.results : undefined,
        });
      }
      triggerDownload(resp.blob, resp.filename);
    } catch (e) {
      console.error("Export failed:", e);
    } finally {
      setExporting(null);
    }
  };

  const handleExportSap = async (sapMode: "all" | "total") => {
    setExporting("sap");
    try {
      let resp: { blob: Blob; filename: string };
      const siteFilter = sapSite !== "all" ? sapSite : undefined;
      if (result.mode === "compare") {
        resp = await api.exportSap({
          mode: "compare",
          sapMode,
          format: "xlsx",
          siteFilter,
          allSummary: { summary: result.allSummary.summary, results: result.allSummary.results },
          totalSummary: { summary: result.totalSummary.summary, results: result.totalSummary.results },
        });
      } else {
        resp = await api.exportSap({
          mode: result.mode,
          format: "xlsx",
          siteFilter,
          summary: "summary" in result ? result.summary : undefined,
          results: "results" in result ? result.results : undefined,
        });
      }
      triggerDownload(resp.blob, resp.filename);
    } catch (e) {
      console.error("SAP export failed:", e);
    } finally {
      setExporting(null);
    }
  };

  // Collect available sites from results
  const availableSites = useMemo(() => {
    const sites = new Set<string>();
    if (result.mode === "compare") {
      for (const r of result.allSummary.results) {
        if (r.site) sites.add(r.site);
      }
    } else if ("results" in result) {
      for (const r of result.results) {
        if (r.site) sites.add(r.site);
      }
    }
    return Array.from(sites).sort();
  }, [result]);

  const [sapSite, setSapSite] = useState<string>("all");

  return (
    <div className="border-t border-foreground/20 pt-6 flex flex-wrap items-center gap-6">
      <span className="font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Export</span>

      <button
        type="button"
        onClick={handleExportExcel}
        disabled={exporting !== null}
        className={cn(
          "font-sans text-[11px] uppercase tracking-[0.2em] pb-1 border-b transition-colors duration-500 ease-luxury",
          exporting === "excel"
            ? "text-accent border-accent"
            : "text-foreground border-foreground hover:text-accent hover:border-accent"
        )}
      >
        {exporting === "excel" ? "Downloading..." : "Excel"}
      </button>

      <div className="flex items-center gap-3">
        <select
          value={sapSite}
          onChange={(e) => setSapSite(e.target.value)}
          className="bg-transparent border-0 border-b border-foreground py-1 font-mono text-xs text-foreground appearance-none cursor-pointer focus:outline-none focus:border-accent transition-colors duration-500 ease-luxury pr-4"
        >
          <option value="all">All sites</option>
          {availableSites.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {result.mode === "compare" ? (
        <>
          <button
            type="button"
            onClick={() => handleExportSap("all")}
            disabled={exporting !== null}
            className={cn(
              "font-sans text-[11px] uppercase tracking-[0.2em] pb-1 border-b transition-colors duration-500 ease-luxury",
              exporting === "sap"
                ? "text-accent border-accent"
                : "text-foreground border-foreground hover:text-accent hover:border-accent"
            )}
          >
            SAP MM17 · Split
          </button>
          <button
            type="button"
            onClick={() => handleExportSap("total")}
            disabled={exporting !== null}
            className={cn(
              "font-sans text-[11px] uppercase tracking-[0.2em] pb-1 border-b transition-colors duration-500 ease-luxury",
              exporting === "sap"
                ? "text-accent border-accent"
                : "text-foreground border-foreground hover:text-accent hover:border-accent"
            )}
          >
            SAP MM17 · Consolidated
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => handleExportSap(result.mode === "total" ? "total" : "all")}
          disabled={exporting !== null}
          className={cn(
            "font-sans text-[11px] uppercase tracking-[0.2em] pb-1 border-b transition-colors duration-500 ease-luxury",
            exporting === "sap"
              ? "text-accent border-accent"
              : "text-foreground border-foreground hover:text-accent hover:border-accent"
          )}
        >
          {exporting === "sap" ? "Downloading..." : "SAP MM17"}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TableBlock — one complete results table with its own local filter / sort
// ---------------------------------------------------------------------------

type SortKey =
  | "site"
  | "sku"
  | "abcClass"
  | "totalQty"
  | "meanDemand"
  | "dailyDemand"
  | "stdDev"
  | "cv"
  | "safetyStock"
  | "reorderPoint"
  | "maxInventory"
  | "trendPct"
  | "planStock"
  | "suggestedOrder"
  | "coverageDays"
  | "gap";
type SortDir = "asc" | "desc";

const STATUS_FILTERS: Array<{
  key: "all" | StockStatus;
  label: string;
  description: string;
}> = [
  { key: "all", label: "All", description: "Every SKU" },
  { key: "red", label: "Shortage", description: "Below safety" },
  { key: "green", label: "Healthy", description: "Within range" },
  { key: "blue", label: "Overstock", description: "Above 3× SS" },
];

function TableBlock({
  heading,
  italicAccent,
  deck,
  results,
  mode,
}: {
  heading: string;
  italicAccent: string;
  deck: string;
  results: SkuResult[];
  mode: "all" | "total" | "single";
}) {
  const { parameters } = useWorkflow();
  // Filter + pagination state
  const [statusFilter, setStatusFilterRaw] = useState<"all" | StockStatus>("all");
  const [siteFilter, setSiteFilterRaw] = useState<string>("all");
  const [query, setQueryRaw] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({
    key: "totalQty",
    dir: "desc",
  });
  const [page, setPage] = useState(1);
  const pageSize = 50;

  // 判斷是否有任何結果包含 plan 資料
  const hasPlanData = useMemo(() => results.some((r) => r.hasPlan), [results]);

  // 篩選條件變更時同步重置分頁到第 1 頁
  const setStatusFilter = useCallback((v: "all" | StockStatus) => {
    setStatusFilterRaw(v);
    setPage(1);
  }, []);
  const setSiteFilter = useCallback((v: string) => {
    setSiteFilterRaw(v);
    setPage(1);
  }, []);
  const setQuery = useCallback((v: string) => {
    setQueryRaw(v);
    setPage(1);
  }, []);

  // Derive the list of sites for the filter dropdown
  const sites = useMemo(() => {
    const s = new Set<string>();
    for (const r of results) if (r.site) s.add(r.site);
    return Array.from(s).sort();
  }, [results]);

  const showSiteFilter = mode === "all" && sites.length > 1;

  // Status counts (for tab badges)
  const statusCounts = useMemo(() => {
    const c: Record<"all" | StockStatus, number> = {
      all: results.length,
      red: 0,
      green: 0,
      blue: 0,
      gray: 0,
    };
    for (const r of results) c[r.status]++;
    return c;
  }, [results]);

  // Pipeline: site -> status -> search -> sort -> paginate
  const filteredSorted = useMemo(() => {
    let list = results;
    if (showSiteFilter && siteFilter !== "all") {
      list = list.filter((r) => r.site === siteFilter);
    }
    if (statusFilter !== "all") {
      list = list.filter((r) => r.status === statusFilter);
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((r) => r.sku.toLowerCase().includes(q) || (r.name ?? "").toLowerCase().includes(q));
    }
    // Sort (immutable: clone before sorting)
    const gran = parameters?.granularity ?? "monthly";
    const dpp = gran === "daily" ? 1 : gran === "weekly" ? 7 : (parameters?.workingDaysPerMonth ?? 30);

    const getSortValue = (r: SkuResult, key: SortKey): number | string | null => {
      if (key === "dailyDemand") return r.meanDemand > 0 ? r.meanDemand / dpp : 0;
      if (key === "trendPct") return r.trendPct ?? null;
      if (key === "coverageDays") return r.coverageDays ?? null;
      if (key === "gap") return r.gap ?? null;
      return r[key] as number | string;
    };

    const sorted = [...list].sort((a, b) => {
      const av = getSortValue(a, sort.key);
      const bv = getSortValue(b, sort.key);
      // Nulls go last
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (av === bv) return 0;
      const dir = sort.dir === "asc" ? 1 : -1;
      if (typeof av === "number" && typeof bv === "number") {
        return (av - bv) * dir;
      }
      return String(av).localeCompare(String(bv)) * dir;
    });
    return sorted;
  }, [results, siteFilter, statusFilter, query, sort, showSiteFilter, parameters]);

  // For split mode: group by SKU for display
  const grouped = useMemo(() => {
    if (mode !== "all") return null;
    const map = new Map<string, SkuResult[]>();
    for (const r of filteredSorted) {
      const key = r.sku;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    // Sort groups by sum of totalQty desc
    return Array.from(map.entries())
      .map(([sku, items]) => ({
        sku,
        name: items[0].name,
        abcClass: items[0].abcClass,
        isPriceMissing: items[0].isPriceMissing,
        totalQty: items.reduce((s, r) => s + r.totalQty, 0),
        items: items.sort((a, b) => b.totalQty - a.totalQty),
      }))
      .sort((a, b) => b.totalQty - a.totalQty);
  }, [filteredSorted, mode]);

  // Pagination: count by groups (split) or rows (total/single)
  const itemCount = grouped ? grouped.length : filteredSorted.length;
  const totalPages = Math.max(1, Math.ceil(itemCount / pageSize));
  const currentPage = Math.min(page, totalPages);
  const start = (currentPage - 1) * pageSize;
  const pageSlice = grouped ? grouped.slice(start, start + pageSize) : null;
  const flatPageSlice = grouped ? null : filteredSorted.slice(start, start + pageSize);
  const planExtraCols = hasPlanData ? 7 : 0;
  const colCount = (mode === "all" ? 13 : 12) + planExtraCols;

  const onSort = (key: SortKey) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
    setPage(1);
  };

  return (
    <section>
      {/* Heading */}
      <div className="border-t border-foreground/20 pt-6">
        <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Table</span>
        <h3 className="mt-2 font-serif text-3xl md:text-4xl leading-tight text-foreground">
          {heading} <em className="italic text-accent">{italicAccent}.</em>
        </h3>
        <p className="mt-2 font-sans text-sm text-muted-foreground max-w-xl">{deck}</p>
      </div>

      {/* Controls row */}
      <div className="mt-8 flex flex-col lg:flex-row lg:items-end gap-6 lg:gap-10">
        <StatusTabs counts={statusCounts} active={statusFilter} onChange={setStatusFilter} />
        <div className="flex flex-col sm:flex-row gap-4 lg:ml-auto">
          {showSiteFilter ? <SiteDropdown sites={sites} value={siteFilter} onChange={setSiteFilter} /> : null}
          <SearchInput value={query} onChange={setQuery} />
        </div>
      </div>

      {/* Table */}
      <div className="mt-6 overflow-x-auto">
        <table className="min-w-full border-separate border-spacing-0 text-sm">
          <thead>
            <tr>
              {mode === "all" ? (
                <HeaderCell sortKey="site" sort={sort} onSort={onSort}>
                  Site
                </HeaderCell>
              ) : null}
              <HeaderCell sortKey="sku" sort={sort} onSort={onSort}>
                SKU
              </HeaderCell>
              <HeaderCell sortKey={null}>Name</HeaderCell>
              <HeaderCell sortKey="abcClass" sort={sort} onSort={onSort} align="center">
                ABC
              </HeaderCell>
              <HeaderCell sortKey="totalQty" sort={sort} onSort={onSort} align="right">
                Total
              </HeaderCell>
              <HeaderCell sortKey="meanDemand" sort={sort} onSort={onSort} align="right">
                Mean
              </HeaderCell>
              <HeaderCell sortKey="dailyDemand" sort={sort} onSort={onSort} align="right">
                Daily
              </HeaderCell>
              <HeaderCell sortKey="stdDev" sort={sort} onSort={onSort} align="right">
                Std Dev
              </HeaderCell>
              <HeaderCell sortKey="cv" sort={sort} onSort={onSort} align="right">
                CV
              </HeaderCell>
              <HeaderCell sortKey="safetyStock" sort={sort} onSort={onSort} align="right">
                Safety
              </HeaderCell>
              <HeaderCell sortKey="reorderPoint" sort={sort} onSort={onSort} align="right">
                ROP
              </HeaderCell>
              <HeaderCell sortKey="maxInventory" sort={sort} onSort={onSort} align="right">
                Max
              </HeaderCell>
              <HeaderCell sortKey="trendPct" sort={sort} onSort={onSort} align="right">
                Trend
              </HeaderCell>
              {hasPlanData ? (
                <>
                  <HeaderCell sortKey="planStock" sort={sort} onSort={onSort} align="right">
                    Stock
                  </HeaderCell>
                  <HeaderCell sortKey="coverageDays" sort={sort} onSort={onSort} align="right">
                    Coverage
                  </HeaderCell>
                  <HeaderCell sortKey="suggestedOrder" sort={sort} onSort={onSort} align="right">
                    Order
                  </HeaderCell>
                  <HeaderCell sortKey="gap" sort={sort} onSort={onSort} align="right">
                    Gap
                  </HeaderCell>
                  <HeaderCell sortKey={null} align="right">
                    Shortage
                  </HeaderCell>
                  <HeaderCell sortKey={null} align="right">
                    Deadline
                  </HeaderCell>
                  <HeaderCell sortKey={null} align="right">
                    Turnover
                  </HeaderCell>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {itemCount === 0 ? (
              <tr>
                <td
                  colSpan={colCount}
                  className="py-20 text-center font-serif italic text-muted-foreground border-t border-foreground/10"
                >
                  No SKUs match the current filters.
                </td>
              </tr>
            ) : pageSlice ? (
              pageSlice.map((group) => <SkuGroup key={group.sku} group={group} hasPlanData={hasPlanData} />)
            ) : flatPageSlice ? (
              flatPageSlice.map((r) => (
                <ExpandableResultRow key={`${r.site}-${r.sku}`} row={r} mode={mode} hasPlanData={hasPlanData} />
              ))
            ) : null}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 ? (
        <Pagination
          page={currentPage}
          totalPages={totalPages}
          onChange={setPage}
          totalItems={itemCount}
          pageSize={pageSize}
        />
      ) : (
        <div className="mt-4 font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
          {grouped ? `${itemCount} SKUs · ${filteredSorted.length} rows` : `${filteredSorted.length} rows`}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Table row
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// SKU Group (for split/all mode)
// ---------------------------------------------------------------------------

interface SkuGroupData {
  sku: string;
  name: string;
  abcClass: "A" | "B" | "C";
  isPriceMissing?: boolean;
  totalQty: number;
  items: SkuResult[];
}

function SkuGroup({ group, hasPlanData = false }: { group: SkuGroupData; hasPlanData?: boolean }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <>
      {/* Group header */}
      <tr
        onClick={() => setCollapsed((p) => !p)}
        className="border-t-2 border-foreground/20 bg-[#f4f1ec] cursor-pointer select-none hover:bg-[#ede8e0] transition-colors duration-300"
      >
        <td className="py-3 px-3">
          <span className="font-mono text-[10px] text-muted-foreground">
            {collapsed ? "▸" : "▾"} {group.items.length} sites
          </span>
        </td>
        <td className="py-3 px-3">
          <span className="font-mono text-xs font-medium text-foreground">{group.sku}</span>
        </td>
        <td className="py-3 px-3">
          <span className="font-sans text-sm text-foreground line-clamp-1 max-w-xs block">{group.name || "—"}</span>
        </td>
        <td className="py-3 px-3 text-center">
          <AbcBadge cls={group.abcClass} priceMissing={group.isPriceMissing} />
        </td>
        <td className="py-3 px-3 text-right">
          <span className="font-mono text-sm font-medium tabular-nums text-foreground">
            {formatNumber(group.totalQty, 0)}
          </span>
        </td>
        <td colSpan={8} className="py-3 px-3" />
      </tr>
      {/* Site rows within group */}
      {!collapsed &&
        group.items.map((r) => (
          <ExpandableResultRow key={`${r.site}-${r.sku}`} row={r} mode="all" indent hasPlanData={hasPlanData} />
        ))}
    </>
  );
}

function ExpandableResultRow({
  row,
  mode,
  indent,
  hasPlanData = false,
}: {
  row: SkuResult;
  mode: "all" | "total" | "single";
  indent?: boolean;
  hasPlanData?: boolean;
}) {
  const { parameters } = useWorkflow();
  const [expanded, setExpanded] = useState(false);
  const planExtraCols = hasPlanData ? 7 : 0;
  const colCount = (mode === "all" ? 13 : 12) + planExtraCols;

  const gran = parameters.granularity ?? "monthly";
  const dpp = gran === "daily" ? 1 : gran === "weekly" ? 7 : (parameters.workingDaysPerMonth ?? 30);
  const dailyDemand = row.meanDemand > 0 ? row.meanDemand / dpp : 0;

  return (
    <>
      <tr
        onClick={() => setExpanded((p) => !p)}
        className={cn(
          "border-t border-foreground/10 hover:bg-[#F3EEE7] transition-colors duration-300 cursor-pointer select-none",
          expanded && "bg-[#F3EEE7]",
          indent && "bg-[#faf8f5]"
        )}
      >
        {mode === "all" ? (
          <Cell>
            <span className={cn("font-mono text-xs", indent ? "pl-4 text-foreground" : "text-muted-foreground")}>
              {row.site}
            </span>
          </Cell>
        ) : null}
        <Cell>
          <span className="font-mono text-xs text-foreground">{indent ? "" : row.sku}</span>
        </Cell>
        <Cell>
          <span className="font-sans text-sm text-foreground/80 line-clamp-1 max-w-xs block">
            {indent ? "" : row.name || "—"}
          </span>
        </Cell>
        <Cell align="center">{indent ? null : <AbcBadge cls={row.abcClass} priceMissing={row.isPriceMissing} />}</Cell>
        <NumericCell value={row.totalQty} decimals={0} />
        <NumericCell value={row.meanDemand} decimals={0} />
        <NumericCell value={dailyDemand} decimals={0} />
        <NumericCell value={row.stdDev} decimals={0} />
        <NumericCell value={row.cv} decimals={2} />
        <NumericCell value={row.safetyStock} decimals={0} bold statusTone={row.status} />
        <NumericCell value={row.reorderPoint} decimals={0} />
        <NumericCell value={row.maxInventory} decimals={0} />
        <TrendCell label={row.trendLabel} pct={row.trendPct} />
        {hasPlanData ? (
          <>
            <NumericCell value={row.planStock ?? null} decimals={0} />
            <NumericCell value={row.coverageDays ?? null} decimals={1} />
            <NumericCell value={row.suggestedOrder ?? null} decimals={0} />
            <NumericCell value={row.gap ?? null} decimals={0} />
            <Cell align="right">
              <span className="font-mono text-xs text-muted-foreground">{row.firstShortageMonth ?? "—"}</span>
            </Cell>
            <Cell align="right">
              <span className="font-mono text-xs text-muted-foreground">{row.orderDeadline ?? "—"}</span>
            </Cell>
            <NumericCell value={row.turnoverRate ?? null} decimals={2} />
          </>
        ) : null}
      </tr>
      {expanded ? (
        <tr>
          <td colSpan={colCount} className="border-l-2 border-l-[color:var(--color-accent)] bg-[#F3EEE7]/50 px-6 py-5">
            <DemandDetail row={row} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Demand heatmap (expandable row content)
// ---------------------------------------------------------------------------

function DemandDetail({ row }: { row: SkuResult }) {
  const values = row.monthlyValues;
  if (!values || values.length === 0) {
    return <span className="font-serif italic text-sm text-muted-foreground">No period data available.</span>;
  }

  const mean = row.meanDemand;
  const ss = row.safetyStock;
  const maxVal = Math.max(...values, 1);
  const plan = row.monthlyPlan;
  const hasPlanDetail = plan && plan.length > 0;

  return (
    <div className="flex flex-col gap-8">
      {/* Data point warning (weekly mode) */}
      {row.dataPointWarning ? (
        <div className="text-xs text-muted-foreground border-l-2 border-foreground/20 pl-3 py-1">
          {row.dataPointWarning}
        </div>
      ) : null}

      {/* Row 1: demand bar chart + summary stats */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-8">
        {/* Left: demand bar chart */}
        <div>
          <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
            Demand by period
          </span>
          <div className="mt-3 flex items-end gap-[2px] h-16">
            {values.map((v, i) => {
              const h = Math.max(2, Math.round((v / maxVal) * 56));
              const bg =
                v <= 0
                  ? "bg-[color:var(--color-shortage)]/20"
                  : v >= mean
                    ? "bg-[color:var(--color-healthy)]/30"
                    : "bg-[color:var(--color-accent)]/30";
              return (
                <div
                  key={i}
                  className={cn("flex-1 min-w-[6px] max-w-[28px]", bg)}
                  style={{ height: `${h}px` }}
                  title={`P${i + 1}: ${formatNumber(v, 0)}`}
                />
              );
            })}
          </div>
          <div className="mt-1 flex gap-[2px]">
            {values.map((v, i) => (
              <span
                key={i}
                className="flex-1 min-w-[6px] max-w-[28px] text-center font-mono text-[8px] text-muted-foreground/50 tabular-nums truncate"
              >
                {v > 0 ? formatNumber(v, 0) : "0"}
              </span>
            ))}
          </div>
        </div>

        {/* Right: summary stats */}
        <div className="flex flex-col gap-3 min-w-[180px]">
          <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Summary</span>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-xs">
            <span className="text-muted-foreground">Mean</span>
            <span className="text-right tabular-nums">{formatNumber(mean, 0)}</span>
            <span className="text-muted-foreground">Std Dev</span>
            <span className="text-right tabular-nums">{formatNumber(row.stdDev, 0)}</span>
            <span className="text-muted-foreground">CV</span>
            <span className="text-right tabular-nums">{formatNumber(row.cv, 2)}</span>
            <span className="text-muted-foreground">Safety Stock</span>
            <span className="text-right tabular-nums font-medium">{formatNumber(ss, 0)}</span>
            <span className="text-muted-foreground">ROP</span>
            <span className="text-right tabular-nums">{formatNumber(row.reorderPoint, 0)}</span>
            <span className="text-muted-foreground">Max</span>
            <span className="text-right tabular-nums">{formatNumber(row.maxInventory, 0)}</span>
            <span className="text-muted-foreground">Periods</span>
            <span className="text-right tabular-nums">{values.length}</span>
            <span className="text-muted-foreground">Active</span>
            <span className="text-right tabular-nums">{values.filter((v) => v > 0).length}</span>
          </div>
        </div>
      </div>

      {/* Row 2: monthly stock projection (only when plan data exists) */}
      {hasPlanDetail ? (
        <div>
          <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
            Stock projection
          </span>
          <div className="mt-3 grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-8">
            {/* Left: projection table */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono">
                <thead>
                  <tr className="border-b border-foreground/10">
                    <th className="py-1.5 pr-4 text-left text-muted-foreground font-normal">Month</th>
                    <th className="py-1.5 px-3 text-right text-muted-foreground font-normal">Demand</th>
                    <th className="py-1.5 px-3 text-right text-muted-foreground font-normal">Supply</th>
                    <th className="py-1.5 px-3 text-right text-muted-foreground font-normal">Trfr In</th>
                    <th className="py-1.5 px-3 text-right text-muted-foreground font-normal">Trfr Out</th>
                    <th className="py-1.5 px-3 text-right text-muted-foreground font-normal">Net</th>
                    <th className="py-1.5 pl-3 text-right font-normal">Ending</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-b border-foreground/5">
                    <td className="py-1.5 pr-4 text-muted-foreground">Current</td>
                    <td colSpan={5}></td>
                    <td className="py-1.5 pl-3 text-right tabular-nums font-medium">
                      {formatNumber(row.planStock ?? 0, 0)}
                    </td>
                  </tr>
                  {plan.map((mp) => {
                    const isShortage = mp.endingStock < ss;
                    const monthLabel = `${mp.month.slice(0, 4)}/${mp.month.slice(4)}`;
                    return (
                      <tr
                        key={mp.month}
                        className={cn(
                          "border-b border-foreground/5",
                          isShortage && "text-[color:var(--color-shortage)]"
                        )}
                      >
                        <td className="py-1.5 pr-4">{monthLabel}</td>
                        <td className="py-1.5 px-3 text-right tabular-nums">
                          {mp.demand > 0 ? formatNumber(mp.demand, 0) : "—"}
                        </td>
                        <td className="py-1.5 px-3 text-right tabular-nums">
                          {mp.supply > 0 ? formatNumber(mp.supply, 0) : "—"}
                        </td>
                        <td className="py-1.5 px-3 text-right tabular-nums">
                          {mp.transferIn > 0 ? formatNumber(mp.transferIn, 0) : "—"}
                        </td>
                        <td className="py-1.5 px-3 text-right tabular-nums">
                          {mp.transferOut > 0 ? formatNumber(mp.transferOut, 0) : "—"}
                        </td>
                        <td className="py-1.5 px-3 text-right tabular-nums">{formatNumber(mp.netChange, 0)}</td>
                        <td
                          className={cn(
                            "py-1.5 pl-3 text-right tabular-nums",
                            isShortage ? "font-bold" : "font-medium"
                          )}
                        >
                          {formatNumber(mp.endingStock, 0)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Right: plan summary */}
            <div className="flex flex-col gap-3 min-w-[180px]">
              <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
                Plan summary
              </span>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 font-mono text-xs">
                <span className="text-muted-foreground">Current Stock</span>
                <span className="text-right tabular-nums">{formatNumber(row.planStock ?? 0, 0)}</span>
                <span className="text-muted-foreground">Final Stock</span>
                <span className="text-right tabular-nums">{formatNumber(row.finalStock ?? 0, 0)}</span>
                <span className="text-muted-foreground">Min Stock</span>
                <span className="text-right tabular-nums">{formatNumber(row.minStock ?? 0, 0)}</span>
                {row.minStockMonth ? (
                  <>
                    <span className="text-muted-foreground">Min Month</span>
                    <span className="text-right tabular-nums">{`${row.minStockMonth.slice(0, 4)}/${row.minStockMonth.slice(4)}`}</span>
                  </>
                ) : null}
                <span className="text-muted-foreground">Coverage</span>
                <span className="text-right tabular-nums">
                  {row.coverageDays != null ? `${formatNumber(row.coverageDays, 1)}d` : "—"}
                </span>
                <span className="text-muted-foreground">Gap</span>
                <span
                  className={cn("text-right tabular-nums", (row.gap ?? 0) < 0 && "text-[color:var(--color-shortage)]")}
                >
                  {row.gap != null ? formatNumber(row.gap, 0) : "—"}
                </span>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

function HeaderCell({
  children,
  sortKey,
  sort,
  onSort,
  align = "left",
}: {
  children: React.ReactNode;
  sortKey: SortKey | null;
  sort?: { key: SortKey; dir: SortDir };
  onSort?: (k: SortKey) => void;
  align?: "left" | "center" | "right";
}) {
  const clickable = sortKey && onSort;
  const active = sortKey && sort?.key === sortKey;
  return (
    <th
      scope="col"
      className={cn(
        "py-3 px-3 font-sans text-[10px] uppercase tracking-[0.25em] text-muted-foreground select-none",
        "border-b border-foreground/30",
        clickable && "cursor-pointer hover:text-foreground transition-colors duration-300",
        align === "right" && "text-right",
        align === "center" && "text-center",
        active && "text-foreground"
      )}
      onClick={() => clickable && onSort(sortKey!)}
    >
      <span className="inline-flex items-center gap-1">
        {children}
        {active ? <span className="text-accent">{sort!.dir === "asc" ? "↑" : "↓"}</span> : null}
      </span>
    </th>
  );
}

function Cell({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "center" | "right" }) {
  return (
    <td className={cn("py-3 px-3", align === "right" && "text-right", align === "center" && "text-center")}>
      {children}
    </td>
  );
}

function NumericCell({
  value,
  decimals,
  bold = false,
  statusTone,
}: {
  value: number | null | undefined;
  decimals: number;
  bold?: boolean;
  statusTone?: StockStatus;
}) {
  const tone =
    statusTone === "red"
      ? "text-[color:var(--color-shortage)]"
      : statusTone === "blue"
        ? "text-[color:var(--color-overstock)]"
        : "text-foreground";

  return (
    <td className="py-3 px-3 text-right">
      <span
        className={cn(
          "font-mono tabular-nums",
          bold ? "text-base font-medium" : "text-sm",
          bold ? tone : "text-foreground"
        )}
      >
        {formatNumber(value, decimals)}
      </span>
    </td>
  );
}

function TrendCell({ label, pct }: { label?: string; pct?: number | null }) {
  const display = label ?? "—";
  return (
    <td className="py-3 px-3 text-right">
      <span className="font-mono text-sm tabular-nums text-foreground">{display}</span>
    </td>
  );
}

function AbcBadge({ cls, priceMissing }: { cls: "A" | "B" | "C"; priceMissing?: boolean }) {
  const bg =
    cls === "A"
      ? "bg-[color:var(--color-abc-a)] text-background"
      : cls === "B"
        ? "bg-[color:var(--color-abc-b)] text-background"
        : "bg-[color:var(--color-abc-c)] text-background";
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center w-6 h-6",
        "font-mono text-[10px] font-medium",
        bg,
        priceMissing && "border border-dashed border-foreground/40"
      )}
      title={priceMissing ? "Classified by quantity (no price data)" : undefined}
    >
      {cls}
    </span>
  );
}

function StatusTabs({
  counts,
  active,
  onChange,
}: {
  counts: Record<"all" | StockStatus, number>;
  active: "all" | StockStatus;
  onChange: (v: "all" | StockStatus) => void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-6">
      {STATUS_FILTERS.map((f) => {
        const isActive = active === f.key;
        const count = counts[f.key];
        return (
          <button
            key={f.key}
            type="button"
            onClick={() => onChange(f.key)}
            className={cn(
              "text-left pb-2 border-b transition-colors duration-500 ease-luxury",
              isActive
                ? "border-accent text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            <span className="block font-sans text-[10px] uppercase tracking-[0.3em]">{f.description}</span>
            <span className="mt-1 block font-serif text-xl leading-none">
              {f.label} <span className="font-mono text-xs text-muted-foreground">{count}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function SiteDropdown({ sites, value, onChange }: { sites: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Site</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "mt-1 bg-transparent border-0 border-b border-foreground py-2 pr-6 min-w-[10rem]",
          "font-sans text-sm text-foreground appearance-none cursor-pointer",
          "focus:outline-none focus:border-accent transition-colors duration-500 ease-luxury"
        )}
      >
        <option value="all">All sites</option>
        {sites.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </div>
  );
}

function SearchInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Search</label>
      <input
        type="search"
        placeholder="SKU or product name"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "mt-1 bg-transparent border-0 border-b border-foreground py-2 w-full sm:w-64",
          "font-sans text-sm text-foreground placeholder:italic placeholder:text-muted-foreground/60",
          "focus:outline-none focus:border-accent transition-colors duration-500 ease-luxury"
        )}
      />
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  totalItems,
  pageSize,
  onChange,
}: {
  page: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onChange: (p: number) => void;
}) {
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalItems);

  return (
    <div className="mt-6 flex items-center justify-between gap-4 border-t border-foreground/10 pt-4">
      <div className="font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
        {start}–{end} of {totalItems}
      </div>
      <div className="flex items-center gap-2">
        <PageBtn disabled={page <= 1} onClick={() => onChange(page - 1)}>
          ←
        </PageBtn>
        <span className="px-2 font-mono text-xs text-foreground tabular-nums">
          {page} / {totalPages}
        </span>
        <PageBtn disabled={page >= totalPages} onClick={() => onChange(page + 1)}>
          →
        </PageBtn>
      </div>
    </div>
  );
}

function PageBtn({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex items-center justify-center w-8 h-8 border",
        "font-mono text-sm",
        disabled
          ? "border-foreground/10 text-foreground/20 cursor-not-allowed"
          : "border-foreground text-foreground hover:bg-foreground hover:text-background transition-colors duration-500 ease-luxury"
      )}
    >
      {children}
    </button>
  );
}
