// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section, FieldRow, inputClass } from "./primitives";
import { translate, type Locale } from "@/lib/i18n";

interface AuthSectionProps {
  locale: Locale;
  authToken: string;
  password: string;
  setAuthToken: Dispatch<SetStateAction<string>>;
  setPassword: Dispatch<SetStateAction<string>>;
  setUsername: Dispatch<SetStateAction<string>>;
  username: string;
}

export function AuthSection({
  locale,
  authToken,
  password,
  setAuthToken,
  setPassword,
  setUsername,
  username,
}: AuthSectionProps) {
  const t = (key: string) => translate(locale, key);
  return (
          <Section
            title={t("camera.auth.title")}
          advanced
            description={t("camera.auth.description")}
          >
            <FieldRow label={t("camera.auth.username")}>
              {/* autoComplete off + a non-login field name so the browser
                  does not autofill the account email over the camera's own
                  username. Autofill here silently corrupts the RTSP creds and
                  the camera 401s. */}
              <input
                type="text"
                name="nurby-camera-username"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                className={inputClass}
              />
            </FieldRow>

            <FieldRow label={t("camera.auth.password")} hint={t("camera.auth.password_hint")}>
              {/* new-password stops the browser autofilling a saved login
                  password over the camera credential. */}
              <input
                type="password"
                name="nurby-camera-password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className={inputClass}
              />
            </FieldRow>

            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <span className="flex-1 h-px bg-border" />
              {t("camera.auth.or_token")}
              <span className="flex-1 h-px bg-border" />
            </div>

            <FieldRow label={t("camera.auth.bearer_token")} hint={t("camera.auth.bearer_hint")}>
              <input
                type="password"
                value={authToken}
                onChange={(e) => setAuthToken(e.target.value)}
                placeholder={t("camera.auth.token_placeholder")}
                className={`${inputClass} font-mono text-xs`}
              />
            </FieldRow>
          </Section>
  );
}
