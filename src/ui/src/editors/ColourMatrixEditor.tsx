import { ColourPicker } from "./ColourPicker";
import { PreparationNotice } from "./PreparationNotice";
import type { ReactNode } from "react";
import type { PhotoWarpTemplate } from "../types";
import { useCallback, useMemo, useState } from "react";
import type { PreviewJob } from "../components/PreviewPanel";
import { usePreview } from "../hooks/usePreview";
import type { ColourMatrixTemplate } from "../types";
import { EditorShell, OneBoxCanvas } from "./EditorShell";

interface Props {
  rendererControls?: ReactNode;
  templateName: string;
  config: PhotoWarpTemplate<ColourMatrixTemplate>;
  colours: string[];
  /** The photo's true pixel size -- the space the box is in. See
   * `QuadEditor`'s `space`. */
  space: [number, number] | null;
  onChange: (config: ColourMatrixTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
  onApprove: () => void;
}

function PhotoWarpColourMatrixEditor(props: Props) {
  const { templateName, config, colours, onChange, design, onApprove } = props;
  const [selectedColour, setSelectedColour] = useState<string | null>(null);
  // Derived rather than synced via effect+setState: falls back to the first
  // colour whenever the selection isn't (or is no longer) one of them --
  // covers both the initial mount and a colour list that changed underneath.
  const colour =
    selectedColour && colours.includes(selectedColour) ? selectedColour : (colours[0] ?? "");

  const previewUrl = usePreview(
    templateName,
    useMemo(
      () =>
        colour
          ? {
              colour,
              bounding_box: config.bounding_box,
              renderer: config.renderer,
            }
          : null,
      [colour, config.bounding_box, config.renderer],
    ),
    design,
  );

  // One full-size render per colour in the set -- the whole point of this kind
  // is that one box has to work in all of them.
  const jobs: PreviewJob[] = useMemo(
    () =>
      colours.map((c) => ({
        id: c,
        label: c,
        body: {
          colour: c,
          bounding_box: config.bounding_box,
          renderer: config.renderer,
        },
      })),
    [colours, config.bounding_box, config.renderer],
  );

  const setBox = useCallback(
    (bounding_box: ColourMatrixTemplate["bounding_box"]) => onChange({ ...config, bounding_box }),
    [config, onChange],
  );

  return (
    <EditorShell
      {...props}
      rendererControls={props.rendererControls || null}
      previewUrl={previewUrl}
      jobs={jobs}
      onApprove={onApprove}
      canvas={(ctx) => <OneBoxCanvas {...ctx} box={config.bounding_box} onChange={setBox} />}
      barExtras={
        /* Which colour the canvas is showing. A row of pills used to sit
           between the tabs and the photo, pushing the thing being calibrated
           down the page and growing with the set -- a twelve-colour garment
           wrapped onto two lines. It is a choice of one from a list, which is
           what a select is for, and it belongs beside the other control that
           says what you are looking at.

           Only when there is a choice to make: a one-colour set has none, and
           the Preview tab renders every colour regardless. */
        colours.length > 1 ? (
          <ColourPicker colour={colour} colours={colours} onChange={setSelectedColour} />
        ) : null
      }
    />
  );
}

export function ColourMatrixEditor(
  props: Omit<Props, "config"> & { config: ColourMatrixTemplate },
) {
  const renderer = props.config.renderer;
  if (renderer.type !== "photo-warp") {
    return <PreparationNotice />;
  }
  return <PhotoWarpColourMatrixEditor {...props} config={{ ...props.config, renderer }} />;
}
