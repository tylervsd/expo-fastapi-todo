export type HealthPayload = { status: "ok" };

export type HealthCheckOptions = {
  apiUrl?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
};

export class HealthCheckError extends Error {}

export function checkHealth(options: HealthCheckOptions = {}): Promise<HealthPayload> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      options.signal?.removeEventListener("abort", cancel);
      if (error) reject(error);
      else resolve({ status: "ok" });
    };

    const cancel = () => {
      const error = new Error("The API check was cancelled.");
      error.name = "AbortError";
      finish(error);
      controller.abort();
    };

    if (options.signal?.aborted) {
      cancel();
      return;
    }
    options.signal?.addEventListener("abort", cancel, { once: true });

    let url: string;
    try {
      const base = options.apiUrl ?? process.env.EXPO_PUBLIC_API_URL;
      if (!base) throw new Error("Missing API URL");
      const parsed = new URL(base);
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("Invalid protocol");
      url = new URL("/health", parsed).toString();
    } catch {
      finish(new HealthCheckError("The API URL is not configured correctly."));
      return;
    }

    timer = setTimeout(() => {
      finish(new HealthCheckError("The API check timed out."));
      controller.abort();
    }, options.timeoutMs ?? 5_000);

    void (async () => {
      try {
        const result = await (options.fetchImpl ?? fetch)(url, {
          method: "GET",
          signal: controller.signal,
        });
        if (settled) return;
        if (result.status !== 200) {
          finish(new HealthCheckError("The API returned an unexpected response."));
          controller.abort();
          return;
        }

        let body: unknown;
        try {
          body = await result.json();
        } catch {
          finish(new HealthCheckError("The API returned invalid data."));
          return;
        }
        if (
          typeof body !== "object" ||
          body === null ||
          Array.isArray(body) ||
          Object.keys(body).length !== 1 ||
          !("status" in body) ||
          body.status !== "ok"
        ) {
          finish(new HealthCheckError("The API returned invalid data."));
          return;
        }
        finish();
      } catch {
        finish(new HealthCheckError("Could not reach the API."));
      }
    })();
  });
}
