"use client";

import { useWorkflow } from "@/lib/workflow-context";

/**
 * AnalysisEmpty
 * ---------------------------------------------------------------------------
 * 尚未產生計算結果時顯示的空狀態。
 */
export function AnalysisEmpty() {
  const { uploads, calculationResult } = useWorkflow();

  const hasSales = Boolean(uploads.sales?.fileId);

  if (calculationResult) return null;

  return (
    <div className="border-t border-foreground/15 pt-6">
      <span className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">尚未計算</span>

      <p className="mt-4 font-serif text-lg leading-tight text-foreground">
        {hasSales ? "請按上方的計算以產生分析結果。" : "請先上傳銷貨明細以啟用此區塊。"}
      </p>

      <p className="mt-4 max-w-xl font-sans text-sm leading-relaxed text-muted-foreground">
        分析結果將顯示於此：參數快照、摘要卡片、完整結果表格、篩選與匯出功能。
      </p>
    </div>
  );
}
