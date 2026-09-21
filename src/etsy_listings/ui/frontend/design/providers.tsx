// Mock contexts wrapped around every frame. Scaffolded by marver init from what it detected - yours to edit.
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

export default function Providers({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}
