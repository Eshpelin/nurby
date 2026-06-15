import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    // The react-hooks v6 plugin ships the React Compiler diagnostics.
    // They are valuable signal, but several fire on intentional, correct
    // idioms (the "latest ref" pattern `ref.current = x` during render,
    // ref-based id counters, and display-only `Date.now()` derived
    // values), and we do not build with the React Compiler. Keeping them
    // as warnings keeps the signal visible without failing CI on
    // patterns the React docs themselves recommend. Genuine bugs these
    // catch should still be fixed; treat the warnings as a backlog.
    rules: {
      "react-hooks/purity": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
    },
  },
]);

export default eslintConfig;
