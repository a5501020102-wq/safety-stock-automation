"use client";

import { useEffect, useId, useState } from "react";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { useWorkflow } from "@/lib/workflow-context";
import type { CalcMode, CalculateRequestParams, Granularity, MaterialCategory } from "@/lib/types";

/**
 * ParametersForm
 * ---------------------------------------------------------------------------
 * Section 02 · 參數設定。所有輸入都會同步到 WorkflowContext。
 */
export function ParametersForm() {
  const { parameters, setParameters, uploads } = useWorkflow();

  const set = setParameters;

  // ----- 計算模式 -----------------------------------------------------------
  const calcModes: { value: CalcMode; label: string; deck: string }[] = [
    {
      value: "compare",
      label: "對比",
      deck: "同時計算分倉與總倉，顯示庫存節省量。",
    },
    {
      value: "all",
      label: "分倉",
      deck: "每個出貨點獨立計算。",
    },
    {
      value: "total",
      label: "總倉",
      deck: "所有出貨點合併為一個虛擬總倉。",
    },
  ];

  // ----- 彙總粒度 -----------------------------------------------------------
  const granularityOptions: { value: Granularity; label: string; deck: string }[] = [
    {
      value: "monthly",
      label: "月",
      deck: "標準週期，每個日曆月一筆需求資料。",
    },
    {
      value: "weekly",
      label: "週",
      deck: "使用 ISO 週，適合需要較細需求分析的品項。",
    },
    {
      value: "daily",
      label: "日",
      deck: "使用日粒度，適合前置期較短的品項。",
    },
  ];

  // ----- ABC Z-score 選項 ---------------------------------------------------
  const zScoreOptions: Record<"A" | "B" | "C", { value: number; label: string }[]> = {
    A: [
      { value: 1.65, label: "95% (1.65)" },
      { value: 2.05, label: "98% (2.05)" },
      { value: 2.33, label: "99% (2.33)" },
    ],
    B: [
      { value: 1.28, label: "90% (1.28)" },
      { value: 1.65, label: "95% (1.65)" },
      { value: 1.96, label: "97.5% (1.96)" },
    ],
    C: [
      { value: 1.04, label: "85% (1.04)" },
      { value: 1.28, label: "90% (1.28)" },
      { value: 1.65, label: "95% (1.65)" },
    ],
  };

  const months = [
    [1, "一月"],
    [2, "二月"],
    [3, "三月"],
    [4, "四月"],
    [5, "五月"],
    [6, "六月"],
    [7, "七月"],
    [8, "八月"],
    [9, "九月"],
    [10, "十月"],
    [11, "十一月"],
    [12, "十二月"],
  ] as const;

  const isMonthSelected = (m: number) => parameters.selectedMonths?.includes(m) ?? false;

  const toggleMonth = (m: number) => {
    const cur = new Set(parameters.selectedMonths ?? []);
    if (cur.has(m)) cur.delete(m);
    else cur.add(m);
    set({ selectedMonths: Array.from(cur).sort((a, b) => a - b) });
  };

  const allMonths = () => set({ selectedMonths: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] });
  const noMonths = () => set({ selectedMonths: [] });

  // ----- 日期範圍 -----------------------------------------------------------
  const dataDateRange = {
    min: (uploads.sales as { dateRange?: { start?: string } } | null)?.dateRange?.start ?? "",
    max: (uploads.sales as { dateRange?: { end?: string } } | null)?.dateRange?.end ?? "",
  };
  const [seasonalOpen, setSeasonalOpen] = useState(false);

  // ----- 分類前置期 ---------------------------------------------------------
  const [materialCategories, setMaterialCategories] = useState<Record<string, MaterialCategory>>({});
  const [masterAvailable, setMasterAvailable] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .materialGroups()
      .then((res) => {
        if (cancelled) return;
        if (res.available) {
          setMaterialCategories(res.categories);
          setMasterAvailable(true);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const setCategoryLt = (catId: string, value: number | null) => {
    const prev = parameters.categoryLeadTimes ?? {};
    if (value === null) {
      const next = { ...prev };
      delete next[catId];
      set({ categoryLeadTimes: next });
    } else {
      set({ categoryLeadTimes: { ...prev, [catId]: value } });
    }
  };

  return (
    <div className="mt-10 grid grid-cols-1 gap-10 lg:grid-cols-12 lg:gap-12">
      {/* 左欄：計算策略 */}
      <div className="flex flex-col gap-10 lg:col-span-7">
        {/* 計算模式 */}
        <Group label="計算模式" deck="同一份資料的三種計算視角。">
          <div className="flex flex-col">
            {calcModes.map((m) => (
              <RadioRow
                key={m.value}
                name="calcMode"
                value={m.value}
                checked={parameters.calcMode === m.value}
                onChange={() => set({ calcMode: m.value })}
                label={m.label}
                deck={m.deck}
              />
            ))}
          </div>
        </Group>

        <Divider />

        {/* 彙總粒度 */}
        <Group label="彙總粒度" deck="設定需求分析的時間粒度。">
          <div className="flex flex-col">
            {granularityOptions.map((g) => (
              <RadioRow
                key={g.value}
                name="granularity"
                value={g.value}
                checked={(parameters.granularity ?? "monthly") === g.value}
                onChange={() => {
                  const patch: Partial<CalculateRequestParams> = { granularity: g.value };

                  if (g.value === "weekly") {
                    const weeks = (uploads.sales as { availableWeeks?: string[] } | null)?.availableWeeks ?? [];
                    if (weeks.length > 0) patch.selectedWeeks = [...weeks];
                  }

                  set(patch);
                }}
                label={g.label}
                deck={g.deck}
              />
            ))}
          </div>
        </Group>

        <Divider />

        {/* ABC 服務水準 */}
        <Group label="ABC 服務水準" deck="依 ABC 分級設定不同 Z 值，數值越高安全庫存越多。">
          <div className="grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-3">
            {(["A", "B", "C"] as const).map((tier) => (
              <UnderlineSelect
                key={tier}
                tier={tier}
                value={parameters.zScores?.[tier] ?? 0}
                options={zScoreOptions[tier]}
                onChange={(val) =>
                  set({
                    zScores: {
                      A: parameters.zScores?.A ?? 2.05,
                      B: parameters.zScores?.B ?? 1.65,
                      C: parameters.zScores?.C ?? 1.28,
                      [tier]: val,
                    },
                  })
                }
              />
            ))}
          </div>
        </Group>

        <Divider />

        {/* 時間參數 */}
        <Group label="時間參數" deck="設定前置期與納入計算所需的最少資料期數。">
          <div className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-3">
            <UnderlineNumber
              label="前置期"
              suffix="天"
              value={parameters.leadTime ?? 30}
              min={1}
              max={365}
              onChange={(v) => set({ leadTime: v })}
            />
            <UnderlineNumber
              label={parameters.granularity === "monthly" ? "最少月份" : "最少期數"}
              suffix={parameters.granularity === "monthly" ? "個月資料" : "有效期數"}
              value={parameters.minMonths ?? 2}
              min={0}
              max={12}
              onChange={(v) => set({ minMonths: v })}
            />
            {parameters.granularity === "monthly" ? (
              <UnderlineNumber
                label="每月工作天"
                suffix="天"
                value={parameters.workingDaysPerMonth ?? 30}
                min={1}
                max={31}
                onChange={(v) => set({ workingDaysPerMonth: v === 30 ? null : v })}
              />
            ) : null}
          </div>
        </Group>

        {/* 週別範圍，只在 weekly 模式顯示 */}
        {parameters.granularity === "weekly" ? (
          <WeekRangeSelector
            availableWeeks={(uploads.sales as { availableWeeks?: string[] } | null)?.availableWeeks ?? []}
            selectedWeeks={parameters.selectedWeeks}
            onChange={(weeks) => set({ selectedWeeks: weeks })}
          />
        ) : null}

        <Divider />

        {/* 統計處理 */}
        <Group label="統計處理" deck="計算安全庫存前套用的統計過濾方式。">
          <div className="flex flex-col gap-6">
            <ToggleRow
              label="MAD 離群值偵測"
              deck="使用中位數絕對偏差排除異常期間。"
              checked={parameters.enableOutlier ?? true}
              onChange={(c) => set({ enableOutlier: c })}
            />
            <ToggleRow
              label="移動平均"
              deck="使用滾動視窗平滑期間之間的需求波動。"
              checked={parameters.enableMa ?? false}
              onChange={(c) => set({ enableMa: c })}
            />

            {parameters.enableMa ? (
              <div className="ml-2 border-l border-foreground/15 pl-8">
                <span className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">視窗</span>
                <div className="mt-3 flex items-center gap-6">
                  <input
                    type="range"
                    min={2}
                    max={12}
                    step={1}
                    value={parameters.maWindow ?? 3}
                    onChange={(e) => set({ maWindow: Number(e.target.value) })}
                    className="flex-1 accent-[color:var(--color-accent)]"
                    aria-label="移動平均視窗"
                  />
                  <span className="w-20 text-right font-mono text-base tabular-nums text-foreground">
                    {parameters.maWindow ?? 3}{" "}
                    <span className="text-xs text-muted-foreground">
                      {parameters.granularity === "weekly" ? "週" : parameters.granularity === "daily" ? "天" : "月"}
                    </span>
                  </span>
                </div>
              </div>
            ) : null}
          </div>
        </Group>

        <Divider />

        {/* 趨勢偵測 */}
        <Group label="趨勢" deck="在結果中顯示需求趨勢百分比。">
          <div className="flex flex-col">
            {(
              [
                { value: "none", label: "不計算", deck: "不計算需求趨勢。" },
                { value: "short", label: "短期趨勢", deck: "比較資料前半段與後半段的需求變化。" },
                { value: "yoy", label: "年度同期比", deck: "比較最近兩年相同月份的需求變化。" },
              ] as const
            ).map((opt) => (
              <RadioRow
                key={opt.value}
                name="trendMode"
                value={opt.value}
                checked={(parameters.trendMode ?? "none") === opt.value}
                onChange={() => set({ trendMode: opt.value })}
                label={opt.label}
                deck={opt.deck}
              />
            ))}
          </div>
        </Group>
      </div>

      {/* 右欄：日期範圍與季節性過濾 */}
      <div className="flex flex-col gap-10 lg:col-span-5">
        {/* 日期範圍 */}
        <Group label="日期範圍" deck="使用此期間的資料進行計算。系統會依上傳資料自動帶入。">
          <div className="flex flex-col gap-4">
            <DateInput
              label="起"
              value={parameters.dateFrom ?? ""}
              placeholder={dataDateRange.min}
              onChange={(v) => set({ dateFrom: v || null })}
            />
            <DateInput
              label="迄"
              value={parameters.dateTo ?? ""}
              placeholder={dataDateRange.max}
              onChange={(v) => set({ dateTo: v || null })}
            />
            <span className="font-sans text-[10px] text-muted-foreground/60">空白表示使用上傳資料的完整期間</span>
          </div>
        </Group>

        <Divider />

        {/* 季節性過濾 */}
        <div>
          <button
            type="button"
            onClick={() => setSeasonalOpen((p) => !p)}
            className="border-b border-muted-foreground pb-1 font-sans text-[11px] tracking-[0.2em] text-muted-foreground transition-colors duration-500 ease-luxury hover:border-accent hover:text-accent"
          >
            {seasonalOpen ? "▵ 收合" : "▿ 進階"} · 季節性過濾
          </button>

          {seasonalOpen ? (
            <div className="mt-6">
              <p className="max-w-md font-serif text-xs text-muted-foreground">
                排除特定月份。只有勾選的月份會納入計算。
              </p>
              <div className="mt-4 grid grid-cols-3 gap-x-4 gap-y-3">
                {months.map(([num, name]) => (
                  <MonthCheckbox
                    key={num}
                    label={name}
                    num={num}
                    checked={isMonthSelected(num)}
                    onChange={() => toggleMonth(num)}
                  />
                ))}
              </div>
              <div className="mt-4 flex items-center gap-4">
                <button
                  type="button"
                  onClick={allMonths}
                  className="border-b border-foreground pb-1 font-sans text-[11px] tracking-[0.2em] text-foreground transition-colors duration-500 ease-luxury hover:border-accent hover:text-accent"
                >
                  全選
                </button>
                <button
                  type="button"
                  onClick={noMonths}
                  className="border-b border-muted-foreground pb-1 font-sans text-[11px] tracking-[0.2em] text-muted-foreground transition-colors duration-500 ease-luxury hover:border-accent hover:text-accent"
                >
                  清除
                </button>
                <span className="ml-auto font-mono text-xs tabular-nums text-muted-foreground">
                  {parameters.selectedMonths?.length ?? 0} / 12
                </span>
              </div>
            </div>
          ) : null}
        </div>

        {/* 計算政策預覽 */}
        <div className="border-t border-foreground/15 pt-6">
          <span className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">計算政策預覽</span>
          <p className="mt-3 font-serif text-base leading-relaxed text-foreground">{summarizePolicy(parameters)}</p>
        </div>
      </div>

      {/* 分類前置期 */}
      {masterAvailable ? (
        <div className="border-t border-foreground/10 pt-8 lg:col-span-12">
          <button
            type="button"
            onClick={() => setAdvancedOpen((p) => !p)}
            className="border-b border-muted-foreground pb-1 font-sans text-[11px] tracking-[0.2em] text-muted-foreground transition-colors duration-500 ease-luxury hover:border-accent hover:text-accent"
          >
            {advancedOpen ? "▵ 收合" : "▿ 進階"} · 分類前置期
          </button>

          {advancedOpen ? (
            <div className="mt-8">
              <p className="max-w-xl font-serif text-sm text-muted-foreground">
                可針對特定產品分類覆寫全域前置期。空白欄位會沿用上方的全域設定。
              </p>

              <div className="mt-6 grid grid-cols-1 gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(materialCategories)
                  .sort(([, a], [, b]) => b.totalCount - a.totalCount)
                  .map(([catId, cat]) => (
                    <CategoryLtInput
                      key={catId}
                      catId={catId}
                      name={cat.name}
                      count={cat.totalCount}
                      value={parameters.categoryLeadTimes?.[catId] ?? null}
                      defaultLt={parameters.leadTime ?? 30}
                      onChange={(v) => setCategoryLt(catId, v)}
                    />
                  ))}
              </div>

              <div className="mt-6">
                <button
                  type="button"
                  onClick={() => set({ categoryLeadTimes: {} })}
                  className="border-b border-muted-foreground pb-1 font-sans text-[11px] tracking-[0.2em] text-muted-foreground transition-colors duration-500 ease-luxury hover:border-accent hover:text-accent"
                >
                  全部重設為預設值
                </button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ===========================================================================
// Sub-primitives
// ===========================================================================

function DateInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  onChange: (val: string) => void;
}) {
  const id = useId();
  const displayPlaceholder = placeholder ? placeholder.replace(/-/g, "/") : "YYYY/MM/DD";

  return (
    <div>
      <label htmlFor={id} className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        placeholder={displayPlaceholder}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw);
        }}
        className={cn(
          "mt-2 w-full border-0 border-b bg-transparent py-2",
          "font-mono text-sm tabular-nums",
          "transition-colors duration-500 ease-luxury focus:outline-none",
          value
            ? "border-foreground text-foreground focus:border-accent"
            : "border-foreground/30 text-muted-foreground placeholder:italic focus:border-accent"
        )}
      />
    </div>
  );
}

function CategoryLtInput({
  catId,
  name,
  count,
  value,
  defaultLt,
  onChange,
}: {
  catId: string;
  name: string;
  count: number;
  value: number | null;
  defaultLt: number;
  onChange: (v: number | null) => void;
}) {
  const id = useId();
  const hasOverride = value !== null;

  return (
    <div>
      <label htmlFor={id} className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">
        {name}
      </label>
      <span className="mt-1 block font-mono text-[10px] text-muted-foreground/60">
        {catId} · {count.toLocaleString()} 個品項
      </span>
      <div className="mt-2 flex items-center gap-3">
        <input
          id={id}
          type="number"
          min={1}
          max={365}
          placeholder={`${defaultLt}`}
          value={hasOverride ? value : ""}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") {
              onChange(null);
            } else {
              const n = parseInt(raw, 10);
              if (!isNaN(n) && n >= 1 && n <= 365) onChange(n);
            }
          }}
          className={cn(
            "w-20 border-0 border-b bg-transparent py-2",
            "font-mono text-sm tabular-nums",
            "transition-colors duration-500 ease-luxury focus:outline-none",
            hasOverride
              ? "border-foreground text-foreground focus:border-accent"
              : "border-foreground/30 text-muted-foreground/50 focus:border-accent"
          )}
        />
        <span className="font-sans text-xs text-muted-foreground">天</span>
        {!hasOverride ? <span className="font-serif text-xs text-muted-foreground/40">預設：{defaultLt}</span> : null}
      </div>
    </div>
  );
}

