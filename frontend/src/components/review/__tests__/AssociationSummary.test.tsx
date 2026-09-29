import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { AssociationSummary } from "../AssociationSummary";

const authFetch = vi.fn();

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    authFetch,
    token: "token",
    user: { locale: "es" },
  }),
}));

describe("AssociationSummary", () => {
  it("uses cautious localized wording for a learned vehicle pattern", async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.startsWith("/api/review/associations?")) {
        return Promise.resolve(new Response(JSON.stringify([{
          id: "association-1",
          subject_kind: "person",
          subject_key: "person-1",
          object_kind: "vehicle",
          object_key: "vehicle-1",
          object_label: "ABCDXYZ",
          relation: "arrives_with",
          status: "candidate",
          user_confirmed: false,
          evidence_count: 3,
          supporting_evidence_count: 3,
          contradictory_evidence_count: 0,
          distinct_days: 3,
          counterpart_label: "ABCDXYZ",
          evidence_url: "/api/review/relationship-suggestions/association-1",
        }])));
      }
      return Promise.resolve(new Response(JSON.stringify({ evidence: [] })));
    });

    render(<AssociationSummary subjectKind="person" subjectKey="person-1" />);

    expect(await screen.findByText("Patrones observados")).toBeInTheDocument();
    expect(screen.getByText(/suele llegar con/)).toBeInTheDocument();
    expect(screen.getByText("patrón sugerido")).toBeInTheDocument();
    expect(screen.getByText(/3 visitas independientes/)).toBeInTheDocument();
  });
});
