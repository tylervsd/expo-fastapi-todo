import * as mockReact from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { createAppQueryClient } from "../../App";
import { TodoApiError, type AuthUser, type Todo } from "../todos/todoApi";
import { AuthProvider, SessionEpochContext } from "./AuthProvider";
import { PENDING_WRITE_KEY_PREFIX } from "../todoWorkflows/pendingWorkflowWrite";
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
      if (property === "findNodeHandle") return () => 123;
      if (property === "AccessibilityInfo") {
        return {
          ...actual.AccessibilityInfo,
          announceForAccessibility: () => undefined,
          setAccessibilityFocus: () => undefined,
        };
      }
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
  setTodoCompleted: jest.fn(
    async () => ({ id: "1", title: "Hi", completed: false })
  ),
  deleteTodo: jest.fn(async () => undefined),
  startTodoWorkflow: jest.fn(),
  getTodoWorkflow: jest.fn(),
  advanceTodoWorkflow: jest.fn(),
  listTodoWorkflows: jest.fn(),
});

const renderProvider = async (options?: {
  authApi?: ReturnType<typeof makeAuthApi>;
  storage?: TokenStorage;
  transport?: TodoTransport;
  client?: QueryClient;
  children?: mockReact.ReactNode;
}) => {
  const authApi = options?.authApi ?? makeAuthApi();
  const storage = options?.storage ?? createMemoryTokenStorage();
  const transport = options?.transport ?? makeTransport();
  const client = options?.client ?? createAppQueryClient();
  liveClients.push(client);
  const view = await render(
    <QueryClientProvider client={client}>
      <AuthProvider authApi={authApi} storage={storage} transport={transport}>
        {options?.children}
      </AuthProvider>
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

describe("session identity", () => {
  const sessionA = {
    token: "tok-A",
    expires_at: "2026-10-07T00:00:00+00:00",
    user: { id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72", username: "alice" },
  };
  const sessionB = {
    token: "tok-B",
    expires_at: "2026-10-07T00:00:00+00:00",
    user: { id: "9ab4d5e6-16a8-4d8e-ae94-fc50bb457d72", username: "bob" },
  };
  const deferred = <T,>() => {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((onResolve, onReject) => {
      resolve = onResolve;
      reject = onReject;
    });
    return { promise, resolve, reject };
  };

  const signInThroughForm = async (username: string, password: string) => {
    await fireEvent.changeText(screen.getByLabelText("Username"), username);
    await fireEvent.changeText(screen.getByLabelText("Password"), password);
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  };

  it("lets the latest login win when storage completions overlap", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA).mockResolvedValueOnce(sessionB);
    const storage = createMemoryTokenStorage();
    const realSet = storage.set.bind(storage);
    const pendingSets: (() => void)[] = [];
    jest.spyOn(storage, "set").mockImplementation(
      (token: string) =>
        new Promise<void>((done) => {
          pendingSets.push(() => {
            void realSet(token).then(() => done());
          });
        }),
    );
    const client = createAppQueryClient();
    const seededTodos = [{ id: "1", title: "Row", completed: false }];
    client.setQueryData(["todos"], seededTodos);
    await renderProvider({ authApi, storage, client });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await signInThroughForm("bob", "long-enough-password");
    expect(authApi.login).toHaveBeenCalledTimes(2);
    // Completions serialize: the second login waits for the first
    // persistence instead of racing it.
    expect(pendingSets).toHaveLength(1);
    await act(async () => {
      pendingSets[0]();
    });
    await act(async () => {});
    // The stale completion finished persisting but must not clear the
    // cache or install its identity once superseded.
    expect(client.getQueryData(["todos"])).toEqual(seededTodos);
    expect(pendingSets).toHaveLength(2);
    await act(async () => {
      pendingSets[1]();
    });
    await act(async () => {});
    expect(screen.getByText("Signed in as bob")).toBeTruthy();
    expect(await storage.get()).toBe("tok-B");
  });

  it("ignores a stale-token 401 after signing in as someone else", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA).mockResolvedValueOnce(sessionB);
    const storage = createMemoryTokenStorage();
    const transport = makeTransport();
    const pendingList = deferred<Todo[]>();
    transport.listTodos
      .mockReturnValueOnce(pendingList.promise)
      .mockResolvedValue([]);
    await renderProvider({ authApi, storage, transport });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());

    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("bob", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as bob")).toBeTruthy());

    await act(async () => {
      pendingList.reject(new TodoApiError("auth-required", "Please sign in again."));
    });

    expect(screen.getByText("Signed in as bob")).toBeTruthy();
    expect(await storage.get()).toBe("tok-B");
    expect(authApi.logout).toHaveBeenCalledTimes(1);
    expect(authApi.logout).toHaveBeenCalledWith({ token: "tok-A" });
  });

  it("signs out on a current-token todo 401", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA);
    const storage = createMemoryTokenStorage();
    await storage.set("tok-A");
    const transport = makeTransport();
    transport.listTodos.mockResolvedValue([
      { id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72", title: "Row", completed: false },
    ]);
    const pendingUpdate = deferred<Todo>();
    transport.setTodoCompleted.mockReturnValueOnce(pendingUpdate.promise);
    await renderProvider({ authApi, storage, transport });

    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Row" })).toBeTruthy()
    );
    await fireEvent.press(screen.getByRole("checkbox", { name: "Row" }));
    await act(async () => {
      pendingUpdate.reject(new TodoApiError("auth-required", "Please sign in again."));
    });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(await storage.get()).toBeNull();
    expect(authApi.logout).toHaveBeenCalledWith({ token: "tok-A" });
  });

  it("withholds sign-in until a deferred sign-out cleanup finishes", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA);
    const storage = createMemoryTokenStorage();
    await storage.set("tok-A");
    const pendingLogout = deferred<void>();
    authApi.logout.mockReturnValueOnce(pendingLogout.promise as Promise<undefined>);
    await renderProvider({ authApi, storage });

    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));

    expect(screen.queryByLabelText("Username")).toBeNull();
    expect(await storage.get()).toBe("tok-A");
    await act(async () => {
      pendingLogout.resolve(undefined);
    });
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(await storage.get()).toBeNull();
  });
});

