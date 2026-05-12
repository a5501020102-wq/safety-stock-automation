"use client";

import { useWorkflow } from "@/lib/workflow-context";
import { formatNumber } from "@/lib/format";
import type { CalculationResponse, CalculationSummary, ComparisonStats, ParametersSnapshot } from "@/lib/types";

/**
 * ResultsSummary
 * ---------------------------------------------------------------------------
 * Renders the "deck" of the Analysis spread:
 *   1. ParametersSnapshot strip (immutable record of what was computed)
 *   2. Four editorial stat cards (per-mode shape)
 *
 * For single mode (all / total) we show health distribution.
 * For compare mode we show the inventory-saving headline.
 */
export function ResultsSummary() {
  const { calculationResult } = useWorkflow();
  if (!calculationResult) return null;

  return (
    <div className="mt-16 flex flex-col gap-16">
      <ParametersRow parameters={calculationResult.parameters} />
      <StatCards result={calculationResult} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Parameters snapshot strip
// ---------------------------------------------------------------------------

function ParametersRow({ parameters: p }: { parameters: ParametersSnapshot }) {
  const entries: Array<[string, React.ReactNode]> = [
    ["Mode", capitalizeMode(p.calcMode)],
    ["Granularity", capitalize(p.granularity ?? "monthly")],
    ["Range", p.dataMinDate && p.dataMaxDate ? `${p.dataMinDate} → ${p.dataMaxDate}` : "—"],
    ["Excluded", p.excludedMonth ?? "—"],
    ["Lead time", `${p.leadTimeDays} days`],
    ["Min periods", String(p.minMonths)],
    ["Z (A/B/C)", `${p.zScores.A} / ${p.zScores.B} / ${p.zScores.C}`],
    ["Months", `${p.selectedMonths.length}/12`],
    ["Outlier", p.enableOutlier ? "MAD enabled" : "Disabled"],
    ["MA", p.enableMa ? `Enabled (${p.maWindow})` : "Disabled"],
    ["Run time", `${Math.round(p.executionTimeMs)} ms`],
  ];

  return (
    <div className="border-t border-foreground/20 pt-6">
      <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">
        Calculated with
      </span>
      <dl className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-x-8 gap-y-4">
        {entries.map(([label, val]) => (
          <div key={label}>
            <dt className="font-sans text-[9px] uppercase tracking-[0.3em] text-muted-foreground/70">{label}</dt>
            <dd className="mt-1 font-mono text-sm text-foreground tabular-nums">{val}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat cards
// ---------------------------------------------------------------------------

function StatCards({ result }: { result: CalculationResponse }) {
  const cards = buildCards(result);

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
      {cards.map((c) => (
        <StatCard key={c.label} {...c} />
      ))}
    </div>
  );
}

interface CardSpec {
  label: string;
  value: string;
  hint: string;
  accent?: boolean; // gold left stripe
}

function StatCard({ label, value, hint, accent = false }: CardSpec) {
  return (
    <article
      className={`relative border-t border-foreground/25 pt-6 pl-4 min-h-[8rem] ${
        accent ? "border-l-[3px] border-l-accent" : ""
      }`}
    >
      <span className="block font-sans text-[10px] uppercase tracking-[0.3em] text-muted-foreground">{label}</span>
      <p className="mt-3 font-serif text-4xl md:text-5xl leading-none tabular-nums text-foreground">{value}</p>
      <p className="mt-3 font-sans text-xs leading-relaxed text-muted-foreground">{hint}</p>
    </article>
  );
}

// ---------------------------------------------------------------------------
// Shape the cards per-mode
// ---------------------------------------------------------------------------

function buildCards(result: CalculationResponse): CardSpec[] {
  if (result.mode === "compare") {
    const c: ComparisonStats = result.comparison;
    return [
      {
        label: "Split · Safety Stock",
        value: formatNumber(c.totalAllSafetyStock),
        hint: `${c.allSkuCount} SKUs across sites`,
      },
      {
        label: "Consolidated · Safety Stock",
        value: formatNumber(c.totalTotalSafetyStock),
        hint: `${c.totalSkuCount} SKUs pooled`,
      },
      {
        label: "Inventory Saved",
        value: formatNumber(c.inventorySaved),
        hint: `${c.savingsPercentage.toFixed(1)}% reduction`,
        accent: true,
      },
      {
        label: "Cost Saved",
        value: `$${formatNumber(Math.round(c.costSaved))}`,
        hint: `${c.savingsValuePercentage.toFixed(1)}% of split value`,
        accent: true,
      },
    ];
  }

  const s: CalculationSummary = result.summary;
  return [
    {
      label: "Valid SKUs",
      value: formatNumber(s.totalSkus),
      hint: `${s.excludedCount} excluded (insufficient data)`,
    },
    {
      label: "Shortage Risk",
      value: formatNumber(s.shortageRiskCount),
      hint: "Stock below safety line",
    },
    {
      label: "Healthy",
      value: formatNumber(s.healthyCount),
      hint: "Within policy range",
    },
    {
      label: "Overstock",
      value: formatNumber(s.overstockRiskCount),
      hint: "Above 3× safety stock",
    },
  ];
}

function capitalizeMode(mode: string): string {
  const map: Record<string, string> = {
    all: "Split",
    total: "Consolidated",
    compare: "Compare",
    single: "Single",
  };
  return map[mode] ?? mode;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