function Group({ label, deck, children }: { label: string; deck?: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">{label}</span>
      {deck ? <p className="mt-2 max-w-md font-serif text-sm text-muted-foreground">{deck}</p> : null}
      <div className="mt-6">{children}</div>
    </div>
  );
}

function Divider() {
  return <div className="h-px w-full bg-foreground/15" />;
}

function RadioRow({
  name,
  value,
  checked,
  onChange,
  label,
  deck,
}: {
  name: string;
  value: string;
  checked: boolean;
  onChange: () => void;
  label: string;
  deck?: string;
}) {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className={cn(
        "group/radio flex cursor-pointer items-start gap-4 border-t border-foreground/10 py-4 transition-colors duration-500 ease-luxury",
        "hover:border-foreground/40",
        checked && "border-foreground/40"
      )}
    >
      <input id={id} type="radio" name={name} value={value} checked={checked} onChange={onChange} className="sr-only" />
      <span
        aria-hidden="true"
        className={cn(
          "mt-1 inline-block h-3 w-3 border border-foreground transition-colors duration-500 ease-luxury",
          checked ? "bg-foreground" : "bg-transparent"
        )}
      />
      <div className="flex-1">
        <span
          className={cn(
            "font-serif text-xl leading-tight transition-colors duration-500 ease-luxury",
            checked ? "text-foreground" : "text-foreground/70"
          )}
        >
          {label}
        </span>
        {deck ? <p className="mt-1 font-sans text-sm text-muted-foreground">{deck}</p> : null}
      </div>
    </label>
  );
}

