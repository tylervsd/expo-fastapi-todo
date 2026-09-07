import * as mockReact from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { createAppQueryClient } from "../../App";
import { TodoApiError, type AuthUser } from "../todos/todoApi";
import { AuthProvider } from "./AuthProvider";
import { createMemoryTokenStorage, type TokenStorage } from "./tokenStorage";
import type { TodoTransport } from "./authenticatedApi";

// TanStack Query schedules minute-scale GC timeouts that can outlive component
// unmounts under jsdom and hold Jest's event loop open after the run. Unref
// them so they still fire while the loop is otherwise alive but never block
// suite exit. Production cache behavior is unchanged.
timeoutManager.setTimeoutProvider({
  setTimeout: (callback, delay) => {
    const id = setTimeout(callback, delay);
    (id as unknown as { unref?: () => void }).unref?.();
    return id as unknown as number;
  },
  clearTimeout: (timeoutId) => clearTimeout(timeoutId as unknown as ReturnType<typeof setTimeout>),
  setInterval: (callback, delay) => {
    const id = setInterval(callback, delay);
    (id as unknown as { unref?: () => void }).unref?.();
    return id as unknown as number;
  },
  clearInterval: (intervalId) =>
    clearInterval(intervalId as unknown as ReturnType<typeof setInterval>),
});

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const TestPressable = (props: Record<string, unknown>) =>
    mockReact.createElement("View", {
      ...props,
      accessible: true,
      accessibilityState:
        props.disabled === undefined
          ? props.accessibilityState
          : { ...(props.accessibilityState as Record<string, unknown>), disabled: props.disabled },
    });
  TestPressable.displayName = "TestPressable";
  return new Proxy(actual, {
    get(target, property, receiver) {
      if (property === "Pressable") return TestPressable;
      return Reflect.get(target, property, receiver);
    },
  });
});

jest.mock("expo-secure-store", () => {
  const store = new Map<string, string>();
  return {
    getItemAsync: jest.fn(async (key: string) => store.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => {
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
      store.delete(key);
    }),
  };
});

const liveClients: QueryClient[] = [];

