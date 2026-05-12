"use client";

import { UploadCard } from "./UploadCard";
import { useWorkflow } from "@/lib/workflow-context";

/**
 * UploadsSection
 * ---------------------------------------------------------------------------
 * 顯示三個上傳區塊：銷貨明細、單價表、庫存計畫。
 *
 * - 銷貨明細為必填。
 * - 單價表與庫存計畫為選填。
 * - 下方狀態列顯示目前已上傳的資料來源數量。
 */
export function UploadsSection() {
  const { uploads } = useWorkflow();

  const loadedCount = [uploads.sales, uploads.price, uploads.plan].filter(Boolean).length;
  const ready = Boolean(uploads.sales);

  return (
    <div className="mt-10">
      {/* Three-slot upload grid */}
      <div className="grid grid-cols-1 gap-8 md:grid-cols-2 md:gap-10 lg:grid-cols-12">
        {/* Sales — required */}
        <div className="lg:col-span-6">
          <UploadCard
            slot="sales"
            numeral="I"
            required
            title={
              <>
                銷貨
                <br />
                <em className="italic text-accent">明細</em>
              </>
            }
            hint="出貨點、料號、日期、數量。此檔必填。"
          />
        </div>

        {/* Price */}
        <div className="lg:col-span-3">
          <UploadCard
            slot="price"
            numeral="II"
            title={
              <>
                單價
                <br />
                <em className="italic text-accent">表</em>
              </>
            }
            hint="料號、單價。用於 ABC 分級。選填。"
          />
        </div>

        {/* Plan */}
        <div className="lg:col-span-3">
          <UploadCard
            slot="plan"
            numeral="III"
            title={
              <>
                庫存
                <br />
                <em className="italic text-accent">計畫</em>
              </>
            }
            hint="ERP 計畫：需求、供給、調撥。選填。"
          />
        </div>
      </div>

      {/* Status strip */}
      <div className="mt-8 flex flex-col items-start justify-between gap-4 border-t border-foreground/15 pt-5 md:flex-row md:items-end">
        <div>
          <span className="block font-sans text-[10px] tracking-[0.3em] text-muted-foreground">狀態</span>

          <p className="mt-2 font-serif text-lg leading-tight text-foreground">
            {ready ? (
              <>
                {loadedCount} / 3 個資料來源已連結。可進入
                <em className="not-italic text-accent">參數設定</em>。
              </>
            ) : (
              <>請先上傳銷貨明細。</>
            )}
          </p>
        </div>

        {ready ? (
          <a
            href="#configuration"
            className="border-b border-foreground pb-1 font-sans text-[11px] tracking-[0.2em] text-foreground transition-colors duration-500 ease-luxury hover:border-accent hover:text-accent"
          >
            前往 02 · 參數設定 →
          </a>
        ) : null}
      </div>
    </div>
  );
}
