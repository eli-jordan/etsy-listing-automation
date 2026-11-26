import { ColourPicker } from "./ColourPicker";
import { PreparationNotice } from "./PreparationNotice";
import type { ReactNode } from "react";
import type { PhotoSpace, PhotoWarpTemplate } from "../types";
import { useCallback, useMemo, useState } from "react";
import type { PreviewJob } from "../components/PreviewPanel";
import { usePreview } from "../hooks/usePreview";
import type { ColourMatrixTemplate } from "../types";
import { EditorShell, OneBoxCanvas } from "./EditorShell";
import { pickOrFirst, previewJobs } from "./marigoldEditorModel";

interface Props {
  rendererControls?: ReactNode;
  templateName: string;
  config: PhotoWarpTemplate<ColourMatrixTemplate>;
  colours: string[];
  space: PhotoSpace | null;
  onChange: (config: ColourMatrixTemplate) => void;
  design: string;
  onDesignChange: (design: string) => void;
  onApprove: () => void;
}

function PhotoWarpColourMatrixEditor(props: Props) {
  const { templateName, config, colours, onChange, design, onApprove } = props;
  const [selectedColour, setSelectedColour] = useState<string | null>(null);
  const colour = pickOrFirst(selectedColour, colours);

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

  const jobs: PreviewJob[] = useMemo(
    () => previewJobs(config, colours, templateName),
    [config, colours, templateName],
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
      barExtras={<ColourPicker colour={colour} colours={colours} onChange={setSelectedColour} />}
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