describe("workflow shell integration", () => {
  const WORKFLOW_ID = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
  const deferred = <T,>() => {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((onResolve, onReject) => {
      resolve = onResolve;
      reject = onReject;
    });
    return { promise, resolve, reject };
  };
  const assessWorkflow = {
    workflow_id: WORKFLOW_ID,
    revision: 0,
    definition_version: 1,
    view_contract_version: 1,
    state: "ASSESS_TASK",
    title: "Plan birthday party",
    context: { involves_multiple_steps: null, proposed_todo_titles: [] },
    result: null,
    view: {
      type: "yes_no",
      step_id: `${WORKFLOW_ID}:ASSESS_TASK`,
      title: "Plan birthday party",
      question: "Does this task involve multiple steps?",
      actions: [
        { id: "yes", label: "Yes" },
        { id: "no", label: "No" },
      ],
    },
  };
  const sessionA = {
    token: "tok-A",
    expires_at: "2026-10-07T00:00:00+00:00",
    user: { id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72", username: "alice" },
  };
  const sessionB = {
    token: "tok-B",
    expires_at: "2026-10-07T00:00:00+00:00",
    user: { id: "9ab4d5e6-16a8-4d8e-ae94-fc50bb457d72", username: "bob" },
  };

  const signInThroughForm = async (username: string, password: string) => {
    await fireEvent.changeText(screen.getByLabelText("Username"), username);
    await fireEvent.changeText(screen.getByLabelText("Password"), password);
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  };

  it("keys workflows by public user ID and sends the current token", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA);
    const storage = createMemoryTokenStorage();
    const transport = makeTransport();
    transport.startTodoWorkflow.mockResolvedValueOnce(assessWorkflow);
    const { client } = await renderProvider({ authApi, storage, transport });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
    await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
    await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

    await waitFor(() =>
      expect(transport.startTodoWorkflow).toHaveBeenCalledWith("Plan birthday party", {
        token: "tok-A",
      })
    );
    await waitFor(() =>
      expect(
        client.getQueryData(["todo-workflow", sessionA.user.id, WORKFLOW_ID])
      ).toEqual(assessWorkflow)
    );
  });

  it("ignores a stale workflow 401 after switching users", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA).mockResolvedValueOnce(sessionB);
    const storage = createMemoryTokenStorage();
    const transport = makeTransport();
    const pendingStart = deferred<typeof assessWorkflow>();
    transport.startTodoWorkflow.mockReturnValueOnce(pendingStart.promise);
    await renderProvider({ authApi, storage, transport });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
    await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
    await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("bob", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as bob")).toBeTruthy());

    await act(async () => {
      pendingStart.reject(new TodoApiError("auth-required", "Please sign in again."));
    });

    expect(screen.getByText("Signed in as bob")).toBeTruthy();
    expect(await storage.get()).toBe("tok-B");
    expect(authApi.logout).toHaveBeenCalledTimes(1);
  });

  it("signs out on a current-token workflow 401", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA);
    const storage = createMemoryTokenStorage();
    const transport = makeTransport();
    const pendingStart = deferred<typeof assessWorkflow>();
    transport.startTodoWorkflow.mockReturnValueOnce(pendingStart.promise);
    await renderProvider({ authApi, storage, transport });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
    await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
    await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
    await act(async () => {
      pendingStart.reject(new TodoApiError("auth-required", "Please sign in again."));
    });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(await storage.get()).toBeNull();
    expect(authApi.logout).toHaveBeenCalledWith({ token: "tok-A" });
  });
});

