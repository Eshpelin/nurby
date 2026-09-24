import type { Metadata } from "next";
import "./globals.css";
import { AuthShell } from "@/components/auth-shell";
import { ErrorBoundary } from "@/components/error-boundary";
import { FeedbackProvider } from "@/lib/feedback";
import { ThemeProvider, themeInitScript } from "@/lib/theme";
import { WebcamPublisherProvider } from "@/lib/webcam-publisher";

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
      className="h-full antialiased"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <ThemeProvider>
          <FeedbackProvider>
            <AuthShell>
              <WebcamPublisherProvider>
                <ErrorBoundary>
                  {children}
                </ErrorBoundary>
              </WebcamPublisherProvider>
            </AuthShell>
          </FeedbackProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
