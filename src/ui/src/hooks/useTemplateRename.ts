import { useState } from "react";
import { renameTemplate, type TemplateRenameResult } from "../api/calibrator";
import type { NameRefusal } from "../components/EditableName";
import type { Settled } from "./writeLoop";

function noteFor(result: TemplateRenameResult): string {
  if (result.unresolved.length > 0) {
    return `Renamed. Check these by hand: ${result.unresolved.join(", ")}`;
  }
  const count = result.updated.length;
  if (count === 0) return "Renamed";
  return `Renamed · ${count} file${count === 1 ? "" : "s"} updated`;
}

export interface TemplateRename {
  commit: (next: string) => Promise<void>;
  busy: boolean;
  refusal: NameRefusal | null;
  /** What the last rename has to tell the seller, while its template is open. */
  note: string | null;
}

/**
 * Renaming the open template. Pending edits are saved first: an autosave that
 * fires after the move would name a template that has gone, so a save that fails
 * refuses the rename and the draft stays open. `onRenamed` selects
 * the new name, which is what closes the name field. An unsaved renderer switch
 * is kept in memory by name and does not follow; the saved template does.
 */
export function useTemplateRename(
  templateName: string | null,
  flush: () => Promise<Settled>,
  onRenamed: (newName: string) => void,
): TemplateRename {
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<NameRefusal | null>(null);
  const [note, setNote] = useState<{ template: string; message: string } | null>(null);

  async function commit(next: string) {
    if (!templateName) return;
    setBusy(true);
    setRefusal(null);
    try {
      const settled = await flush();
      if (!settled.written) {
        setRefusal({ name: next, message: settled.message });
        return;
      }
      const result = await renameTemplate(templateName, next);
      setNote({ template: result.name, message: noteFor(result) });
      onRenamed(result.name);
    } catch (e) {
      setRefusal({ name: next, message: e instanceof Error ? e.message : "Rename failed" });
    } finally {
      setBusy(false);
    }
  }

  return {
    commit,
    busy,
    refusal,
    note: note?.template === templateName ? note.message : null,
  };
}
