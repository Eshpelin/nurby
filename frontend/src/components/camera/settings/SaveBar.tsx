// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import Link from "next/link";

interface SaveBarProps {
  error: string | null;
  saved: boolean;
  saving: boolean;
}

export function SaveBar({
  error,
  saved,
  saving,
}: SaveBarProps) {
  return (
      <div className="sticky bottom-0 mt-6 -mx-6 px-6 py-3 bg-background/80 backdrop-blur-sm border-t border-border flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs">
          {error && <span className="text-danger">{error}</span>}
          {!error && saving && (
            <>
              <svg
                className="animate-spin w-3 h-3 text-muted-foreground"
                viewBox="0 0 24 24"
                fill="none"
              >
                <circle
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="3"
                  strokeDasharray="40 60"
                />
              </svg>
              <span className="text-muted-foreground">Saving.</span>
            </>
          )}
          {!error && !saving && saved && (
            <span className="text-accent">All changes saved</span>
          )}
          {!error && !saving && !saved && (
            <span className="text-muted-foreground/70">
              Changes save automatically
            </span>
          )}
        </div>
        <Link
          href="/"
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
        >
          Done
        </Link>
      </div>
  );
}