function UnderlineSelect({
  tier,
  value,
  options,
  onChange,
}: {
  tier: "A" | "B" | "C";
  value: number;
  options: { value: number; label: string }[];
  onChange: (val: number) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">
        等級 <span className="text-foreground">{tier}</span>
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={cn(
          "mt-2 w-full cursor-pointer appearance-none border-0 border-b border-foreground bg-transparent py-2",
          "font-sans text-base text-foreground",
          "transition-colors duration-500 ease-luxury focus:border-accent focus:outline-none"
        )}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function UnderlineNumber({
  label,
  suffix,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  suffix?: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (val: number) => void;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">
        {label}
      </label>
      <div className="mt-2 flex items-baseline gap-3 border-b border-foreground py-2 transition-colors duration-500 ease-luxury focus-within:border-accent">
        <input
          id={id}
          type="number"
          value={value}
          min={min}
          max={max}
          onChange={(e) => {
            const next = Number(e.target.value);
            if (!Number.isFinite(next)) return;
            if (min !== undefined && next < min) return;
            if (max !== undefined && next > max) return;
            onChange(next);
          }}
          className={cn("w-24 border-0 bg-transparent outline-none", "font-mono text-2xl tabular-nums text-foreground")}
        />
        {suffix ? <span className="font-serif text-sm text-muted-foreground">{suffix}</span> : null}
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  deck,
  checked,
  onChange,
}: {
  label: string;
  deck?: string;
  checked: boolean;
  onChange: (c: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="flex-1">
        <label htmlFor={id} className="cursor-pointer font-serif text-lg leading-tight text-foreground">
          {label}
        </label>
        {deck ? <p className="mt-1 font-sans text-sm text-muted-foreground">{deck}</p> : null}
      </div>

      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative mt-1 inline-flex h-6 w-12 shrink-0 items-center border transition-colors duration-500 ease-luxury",
          checked ? "border-foreground bg-foreground" : "border-foreground/40 bg-transparent"
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "inline-block h-4 w-4 transition-transform duration-500 ease-luxury",
            checked ? "translate-x-7 bg-accent" : "translate-x-1 bg-foreground/40"
          )}
        />
      </button>
    </div>
  );
}

function MonthCheckbox({
  label,
  num,
  checked,
  onChange,
}: {
  label: string;
  num: number;
  checked: boolean;
  onChange: () => void;
}) {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className={cn(
        "group/m flex cursor-pointer items-center gap-3 border px-3 py-2 transition-colors duration-500 ease-luxury",
        checked
          ? "border-foreground/20 border-l-[3px] border-l-accent bg-[#E3DBCF] text-foreground"
          : "border-foreground/10 bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
      )}
    >
      <input id={id} type="checkbox" checked={checked} onChange={onChange} className="sr-only" />
      <span
        className={cn(
          "font-mono text-[10px] tracking-[0.2em] transition-colors duration-500 ease-luxury",
          checked ? "text-foreground/60" : "text-muted-foreground/60"
        )}
      >
        {String(num).padStart(2, "0")}
      </span>
      <span className="font-serif text-sm">{label}</span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function summarizePolicy(p: ReturnType<typeof useWorkflow>["parameters"]): string {
  const z = p.zScores ?? { A: 2.05, B: 1.65, C: 1.28 };
  const months = p.selectedMonths?.length ?? 12;
  const ma = p.enableMa ? `，移動平均(${p.maWindow ?? 3})` : "";
  const outlier = p.enableOutlier ? "" : "，保留離群值";
  const gran = formatGranularity(p.granularity ?? "monthly");
  const dateRange = p.dateFrom && p.dateTo ? ` · ${p.dateFrom}~${p.dateTo}` : "";
  const modeLabel = formatCalcMode(p.calcMode ?? "compare");

  return (
    `${modeLabel} · ${gran} · 前置期 ${p.leadTime ?? 30} 天 · 最少 ${p.minMonths ?? 2} 期 · ` +
    `Z(${z.A}/${z.B}/${z.C}) · 已選 ${months}/12 個月${dateRange}${ma}${outlier}`
  );
}

function formatCalcMode(mode: CalcMode): string {
  if (mode === "compare") return "對比";
  if (mode === "all") return "分倉";
  if (mode === "total") return "總倉";
  return "對比";
}

function formatGranularity(granularity: Granularity): string {
  if (granularity === "monthly") return "月";
  if (granularity === "weekly") return "週";
  if (granularity === "daily") return "日";
  return "月";
}

// ---------------------------------------------------------------------------
// Week range selector
// ---------------------------------------------------------------------------

function WeekRangeSelector({
  availableWeeks,
  selectedWeeks,
  onChange,
}: {
  availableWeeks: string[];
  selectedWeeks?: string[];
  onChange: (weeks: string[]) => void;
}) {
  if (availableWeeks.length === 0) {
    return <div className="mt-4 font-serif text-sm text-muted-foreground">請先上傳銷貨資料以查看可用週別。</div>;
  }

  const fromWeek = selectedWeeks?.[0] ?? availableWeeks[0];
  const toWeek = selectedWeeks?.[selectedWeeks.length - 1] ?? availableWeeks[availableWeeks.length - 1];

  const setRange = (from: string, to: string) => {
    const fromIdx = availableWeeks.indexOf(from);
    const toIdx = availableWeeks.indexOf(to);
    if (fromIdx < 0 || toIdx < 0) return;
    const start = Math.min(fromIdx, toIdx);
    const end = Math.max(fromIdx, toIdx);
    onChange(availableWeeks.slice(start, end + 1));
  };

  const presets = [
    { label: "近 4 週", count: 4 },
    { label: "近 8 週", count: 8 },
    { label: "近 12 週", count: 12 },
    { label: "全部", count: availableWeeks.length },
  ];

  const weekCount = selectedWeeks?.length ?? availableWeeks.length;

  return (
    <div className="mt-4 flex flex-col gap-4">
      <div className="flex items-baseline gap-3">
        <span className="font-sans text-[10px] tracking-[0.3em] text-muted-foreground">週別範圍</span>
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {weekCount} 週（{weekCount * 7} 天）
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">起</span>
          <select
            className="border-b border-foreground/20 bg-transparent px-2 py-1 font-mono text-xs focus:border-foreground focus:outline-none"
            value={fromWeek}
            onChange={(e) => setRange(e.target.value, toWeek)}
          >
            {availableWeeks.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">迄</span>
          <select
            className="border-b border-foreground/20 bg-transparent px-2 py-1 font-mono text-xs focus:border-foreground focus:outline-none"
            value={toWeek}
            onChange={(e) => setRange(fromWeek, e.target.value)}
          >
            {availableWeeks.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-center gap-2">
          {presets.map((p) => (
            <button
              key={p.label}
              type="button"
              className={cn(
                "border px-2 py-0.5 text-[10px] tracking-wider transition-colors",
                weekCount === p.count
                  ? "border-foreground text-foreground"
                  : "border-foreground/20 text-muted-foreground hover:border-foreground/40"
              )}
              onClick={() => {
                const start = Math.max(0, availableWeeks.length - p.count);
                onChange(availableWeeks.slice(start));
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
