import { describe, expect, it } from "vitest";
import { duration, label, pct } from "./components";

describe("formatting helpers", () => {
  it("humanises states", () => {
    expect(label("WAITING_FOR_DEVICE")).toBe("Waiting for device");
  });
  it("formats durations", () => {
    expect(duration(null)).toBe("—");
    expect(duration(12.34)).toBe("12.3s");
    expect(duration(600)).toBe("10.0 min");
  });
  it("formats percentages", () => {
    expect(pct(0.9567)).toBe("96%");
    expect(pct(null)).toBe("—");
  });
});
