import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { HealthScreen } from "./HealthScreen";
import { HealthCheckError, type HealthPayload } from "./health/checkHealth";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
};

it("starts in Connecting and makes one health check", async () => {
  const pending = deferred<HealthPayload>();
  const healthCheck = jest.fn().mockReturnValue(pending.promise);

  await render(<HealthScreen healthCheck={healthCheck} />);

  expect(screen.getByText("Connecting")).toBeTruthy();
  expect(healthCheck).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  await screen.unmount();
});

it("connects and allows exactly one new check through Retry", async () => {
  const first = deferred<HealthPayload>();
  const second = deferred<HealthPayload>();
  const healthCheck = jest.fn()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(second.promise);

  await render(<HealthScreen healthCheck={healthCheck} />);
  expect(screen.getByText("Connecting")).toBeTruthy();

  await act(async () => first.resolve({ status: "ok" }));
  expect(screen.getByText("Connected")).toBeTruthy();

  await fireEvent.press(screen.getByRole("button", { name: "Retry" }));
  expect(screen.getByText("Connecting")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  expect(healthCheck).toHaveBeenCalledTimes(2);

  await act(async () => second.resolve({ status: "ok" }));
  expect(screen.getByText("Connected")).toBeTruthy();

  const activeSignal = healthCheck.mock.calls[1][0].signal as AbortSignal;
  await screen.unmount();
  expect(activeSignal.aborted).toBe(true);
});

it("shows a safe timeout failure and recovers through Retry", async () => {
  const first = deferred<HealthPayload>();
  const next = deferred<HealthPayload>();
  const healthCheck = jest.fn()
    .mockReturnValueOnce(first.promise)
    .mockReturnValueOnce(next.promise);

  await render(<HealthScreen healthCheck={healthCheck} />);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

  await act(async () => first.reject(new HealthCheckError("The API check timed out.")));
  expect(screen.getByText("Unavailable")).toBeTruthy();
  expect(screen.getByText("The API check timed out.")).toBeTruthy();
  expect(screen.queryByText("HealthCheckError")).toBeNull();

  await fireEvent.press(screen.getByRole("button", { name: "Retry" }));
  expect(screen.getByText("Connecting")).toBeTruthy();
  expect(healthCheck).toHaveBeenCalledTimes(2);

  await act(async () => next.resolve({ status: "ok" }));
  expect(screen.getByText("Connected")).toBeTruthy();
  await screen.unmount();
});

it("maps an unknown failure to safe unavailable copy", async () => {
  const healthCheck = jest.fn().mockRejectedValue(new Error("private stack details"));

  await render(<HealthScreen healthCheck={healthCheck} />);
  await waitFor(() => expect(screen.getByText("Unavailable")).toBeTruthy());

  expect(screen.getByText("Could not reach the API.")).toBeTruthy();
  expect(screen.queryByText("private stack details")).toBeNull();
  await screen.unmount();
});

it("does not overlap an active attempt", async () => {
  const pending = deferred<HealthPayload>();
  const healthCheck = jest.fn().mockReturnValue(pending.promise);

  const view = await render(<HealthScreen healthCheck={healthCheck} />);
  await view.rerender(<HealthScreen healthCheck={healthCheck} />);

  expect(healthCheck).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Connecting")).toBeTruthy();
  await screen.unmount();
});

it("ignores an old result after replacing the health checker", async () => {
  const old = deferred<HealthPayload>();
  const current = deferred<HealthPayload>();
  const one = jest.fn().mockReturnValue(old.promise);
  const two = jest.fn().mockReturnValue(current.promise);

  const view = await render(<HealthScreen healthCheck={one} />);
  const oldSignal = one.mock.calls[0][0].signal as AbortSignal;
  await view.rerender(<HealthScreen healthCheck={two} />);
  expect(oldSignal.aborted).toBe(true);

  await act(async () => current.resolve({ status: "ok" }));
  await act(async () => old.reject(new Error("stale failure")));
  expect(screen.getByText("Connected")).toBeTruthy();
  expect(screen.queryByText("stale failure")).toBeNull();
  await screen.unmount();
});

it("aborts a pending attempt on unmount and ignores late completion", async () => {
  const pending = deferred<HealthPayload>();
  const healthCheck = jest.fn().mockReturnValue(pending.promise);

  await render(<HealthScreen healthCheck={healthCheck} />);
  const signal = healthCheck.mock.calls[0][0].signal as AbortSignal;
  await screen.unmount();
  expect(signal.aborted).toBe(true);

  await act(async () => pending.resolve({ status: "ok" }));
  expect(healthCheck).toHaveBeenCalledTimes(1);
});
