import type { Metadata } from "next";
import { Inter, Playfair_Display, Noto_Sans_TC, Noto_Serif_TC, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { PaperNoise } from "@/components/layout/PaperNoise";
import { VerticalGridlines } from "@/components/layout/VerticalGridlines";
import { ui } from "@/lib/i18n";
/**
 * Font pairing rationale:
 * - Playfair Display: high-contrast serif for editorial headlines.
 * - Inter: humanist sans-serif for body / UI.
 * - Noto Sans/Serif TC: Chinese fallback, matched visual weight.
 * - JetBrains Mono: for tabular data (SKU IDs, numeric columns).
 */
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "700"],
  style: ["normal", "italic"],
});

const notoSansTC = Noto_Sans_TC({
  variable: "--font-noto-sans-tc",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "700"],
});

const notoSerifTC = Noto_Serif_TC({
  variable: "--font-noto-serif-tc",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "700"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: ui.app.title,
  description: ui.app.description,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const fontVars = [
    inter.variable,
    playfair.variable,
    notoSansTC.variable,
    notoSerifTC.variable,
    jetbrainsMono.variable,
  ].join(" ");

  return (
    <html lang="zh-TW" className={`${fontVars} h-full antialiased`}>
      <body className="relative min-h-full overflow-x-hidden">
        {/* Decorative layers — pointer-events:none so they never block UI */}
        <VerticalGridlines />
        <PaperNoise />

        {/* Content */}
        <div className="relative z-10 min-h-full">{children}</div>
      </body>
    </html>
  );
}
