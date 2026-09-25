import { fireEvent, render, screen } from "@testing-library/react-native";
import { createAnalytics, createMemoryConsentStore } from "./analytics";
import { AnalyticsConsentSwitch } from "./AnalyticsConsentSwitch";

const sdk = () => ({ track: jest.fn(), identify: jest.fn(), reset: jest.fn() });

it("renders nothing when analytics is unavailable", async () => {
  const analytics = createAnalytics({ sdk: null, consentStore: createMemoryConsentStore(), gpc: () => false });
  await render(<AnalyticsConsentSwitch analytics={analytics} />);
  expect(screen.queryByLabelText("Share usage analytics")).toBeNull();
});

it("defaults on and turns analytics off", async () => {
  const store = createMemoryConsentStore();
  const client = sdk();
  const analytics = createAnalytics({ sdk: client, consentStore: store, gpc: () => false });
  await render(<AnalyticsConsentSwitch analytics={analytics} />);
  const toggle = screen.getByLabelText("Share usage analytics");
  expect(toggle).toHaveProp("value", true);
  await fireEvent(toggle, "valueChange", false);
  expect(store.get()).toBe(false);
  expect(client.reset).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Share usage analytics")).toHaveProp("value", false);
});

it("shows off and disabled under Global Privacy Control", async () => {
  const analytics = createAnalytics({ sdk: sdk(), consentStore: createMemoryConsentStore(true), gpc: () => true });
  await render(<AnalyticsConsentSwitch analytics={analytics} />);
  const toggle = screen.getByLabelText("Share usage analytics");
  expect(toggle).toHaveProp("value", false);
  expect(toggle).toHaveProp("disabled", true);
  expect(screen.getByText("Off: your browser sends Global Privacy Control.")).toBeTruthy();
});
