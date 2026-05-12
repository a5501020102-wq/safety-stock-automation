"use client";

import { useCallback, useRef, useState } from "react";
import { ApiClientError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useUploadSlot, type UploadSlotType } from "@/lib/workflow-context";
import type { UploadPlanResponse, UploadPriceResponse, UploadSalesResponse } from "@/lib/types";

type UploadValue = UploadSalesResponse | UploadPriceResponse | UploadPlanResponse;

type UploadFn = (file: File, options?: { onProgress?: (e: { percent: number }) => void }) => Promise<UploadValue>;

interface UploadCardProps {
  slot: UploadSlotType;
  numeral: string;
  title: React.ReactNode;
  required?: boolean;
  hint: string;
}

/**
 * UploadCard
 * ---------------------------------------------------------------------------
 * 單一檔案上傳卡片。
 *
 * 狀態：
 *   1. Empty  — 尚未上傳
 *   2. Busy   — 上傳中
 *   3. Done   — 顯示檔案解析資訊
 *   4. Error  — 顯示錯誤訊息
 */
export function UploadCard({ slot, numeral, title, required = false, hint }: UploadCardProps) {
  const { value, set, clear } = useUploadSlot(slot);

  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setDragOver] = useState(false);
  const [isUploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const uploadFn: UploadFn =
    slot === "sales"
      ? (api.uploadSales as UploadFn)
      : slot === "price"
        ? (api.uploadPrice as UploadFn)
        : (api.uploadPlan as UploadFn);

  const handleFile = useCallback(
    async (file: File) => {
      const name = file.name.toLowerCase();

      if (!name.endsWith(".xlsx") && !name.endsWith(".xls")) {
        setError("僅支援 .xlsx 或 .xls 檔案");
        return;
      }

      setError(null);
      setUploading(true);
      setProgress(0);

      try {
        const result = await uploadFn(file, {
          onProgress: ({ percent }) => setProgress(percent),
        });
        set(result);
      } catch (e) {
        if (e instanceof ApiClientError) {
          setError(e.message);
        } else if (e instanceof DOMException && e.name === "AbortError") {
          setError("已取消上傳");
        } else {
          setError((e as Error).message || "上傳失敗");
        }
      } finally {
        setUploading(false);
      }
    },
    [uploadFn, set]
  );

  const onBrowse = () => inputRef.current?.click();

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  const onDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    if (!isUploading && !value) setDragOver(true);
  };

  const onDragLeave = (e: React.DragEvent) => {
    if (e.target === e.currentTarget) setDragOver(false);
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    if (isUploading || value) return;

    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const onReset = () => {
    clear();
    setError(null);
    setProgress(0);
  };

  const borderAccent = isDragOver ? "border-t-accent" : value ? "border-t-foreground" : "border-t-foreground/40";

  return (
    <article
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={cn(
        "relative flex min-h-[20rem] flex-col border-t-[3px] bg-background p-6 transition-colors duration-500 ease-luxury md:p-8",
        borderAccent,
        isDragOver && "bg-muted/40"
      )}
      aria-label={`${slot} upload slot`}
    >
      {/* Slot overline */}
      <div className="flex items-center justify-between gap-4">
        <span className="font-sans text-[10px] tracking-[0.3em] text-muted-foreground">
          <span className="text-foreground">{numeral}</span>
          <span className="mx-3">·</span>
          {required ? "必填" : "選填"}
        </span>

        {value && !isUploading ? (
          <button
            type="button"
            onClick={onReset}
            className="font-sans text-[10px] tracking-[0.2em] text-muted-foreground transition-colors duration-500 ease-luxury hover:text-accent"
          >
            清除
          </button>
        ) : null}
      </div>

      {/* Card title */}
      <h3 className="mt-5 font-serif text-3xl leading-[1.05] text-foreground md:text-4xl">{title}</h3>

      <p className="mt-3 font-sans text-sm leading-relaxed text-muted-foreground">{hint}</p>

      {/* Divider */}
      <div className="mt-5 h-px w-full bg-foreground/15" />

      {/* Body changes by state */}
      <div className="mt-5 flex flex-1 flex-col">
        {isUploading ? (
          <UploadBusy progress={progress} />
        ) : value ? (
          <UploadDone slot={slot} value={value} />
        ) : (
          <UploadIdle onBrowse={onBrowse} hasError={Boolean(error)} />
        )}
      </div>

      {/* Error message */}
      {error && !isUploading ? (
        <p className="mt-4 font-sans text-xs text-[color:var(--color-shortage)]">{error}</p>
      ) : null}

      {/* Hidden native input */}
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.xls"
        onChange={onInputChange}
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
      />
    </article>
  );
}