const alice: AuthUser = { id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72", username: "alice" };

const makeAuthApi = () => ({
  signup: jest.fn(async () => alice),
  login: jest.fn(async () => ({ token: "tok-1", expires_at: "2026-10-07T00:00:00+00:00", user: alice })),
  logout: jest.fn(async () => undefined),
  fetchMe: jest.fn(async () => alice),
});

const makeTransport = (): TodoTransport & {
  [K in keyof TodoTransport]: jest.Mock;
} => ({
  listTodos: jest.fn(async () => []),
  createTodo: jest.fn(async () => ({ id: "1", title: "Hi", completed: false })),
  setTodoTitle: jest.fn(async () => ({ id: "1", title: "Hi", completed: false })),
  setTodoCompleted: jest.fn(async () => ({ id: "1", title: "Hi", completed: false })),
  deleteTodo: jest.fn(async () => undefined),
});

const renderProvider = async (options?: {
  authApi?: ReturnType<typeof makeAuthApi>;
  storage?: TokenStorage;
  transport?: TodoTransport;
  client?: QueryClient;
}) => {
  const authApi = options?.authApi ?? makeAuthApi();
  const storage = options?.storage ?? createMemoryTokenStorage();
  const transport = options?.transport ?? makeTransport();
  const client = options?.client ?? createAppQueryClient();
  liveClients.push(client);
  const view = await render(
    <QueryClientProvider client={client}>
      <AuthProvider authApi={authApi} storage={storage} transport={transport} />
    </QueryClientProvider>
  );
  return { view, authApi, storage, transport, client };
};

afterEach(() => {
  while (liveClients.length > 0) {
    const client = liveClients.pop() as QueryClient;
    client.unmount();
    client.clear();
  }
});

it("shows loading while the session state is unknown", async () => {
  const storage = createMemoryTokenStorage();
  const getSpy = jest.spyOn(storage, "get").mockImplementation(
    () => new Promise<null>(() => undefined)
  );
  await renderProvider({ storage });

  expect(screen.getByText("Loading…")).toBeTruthy();
  expect(screen.queryByRole("header", { name: "Sign in" })).toBeNull();
  getSpy.mockRestore();
});

it("shows the sign-in form with no stored token and no probe request", async () => {
  const authApi = makeAuthApi();
  await renderProvider({ authApi });

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  expect(authApi.fetchMe).not.toHaveBeenCalled();
});

it("shows sign-in when token storage restore rejects", async () => {
  const storage = createMemoryTokenStorage();
  jest.spyOn(storage, "get").mockRejectedValueOnce(new Error("storage unavailable"));

  await renderProvider({ storage });

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
});

it("restores a stored session and shows the user with sign-out", async () => {
  const authApi = makeAuthApi();
  const storage = createMemoryTokenStorage();
  await storage.set("tok-1");
  await renderProvider({ authApi, storage });

  await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
  expect(authApi.fetchMe).toHaveBeenCalledWith({ token: "tok-1" });
  expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
});

it("clears a revoked token and falls back to sign-in", async () => {
  const authApi = makeAuthApi();
  authApi.fetchMe.mockRejectedValueOnce(
    new TodoApiError("auth-required", "Please sign in again.")
  );
  const storage = createMemoryTokenStorage();
  await storage.set("tok-1");
  await renderProvider({ authApi, storage });

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  expect(await storage.get()).toBeNull();
});

it("falls back to sign-in when clearing a revoked token rejects", async () => {
  const authApi = makeAuthApi();
  authApi.fetchMe.mockRejectedValueOnce(
    new TodoApiError("auth-required", "Please sign in again."),
  );
  const storage = createMemoryTokenStorage();
  await storage.set("tok-1");
  jest.spyOn(storage, "clear").mockRejectedValueOnce(new Error("storage unavailable"));

  await renderProvider({ authApi, storage });

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
});

it("signs out through logout, store, and cache", async () => {
  const authApi = makeAuthApi();
  const storage = createMemoryTokenStorage();
  await storage.set("tok-1");
  const client = createAppQueryClient();
  client.setQueryData(["todos"], [{ id: "1", title: "Hi", completed: false }]);
  await renderProvider({ authApi, storage, client });

  await waitFor(() => expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy());
  await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  expect(authApi.logout).toHaveBeenCalledWith({ token: "tok-1" });
  expect(await storage.get()).toBeNull();
  expect(client.getQueryData(["todos"])).toBeUndefined();
});

it("signs out and clears query data when token storage clear rejects", async () => {
  const authApi = makeAuthApi();
  const storage = createMemoryTokenStorage();
  await storage.set("tok-1");
  jest.spyOn(storage, "clear").mockRejectedValue(new Error("storage unavailable"));
  const client = createAppQueryClient();
  client.setQueryData(["todos"], [{ id: "1", title: "Hi", completed: false }]);
  await renderProvider({ authApi, storage, client });

  await waitFor(() => expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy());
  await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  expect(client.getQueryData(["todos"])).toBeUndefined();
});

it("drops to signed-out when a todo request reports auth-required", async () => {
  const authApi = makeAuthApi();
  const storage = createMemoryTokenStorage();
  await storage.set("tok-1");
  const transport = makeTransport();
  transport.listTodos.mockRejectedValueOnce(
    new TodoApiError("auth-required", "Please sign in again.")
  );
  await renderProvider({ authApi, storage, transport });

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  expect(await storage.get()).toBeNull();
});

it("completes sign-in from the form and stores the session", async () => {
  const authApi = makeAuthApi();
  const storage = createMemoryTokenStorage();
  await renderProvider({ authApi, storage });

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
  await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
  await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));

  await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
  expect(await storage.get()).toBe("tok-1");
  expect(authApi.login).toHaveBeenCalledWith("alice", "long-enough-password");
});
