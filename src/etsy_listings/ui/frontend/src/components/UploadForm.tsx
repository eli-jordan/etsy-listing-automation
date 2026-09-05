import { useRef, useState } from "react";
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
  // The file input's handler closes over whatever `name` was when React last
  // rendered it. Type a name and choose files quickly enough -- which any
  // automation does, and an impatient person can -- and the handler still saw
  // the empty string, so the upload silently never happened. The ref is
  // written synchronously, so it is always current by the time files arrive.
  const nameRef = useRef("");

  async function handleFiles(files: FileList | null) {
    const current = nameRef.current.trim();
    if (!files || files.length === 0) return;
    if (!current) {
      setStatus("name the template first");
      return;
    }
    try {
      await uploadTemplate(current, Array.from(files));
      setStatus("uploaded");
      onUploaded(current);
    } catch {
      setStatus("upload failed");
    }
  }

  return (
    <fieldset className="upload-form">
      <legend>New template</legend>
      <label>
        Name
        <input
          value={name}
          onChange={(e) => {
            nameRef.current = e.target.value;
            setName(e.target.value);
          }}
          placeholder="flat-lay-02"
        />
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
