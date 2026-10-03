import { useCallback, useMemo } from "react";
import type { PreviewJob } from "../components/PreviewPanel";
import { usePreview } from "../hooks/usePreview";
import type { SingleTemplate } from "../types";
import { EditorShell, OneBoxCanvas } from "./EditorShell";

interface Props {
  templateName: string;
  config: SingleTemplate;
  /** The photo's true pixel size -- the space the box is in. See
   * `QuadEditor`'s `space`. */
  space: [number, number] | null;
  onChange: (config: SingleTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
}

/** The simplest of the three: one box over one photo, nothing to
 * disambiguate. Everything it adds to the shell is the optional garment
 * colour, which exists only so artwork resolution has something to key on. */
export function SingleEditor({
  templateName,
  config,
  space,
  onChange,
  design,
  onDesignChange,
}: Props) {
  const body = useMemo(
    () => ({
      bounding_box: config.bounding_box,
      displace: config.displace,
      shade: config.shade,
    }),
    [config.bounding_box, config.displace, config.shade],
  );

  const previewUrl = usePreview(templateName, body, design);

  // One output, so one job -- but the same on-demand full-size render a
  // colour set gets, because the reason for it (the canvas draws a downscale)
  // has nothing to do with how many photos a kind has.
  const jobs: PreviewJob[] = useMemo(
    () => [{ id: templateName, label: config.colour ?? templateName, body }],
    [templateName, config.colour, body],
  );

  const setBox = useCallback(
    (bounding_box: SingleTemplate["bounding_box"]) => onChange({ ...config, bounding_box }),
    [config, onChange],
  );

  return (
    <EditorShell
      templateName={templateName}
      config={config}
      onChange={onChange}
      design={design}
      onDesignChange={onDesignChange}
      space={space}
      previewUrl={previewUrl}
      jobs={jobs}
      canvas={(ctx) => <OneBoxCanvas {...ctx} box={config.bounding_box} onChange={setBox} />}
      controls={
        <label>
          Garment colour (optional)
          <input
            value={config.colour ?? ""}
            onChange={(e) => onChange({ ...config, colour: e.target.value || null })}
            placeholder="for artwork resolution, if relevant"
          />
        </label>
      }
    />
  );
}
