import { cleanup, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";

const unmounted = vi.fn();

afterEach(() => {
  try {
    expect(unmounted).toHaveBeenCalledOnce();
  } finally {
    cleanup();
    unmounted.mockClear();
  }
});

it("unmounts React trees before test files restore their API mocks", () => {
  function Component() {
    useEffect(() => () => unmounted(), []);
    return <p>Mounted</p>;
  }

  render(<Component />);
  expect(unmounted).not.toHaveBeenCalled();
});
