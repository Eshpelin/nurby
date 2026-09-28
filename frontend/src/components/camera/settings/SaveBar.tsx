// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { translate, type Locale } from "@/lib/i18n";

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
  const { user } = useAuth();
  const locale = (user?.locale as Locale) || "en";
  const t = (key: string) => translate(locale, key);

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
              <span className="text-muted-foreground">{t("camera_settings.saving")}</span>
            </>
          )}
          {!error && !saving && saved && (
            <span className="text-accent">{t("camera_settings.saved")}</span>
          )}
          {!error && !saving && !saved && (
            <span className="text-muted-foreground/70">
              {t("camera_settings.auto_save")}
            </span>
          )}
        </div>
        <Link
          href="/cameras"
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
        >
          {t("camera_settings.back_to_cameras")}
        </Link>
      </div>
  );
}
