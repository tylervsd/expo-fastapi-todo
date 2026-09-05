import { checkHealth, HealthCheckError } from "./checkHealth";

const response = (status: number, body: unknown) =>
  ({ status, json: jest.fn().mockResolvedValue(body) }) as unknown as Response;

it("resolves only the exact healthy payload", async () => {
  const fetchImpl = jest.fn().mockResolvedValue(response(200, { status: "ok" }));

  await expect(checkHealth({ apiUrl: "http://127.0.0.1:8000", fetchImpl })).resolves.toEqual({ status: "ok" });
  expect(fetchImpl).toHaveBeenCalledWith(
    "http://127.0.0.1:8000/health",
    expect.objectContaining({ method: "GET" }),
  );
});

it.each([
  ["network", jest.fn().mockRejectedValue(new TypeError("offline")), "Could not reach the API."],
  ["non-200", jest.fn().mockResolvedValue(response(503, { status: "ok" })), "The API returned an unexpected response."],
  ["invalid JSON", jest.fn().mockResolvedValue({ status: 200, json: jest.fn().mockRejectedValue(new SyntaxError()) }), "The API returned invalid data."],
  ["unexpected body", jest.fn().mockResolvedValue(response(200, { status: "up" })), "The API returned invalid data."],
])("maps %s to safe unavailable copy", async (_case, fetchImpl, message) => {
  await expect(checkHealth({ apiUrl: "http://127.0.0.1:8000", fetchImpl })).rejects.toEqual(new HealthCheckError(message));
});

it("times out body consumption after five seconds and aborts transport", async () => {
  jest.useFakeTimers();
  try {
    const json = jest.fn(() => new Promise<never>(() => undefined));
    const fetchImpl = jest.fn().mockResolvedValue({ status: 200, json } as unknown as Response);
    const pending = checkHealth({ apiUrl: "http://127.0.0.1:8000", fetchImpl });
    const rejection = expect(pending).rejects.toEqual(new HealthCheckError("The API check timed out."));

    await jest.advanceTimersByTimeAsync(5_000);
    await rejection;
    expect((fetchImpl.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
  } finally {
    jest.useRealTimers();
  }
});

it("rejects immediately when the caller cancels even if fetch ignores abort", async () => {
  const controller = new AbortController();
  const fetchImpl = jest.fn(() => new Promise<Response>(() => undefined));
  const pending = checkHealth({ apiUrl: "http://127.0.0.1:8000", signal: controller.signal, fetchImpl });

  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});

it("does not start transport for an already cancelled caller", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchImpl = jest.fn();

  await expect(checkHealth({ signal: controller.signal, fetchImpl })).rejects.toMatchObject({ name: "AbortError" });
  expect(fetchImpl).not.toHaveBeenCalled();
});

it.each(["success", "timeout", "cancel"])("cleans up after %s", async (mode) => {
  jest.useFakeTimers();
  try {
    const controller = new AbortController();
    const removed = jest.spyOn(controller.signal, "removeEventListener");
    const fetchImpl = jest.fn().mockImplementation(() => mode === "success"
      ? Promise.resolve(response(200, { status: "ok" }))
      : new Promise<Response>(() => undefined));
    const result = checkHealth({ apiUrl: "http://127.0.0.1:8000", signal: controller.signal, fetchImpl });
    const assertion = mode === "success" ? expect(result).resolves.toEqual({ status: "ok" })
      : expect(result).rejects.toBeInstanceOf(Error);

    if (mode === "cancel") controller.abort();
    if (mode === "timeout") await jest.advanceTimersByTimeAsync(5_000);
    await assertion;
    expect(jest.getTimerCount()).toBe(0);
    expect(removed).toHaveBeenCalledWith("abort", expect.any(Function));
  } finally {
    jest.useRealTimers();
  }
});
