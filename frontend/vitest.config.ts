import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Web tests. The app is the largest client and had none: CI only ran
 * `npm run build`, which catches a syntax error and nothing else.
 *
 * Scope on purpose: pure logic and small components. Full-page tests on
 * 3,000-line pages would be slow and brittle; the value is in the
 * functions that decide what a person sees.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
});
