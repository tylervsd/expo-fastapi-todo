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

// eslint-disable-next-line import/first
import { createSdk } from "./sdk.web";

const config = { writeKey: "key", dataPlaneUrl: "https://dp.example.test" };

beforeEach(() => jest.clearAllMocks());

it("returns null and loads nothing without both settings", () => {
  expect(createSdk({ writeKey: undefined, dataPlaneUrl: "https://dp.example.test" })).toBeNull();
  expect(createSdk({ writeKey: "key", dataPlaneUrl: undefined })).toBeNull();
  expect(createSdk({ writeKey: "", dataPlaneUrl: "https://dp.example.test" })).toBeNull();
  expect(mockLoad).not.toHaveBeenCalled();
});

it("does not load (no RudderStack contact) at creation", () => {
  expect(createSdk(config)).not.toBeNull();
  expect(mockLoad).not.toHaveBeenCalled();
});

it("loads cloud mode with localStorage once on the first track, then tracks", () => {
  const sdk = createSdk(config)!;
  sdk.track("suggestion_requested", { workflow_key: "wf-1" });
  expect(mockLoad.mock.calls).toEqual([
    ["key", "https://dp.example.test", expect.objectContaining({ storage: { type: "localStorage" }, loadIntegration: false })],
  ]);
  expect(mockLoad.mock.invocationCallOrder[0]).toBeLessThan(mockTrack.mock.invocationCallOrder[0]);
  expect(mockTrack).toHaveBeenCalledWith("suggestion_requested", { workflow_key: "wf-1" });
  sdk.track("signin_submitted", {});
  expect(mockLoad).toHaveBeenCalledTimes(1);
});

it("loads once on the first identify and forwards the id without traits", () => {
  const sdk = createSdk(config)!;
  sdk.identify("u-1");
  sdk.identify("u-2");
  expect(mockLoad).toHaveBeenCalledTimes(1);
  expect(mockIdentify.mock.calls).toEqual([["u-1"], ["u-2"]]);
});

it("reset before any load loads, then clears the persisted identity", () => {
  const sdk = createSdk(config)!;
  sdk.reset();
  expect(mockLoad).toHaveBeenCalledTimes(1);
  expect(mockLoad.mock.invocationCallOrder[0]).toBeLessThan(mockReset.mock.invocationCallOrder[0]);
  expect(mockReset).toHaveBeenCalledWith({ entries: { anonymousId: true } });
});

it("never throws when the SDK fails to load, and later calls are no-ops", () => {
  mockLoad.mockImplementationOnce(() => {
    throw new Error("blocked");
  });
  const sdk = createSdk(config)!;
  expect(() => sdk.track("signin_submitted", {})).not.toThrow();
  expect(() => sdk.identify("u-1")).not.toThrow();
  expect(() => sdk.reset()).not.toThrow();
  expect(mockLoad).toHaveBeenCalledTimes(1);
  expect(mockTrack).not.toHaveBeenCalled();
  expect(mockIdentify).not.toHaveBeenCalled();
  expect(mockReset).not.toHaveBeenCalled();
});
