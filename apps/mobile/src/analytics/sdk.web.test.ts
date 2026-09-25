const mockLoad = jest.fn();
const mockTrack = jest.fn();
const mockIdentify = jest.fn();
const mockReset = jest.fn();

jest.mock("@rudderstack/analytics-js/bundled", () => ({
  RudderAnalytics: jest.fn().mockImplementation(() => ({
    load: mockLoad,
    track: mockTrack,
    identify: mockIdentify,
    reset: mockReset,
  })),
}));

import { createSdk } from "./sdk.web";

beforeEach(() => jest.clearAllMocks());

it("returns null and loads nothing without both settings", () => {
  expect(createSdk({ writeKey: undefined, dataPlaneUrl: "https://dp.example.test" })).toBeNull();
  expect(createSdk({ writeKey: "key", dataPlaneUrl: undefined })).toBeNull();
  expect(createSdk({ writeKey: "", dataPlaneUrl: "https://dp.example.test" })).toBeNull();
  expect(mockLoad).not.toHaveBeenCalled();
});

it("loads cloud mode with localStorage and forwards calls without traits", () => {
  const sdk = createSdk({ writeKey: "key", dataPlaneUrl: "https://dp.example.test" });
  expect(mockLoad).toHaveBeenCalledWith(
    "key",
    "https://dp.example.test",
    expect.objectContaining({ storage: { type: "localStorage" }, loadIntegration: false }),
  );
  sdk!.track("suggestion_requested", { workflow_key: "wf-1" });
  sdk!.identify("u-1");
  sdk!.reset();
  expect(mockTrack).toHaveBeenCalledWith("suggestion_requested", { workflow_key: "wf-1" });
  expect(mockIdentify.mock.calls).toEqual([["u-1"]]);
  expect(mockReset).toHaveBeenCalledWith({ entries: { anonymousId: true } });
});

it("returns null when the SDK fails to load", () => {
  mockLoad.mockImplementationOnce(() => { throw new Error("blocked"); });
  expect(createSdk({ writeKey: "key", dataPlaneUrl: "https://dp.example.test" })).toBeNull();
});
