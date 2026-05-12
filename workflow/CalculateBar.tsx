"use client";

import { useCallback, useEffect, useRef } from "react";
import { ApiClientError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useWorkflow } from "@/lib/workflow-context";

/**
 * CalculateBar
 * ---------------------------------------------------------------------------
 * 位於「參數設定」與「分析結果」之間的計算操作列。
 */
export function CalculateBar() {
  const {
    uploads,
    parameters,
    isCalculating,
    calculationError,
    calculationResult,
    setCalculating,
    setCalculationError,
    setCalculationResult,
  } = useWorkflow();

  const hasSales = Boolean(uploads.sales?.fileId);
  const hasSelectedMonths = (parameters.selectedMonths?.length ?? 0) > 0;
  const hasDateRange = !!(parameters.dateFrom && parameters.dateTo);
  const hasTimeFilter = hasSelectedMonths || hasDateRange;
  const canCalculate = hasSales && hasTimeFilter && !isCalculating;

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const run = useCallback(async () => {
    if (!canCalculate) return;

    abortRef.current?.abort();
    abortRef.current = new AbortController();

    setCalculationError(null);
    setCalculating(true);

    try {
      const result = await api.calculate({
        salesFileId: uploads.sales!.fileId,
        priceFileId: uploads.price?.fileId ?? null,
        planFileId: uploads.plan?.fileId ?? null,
        params: parameters,
      });

      setCalculationResult(result);

      requestAnimationFrame(() => {
        document.getElementById("analysis")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    } catch (err) {
      if (err instanceof ApiClientError) {
        setCalculationError(`[${err.code}] ${err.message}`);
      } else if (err instanceof DOMException && err.name === "AbortError") {
        // 使用者離開頁面或取消請求時不顯示錯誤
      } else {
        setCalculationError((err as Error).message || "計算失敗");
      }
    } finally {
      setCalculating(false);
    }
  }, [
    canCalculate,
    parameters,
    uploads.sales,
    uploads.price,
    uploads.plan,
    setCalculating,
    setCalculationError,
    setCalculationResult,
  ]);

  const reason = !hasSales
    ? "請先上傳銷貨明細。"
    : !hasTimeFilter
      ? "請設定日期範圍或至少選擇一個月份。"
      : isCalculating
        ? "計算中…"
        : calculationResult
          ? "下方已有結果，可重新計算。"
          : "設定完成，請按計算。";

  return (
    <div className="mt-16 border-t border-foreground/25 pt-8 md:mt-20 md:pt-10">
      <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex-1">
          <span className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">下一步</span>

          <p
            className={cn(
              "mt-3 font-serif text-xl leading-tight md:text-2xl",
              isCalculating ? "text-accent" : "text-foreground"
            )}
          >
            {reason}
          </p>

          {calculationError ? (
            <p className="mt-4 font-sans text-sm leading-relaxed text-[color:var(--color-shortage)]">
              {calculationError}
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={run}
            disabled={!canCalculate}
            className={cn(
              "group/cta relative inline-flex h-14 items-center justify-center overflow-hidden",
              "border border-foreground px-12",
              "font-sans text-xs tracking-[0.3em]",
              "transition-colors duration-500 ease-luxury",
              canCalculate
                ? "cursor-pointer bg-foreground text-background"
                : "cursor-not-allowed border-foreground/25 bg-transparent text-foreground/30"
            )}
            aria-busy={isCalculating}
            aria-disabled={!canCalculate}
          >
            {canCalculate && !isCalculating ? (
              <span
                aria-hidden="true"
                className="absolute inset-0 -translate-x-full bg-accent transition-transform duration-500 ease-luxury group-hover/cta:translate-x-0"
              />
            ) : null}

            <span className="relative z-10 flex items-center gap-3">
              {isCalculating ? (
                <>
                  <Spinner />
                  計算中
                </>
              ) : calculationResult ? (
                "重新計算"
              ) : (
                "計算"
              )}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3 w-3 animate-spin border-r border-t border-background"
      style={{ animationDuration: "800ms" }}
    />
  );
}
