import { SectionHeader } from "@/components/layout/SectionHeader";
import { WorkflowProvider } from "@/lib/workflow-context";
import { UploadsSection } from "@/components/workflow/UploadsSection";
import { ParametersForm } from "@/components/workflow/ParametersForm";
import { CalculateBar } from "@/components/workflow/CalculateBar";
import { ResultsSummary } from "@/components/workflow/ResultsSummary";
import { ResultsTable } from "@/components/workflow/ResultsTable";
import { AnalysisEmpty } from "@/components/workflow/AnalysisEmpty";

export default function Home() {
  return (
    <main className="relative">
      {/* Compact cover */}
      <section className="relative border-b border-foreground/20 px-6 py-10 md:px-12 md:py-14">
        <div className="flex items-center gap-4">
          <span className="h-px w-8 bg-foreground" />
          <span className="font-sans text-[10px] tracking-[0.25em] text-muted-foreground">
            2026 年第 05 版 · 安全庫存分析
          </span>
        </div>

        <h1 className="mt-8 font-serif text-6xl leading-[0.9] tracking-tight text-foreground sm:text-7xl md:text-8xl lg:text-9xl">
          安全
          <br />
          <span className="italic text-accent">庫存</span>
        </h1>

        <p className="mt-8 max-w-2xl font-sans text-base leading-relaxed text-muted-foreground md:text-lg">
          透過歷史銷貨資料進行安全庫存分析。上傳資料、設定參數，快速查看分析結果與補貨建議。
        </p>
      </section>

      <WorkflowProvider>
        {/* Section 01 · Sources */}
        <section id="sources" className="relative px-6 py-10 md:px-12 md:py-14">
          <SectionHeader
            numeral="01"
            overline="資料來源"
            title="上傳"
            italicAccent="資料"
            deck={<>上傳銷貨明細、單價表與庫存計畫。銷貨明細為必填。</>}
            meta="上傳"
          />

          <UploadsSection />
        </section>

        {/* Section 02 · Configuration */}
        <section id="configuration" className="relative px-6 py-10 md:px-12 md:py-14">
          <SectionHeader
            numeral="02"
            overline="參數設定"
            title="計算"
            italicAccent="條件"
            deck={<>設定服務水準、前置期、ABC 門檻、日期範圍與統計處理方式。</>}
            meta="參數"
          />

          <ParametersForm />
          <CalculateBar />
        </section>

        {/* Section 03 · Analysis */}
        <section id="analysis" className="relative px-6 py-10 md:px-12 md:py-14">
          <SectionHeader
            numeral="03"
            overline="分析結果"
            title="計算"
            italicAccent="結果"
            deck={<>檢視摘要統計、SKU 明細、排除項目，並匯出 Excel 或 SAP MM17 檔案。</>}
            meta="結果"
          />

          <AnalysisEmpty />
          <ResultsSummary />
          <ResultsTable />
        </section>
      </WorkflowProvider>

      <footer className="border-t border-foreground/20 px-6 py-6 md:px-12">
        <p className="font-sans text-xs text-muted-foreground">安全庫存計算系統</p>
      </footer>
    </main>
  );
}
