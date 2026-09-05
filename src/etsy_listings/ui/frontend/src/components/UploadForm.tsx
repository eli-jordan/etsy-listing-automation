import { useState } from "react";
import { uploadTemplate } from "../api/calibrator";

interface Props {
  onUploaded: (name: string) => void;
}

/**
 * Photos in; the kind question comes afterwards, in the KindPicker.
 *
 * It used to be asked here, which meant answering it before the photos were
 * on screen -- fine when you assembled the set yourself five seconds ago,
 * guesswork for anything else. So the input always takes several files and
 * they keep their own names: which name is *correct* depends on the answer
 * (a colour-matrix set's filenames are its colours, PRD 7a; a scene kind
 * wants the fixed scene.png, PRD 28), and that is not known yet.
 */
export function UploadForm({ onUploaded }: Props) {
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0 || !name) return;
    try {
      await uploadTemplate(name, Array.from(files));
      setStatus("uploaded");
      onUploaded(name);
    } catch {
      setStatus("upload failed");
    }
  }

  return (
    <fieldset className="upload-form">
      <legend>New template</legend>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="flat-lay-02" />
      </label>
      <label>
        Photos
        <input
          type="file"
          accept="image/png"
          multiple
          onChange={(e) => handleFiles(e.target.files)}
        />
      </label>
      <p role="status">{status}</p>
    </fieldset>
  );
}