// ---------------------------------------------------------------------------
// Sub-states
// ---------------------------------------------------------------------------

function UploadIdle({ onBrowse, hasError }: { onBrowse: () => void; hasError: boolean }) {
  return (
    <div className="flex flex-1 flex-col items-start justify-end gap-4">
      <p className="font-serif text-base text-muted-foreground">
        {hasError ? "請重試，拖曳檔案或選擇檔案。" : "拖曳 .xlsx 檔案到這裡，或選擇檔案。"}
      </p>

      <button
        type="button"
        onClick={onBrowse}
        className="group/btn relative inline-flex items-center justify-center overflow-hidden border border-foreground bg-foreground px-8 py-3 font-sans text-[11px] tracking-[0.2em] text-background"
      >
        <span
          aria-hidden="true"
          className="absolute inset-0 -translate-x-full bg-accent transition-transform duration-500 ease-luxury group-hover/btn:translate-x-0"
        />
        <span className="relative z-10">選擇檔案</span>
      </button>
    </div>
  );
}

function UploadBusy({ progress }: { progress: number }) {
  const pct = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <div className="flex flex-1 flex-col justify-end gap-4">
      <div className="flex items-end justify-between">
        <span className="font-sans text-[10px] tracking-[0.3em] text-muted-foreground">上傳中</span>
        <span className="font-mono text-sm tabular-nums text-foreground">
          {pct}
          <span className="text-xs text-muted-foreground">%</span>
        </span>
      </div>

      <div className="relative h-px w-full overflow-hidden bg-foreground/15">
        <div
          className="absolute left-0 top-0 h-full bg-accent transition-[width] duration-200 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="font-serif text-sm text-muted-foreground">讀取檔案中…</p>
    </div>
  );
}

function UploadDone({ slot, value }: { slot: UploadSlotType; value: UploadValue }) {
  const rows: Array<[string, React.ReactNode]> = [];

  rows.push([
    "檔案",
    <span key="f" className="break-all font-mono text-xs">
      {value.filename}
    </span>,
  ]);

  rows.push(["大小", `${formatKB(value.fileSizeBytes)}`]);

  if (slot === "sales") {
    const v = value as UploadSalesResponse;
    rows.push(["筆數", v.recordCount.toLocaleString()]);
    rows.push(["出貨點", v.detectedSites.length > 0 ? v.detectedSites.join(", ") : "—"]);
    rows.push(["料號", v.detectedSkus.toLocaleString()]);
    rows.push(["範圍", v.dateRange.start && v.dateRange.end ? `${v.dateRange.start} → ${v.dateRange.end}` : "—"]);

    if (v.maxDate) {
      rows.push(["最新日期", v.maxDate.split("T")[0]]);
    }
  } else if (slot === "price") {
    const v = value as UploadPriceResponse;
    rows.push(["筆數", v.recordCount.toLocaleString()]);
  } else if (slot === "plan") {
    const v = value as UploadPlanResponse;
    rows.push(["項目", v.itemCount.toLocaleString()]);
    rows.push(["規劃期間", v.planningHorizon ?? "—"]);
  }

  return (
    <dl className="grid flex-1 grid-cols-[auto_1fr] content-start gap-x-6 gap-y-2 text-sm">
      {rows.map(([label, val]) => (
        <div key={label} className="contents text-sm">
          <dt className="pt-1 font-sans text-[10px] tracking-[0.3em] text-muted-foreground">{label}</dt>
          <dd className="font-sans text-foreground">{val}</dd>
        </div>
      ))}
    </dl>
  );
}

function formatKB(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
