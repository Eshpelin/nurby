import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { AuthShell } from "@/components/auth-shell";
import { ErrorBoundary } from "@/components/error-boundary";
import { FeedbackProvider } from "@/lib/feedback";
import { ThemeProvider, themeInitScript } from "@/lib/theme";
import { WebcamPublisherProvider } from "@/lib/webcam-publisher";
import { WebSocketProvider } from "@/lib/ws";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Nurby",
  description: "AI camera monitoring platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        {/* Google Analytics (GA4). Loaded once at the root so it covers every
            route. Guarded to production so localhost dev traffic does not
            pollute the real property. */}
        {process.env.NODE_ENV === "production" && (
          <>
            <Script
              src="https://www.googletagmanager.com/gtag/js?id=G-GQXBVMRY6Z"
              strategy="afterInteractive"
            />
            <Script id="google-analytics" strategy="afterInteractive">
              {`
                window.dataLayer = window.dataLayer || [];
                function gtag(){dataLayer.push(arguments);}
                gtag('js', new Date());
                gtag('config', 'G-GQXBVMRY6Z');
              `}
            </Script>
          </>
        )}
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ThemeProvider>
          <FeedbackProvider>
            <AuthShell>
              <WebcamPublisherProvider>
                <WebSocketProvider>
                  <ErrorBoundary>
                    {children}
                  </ErrorBoundary>
                </WebSocketProvider>
              </WebcamPublisherProvider>
            </AuthShell>
          </FeedbackProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
