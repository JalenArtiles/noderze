import "./globals.css";
import "./themes.css";
import Nav from "@/components/nav";
import LiveBar from "@/components/live";
import { ActivityProvider } from "@/components/activity";
import ThemeSync from "@/components/theme-sync";
import { DEFAULT_THEME, THEME_BOOT } from "@/lib/theme";

export const metadata = { title: "Noderze", description: "Your route from ASU to Sales Engineering", manifest: "/manifest.webmanifest" };
export const viewport = { themeColor: "#0a0d24" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme={DEFAULT_THEME} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} /></head>
      <body>
        <ThemeSync />
        <ActivityProvider>
          <div className="shell"><Nav /><main className="main"><LiveBar />{children}</main></div>
        </ActivityProvider>
      </body>
    </html>
  );
}