describe("session epoch", () => {
  const sessionA = {
    token: "tok-A",
    expires_at: "2026-10-07T00:00:00+00:00",
    user: { id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72", username: "alice" },
  };

  const signInThroughForm = async (username: string, password: string) => {
    await fireEvent.changeText(screen.getByLabelText("Username"), username);
    await fireEvent.changeText(screen.getByLabelText("Password"), password);
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
  };

  const renderWithProbe = async (options?: {
    authApi?: ReturnType<typeof makeAuthApi>;
    storage?: TokenStorage;
    transport?: TodoTransport;
  }) => {
    const seen: { epoch: number; current: (epoch: number) => boolean }[] = [];
    const Probe = () => {
      const value = mockReact.useContext(SessionEpochContext);
      seen.push({ epoch: value.sessionEpoch, current: value.isSessionCurrent });
      return null;
    };
    const rendered = await renderProvider({ ...options, children: <Probe /> });
    return { ...rendered, seen };
  };

  const latest = (seen: { epoch: number; current: (epoch: number) => boolean }[]) =>
    seen[seen.length - 1];

  it("bumps the epoch when a stored session is restored", async () => {
    const authApi = makeAuthApi();
    const storage = createMemoryTokenStorage();
    await storage.set("tok-1");
    const { seen } = await renderWithProbe({ authApi, storage });

    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    expect(latest(seen).epoch).toBe(1);
    expect(latest(seen).current(1)).toBe(true);
    expect(latest(seen).current(0)).toBe(false);
  });

  it("bumps the epoch when restore finds no session", async () => {
    const { seen } = await renderWithProbe();

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(latest(seen).epoch).toBe(1);
    expect(latest(seen).current(1)).toBe(true);
  });

  it("bumps the epoch on login, sign-out, and same-user re-login", async () => {
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValue(sessionA);
    const { seen } = await renderWithProbe({ authApi });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(latest(seen).epoch).toBe(1);

    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    expect(latest(seen).epoch).toBe(2);
    expect(latest(seen).current(1)).toBe(false);

    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(latest(seen).epoch).toBe(3);

    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    expect(latest(seen).epoch).toBe(4);
    expect(latest(seen).current(3)).toBe(false);
    expect(latest(seen).current(4)).toBe(true);
  });

  it("does not bump the epoch for a superseded stale-token cleanup", async () => {
    const authApi = makeAuthApi();
    authApi.login
      .mockResolvedValueOnce(sessionA)
      .mockResolvedValueOnce({
        token: "tok-B",
        expires_at: "2026-10-07T00:00:00+00:00",
        user: { id: "9ab4d5e6-16a8-4d8e-ae94-fc50bb457d72", username: "bob" },
      });
    const storage = createMemoryTokenStorage();
    const transport = makeTransport();
    const pendingList: { promise: Promise<Todo[]>; resolve: (value: Todo[]) => void; reject: (reason?: unknown) => void } = (() => {
      let resolve!: (value: Todo[]) => void;
      let reject!: (reason?: unknown) => void;
      const promise = new Promise<Todo[]>((onResolve, onReject) => {
        resolve = onResolve;
        reject = onReject;
      });
      return { promise, resolve, reject };
    })();
    transport.listTodos.mockReturnValueOnce(pendingList.promise).mockResolvedValue([]);
    const { seen } = await renderWithProbe({ authApi, storage, transport });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());

    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("bob", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as bob")).toBeTruthy());
    const epochAfterSwitch = latest(seen).epoch;

    await act(async () => {
      pendingList.reject(new TodoApiError("auth-required", "Please sign in again."));
    });

    expect(screen.getByText("Signed in as bob")).toBeTruthy();
    expect(latest(seen).epoch).toBe(epochAfterSwitch);
    expect(latest(seen).current(epochAfterSwitch)).toBe(true);
  });

  it("never writes pending-workflow keys during auth flows", async () => {
    const SecureStore = jest.requireMock("expo-secure-store") as {
      setItemAsync: jest.Mock;
      deleteItemAsync: jest.Mock;
    };
    SecureStore.setItemAsync.mockClear();
    SecureStore.deleteItemAsync.mockClear();
    const authApi = makeAuthApi();
    authApi.login.mockResolvedValueOnce(sessionA);
    const { storage } = await renderProvider({ authApi, storage: createMemoryTokenStorage() });

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await signInThroughForm("alice", "long-enough-password");
    await waitFor(() => expect(screen.getByText("Signed in as alice")).toBeTruthy());
    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    void storage;

    for (const call of SecureStore.setItemAsync.mock.calls) {
      expect(String(call[0])).not.toContain(PENDING_WRITE_KEY_PREFIX);
    }
    for (const call of SecureStore.deleteItemAsync.mock.calls) {
      expect(String(call[0])).not.toContain(PENDING_WRITE_KEY_PREFIX);
    }
  });
});
