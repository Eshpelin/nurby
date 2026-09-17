// Moved verbatim from src/app/cameras/[id]/page.tsx (issue #187).
// State stays in the page; this component renders and reports changes
// through the setters passed as props. Bodies are byte-identical to the
// originals, including their original indentation.

import type { Dispatch, SetStateAction } from "react";
import { Section } from "./primitives";

interface DangerZoneSectionProps {
  deleteConfirm: boolean;
  handleDelete: () => void;
  setDeleteConfirm: Dispatch<SetStateAction<boolean>>;
}

export function DangerZoneSection({
  deleteConfirm,
  handleDelete,
  setDeleteConfirm,
}: DangerZoneSectionProps) {
  return (
        <Section title="Danger Zone">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-foreground">Delete this camera</p>
              <p className="text-xs text-muted-foreground">
                Removes config and stops stream. Recordings remain on disk.
              </p>
            </div>
            {!deleteConfirm ? (
              <button
                onClick={() => setDeleteConfirm(true)}
                className="px-3 py-1.5 text-sm rounded-md border border-danger/30 text-danger hover:bg-danger/10 transition-colors"
              >
                Delete
              </button>
            ) : (
              <div className="flex gap-2">
                <button
                  onClick={() => setDeleteConfirm(false)}
                  className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  className="px-3 py-1.5 text-sm rounded-md bg-danger text-white hover:opacity-90 transition-opacity"
                >
                  Confirm Delete
                </button>
              </div>
            )}
          </div>
        </Section>
  );
}
