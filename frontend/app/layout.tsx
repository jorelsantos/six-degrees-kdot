import type { Metadata } from "next";
import { figtree } from "./fonts";
import { SiteFooter } from "./components/site-footer";
import "./globals.css";

export const metadata: Metadata = {
  title: "Rabbit Hole — Six Degrees of Kendrick Lamar",
  description:
    "An unofficial concept: find the collaboration path between any artist and Kendrick Lamar. Not affiliated with Spotify.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${figtree.variable} h-full`}>
      <body className="min-h-full flex flex-col bg-surface-base text-content-primary">
        <main className="flex-1 w-full">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
