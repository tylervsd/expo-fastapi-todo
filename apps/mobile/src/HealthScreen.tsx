import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { checkHealth, HealthCheckError, type HealthPayload } from "./health/checkHealth";

type ScreenState =
  | { kind: "connecting" }
  | { kind: "connected" }
  | { kind: "unavailable"; message: string };

export type HealthCheck = (options: { signal: AbortSignal }) => Promise<HealthPayload>;

export function HealthScreen({ healthCheck = checkHealth }: { healthCheck?: HealthCheck }) {
  const [state, setState] = useState<ScreenState>({ kind: "connecting" });
  const mounted = useRef(false);
  const attempt = useRef(0);
  const active = useRef<AbortController | null>(null);
  const busy = useRef(false);

  const abortActiveAttempt = useCallback(() => {
    active.current?.abort();
  }, []);
  const invalidateAttempt = useCallback(() => {
    ++attempt.current;
  }, []);

  const runCheck = useCallback(async () => {
    if (!mounted.current || busy.current) return;
    busy.current = true;
    const id = ++attempt.current;
    abortActiveAttempt();
    const controller = new AbortController();
    active.current = controller;
    setState({ kind: "connecting" });

    try {
      await healthCheck({ signal: controller.signal });
      if (mounted.current && attempt.current === id && !controller.signal.aborted) {
        setState({ kind: "connected" });
      }
    } catch (error) {
      if (!mounted.current || attempt.current !== id || controller.signal.aborted) return;
      const message = error instanceof HealthCheckError ? error.message : "Could not reach the API.";
      setState({ kind: "unavailable", message });
    } finally {
      if (attempt.current === id) busy.current = false;
    }
  }, [abortActiveAttempt, healthCheck]);

  useEffect(() => {
    mounted.current = true;
    let effectActive = true;
    void Promise.resolve().then(() => {
      if (effectActive) void runCheck();
    });

    return () => {
      effectActive = false;
      mounted.current = false;
      invalidateAttempt();
      abortActiveAttempt();
      busy.current = false;
    };
  }, [abortActiveAttempt, invalidateAttempt, runCheck]);

  return (
    <View style={{ flex: 1, justifyContent: "center", padding: 24, gap: 16 }}>
      <Text accessibilityRole="header">Project Foundation</Text>
      <Text>Check the connection to your local API.</Text>
      <Text accessibilityLiveRegion="polite">
        {state.kind === "connecting" ? "Connecting" : state.kind === "connected" ? "Connected" : "Unavailable"}
      </Text>
      {state.kind === "unavailable" && <Text>{state.message}</Text>}
      {state.kind !== "connecting" && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Retry"
          style={{ minHeight: 44, padding: 12 }}
          onPress={() => void runCheck()}
        >
          <Text>Retry</Text>
        </Pressable>
      )}
    </View>
  );
}
