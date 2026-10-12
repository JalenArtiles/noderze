import "./globals.css";
import Nav from "@/components/nav";
import LiveBar from "@/components/live";
import { ActivityProvider } from "@/components/activity";

export const metadata = { title: "Noderze", description: "Your route from ASU to Sales Engineering", manifest: "/manifest.webmanifest" };
export const viewport = { themeColor: "#8c1d40" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en"><body>
      <ActivityProvider>
        <div className="shell"><Nav /><main className="main"><LiveBar />{children}</main></div>
      </ActivityProvider>
    </body></html>
  );
}
