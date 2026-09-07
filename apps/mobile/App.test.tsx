jest.mock("./src/todos/todoApi", () => {
  const actual = jest.requireActual<typeof import("./src/todos/todoApi")>("./src/todos/todoApi");
  return {
    ...actual,
    listTodos: jest.fn().mockResolvedValue([]),
    createTodo: jest.fn(),
    setTodoCompleted: jest.fn(),
    signup: jest.fn(),
    login: jest.fn(),
    logout: jest.fn(),
    fetchMe: jest.fn(),
  };
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

import { render, screen, waitFor } from "@testing-library/react-native";
import { timeoutManager } from "@tanstack/react-query";
import App from "./App";
import { fetchMe, listTodos } from "./src/todos/todoApi";

// See src/TodoScreen.test.tsx: keep TanStack GC timeouts from holding Jest open.
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
  clearInterval: (intervalId) => clearInterval(intervalId as unknown as ReturnType<typeof setInterval>),
});

const mockedListTodos = listTodos as jest.MockedFunction<typeof listTodos>;
const mockedFetchMe = fetchMe as jest.MockedFunction<typeof fetchMe>;

const secureStore = () =>
  jest.requireMock("expo-secure-store") as {
    setItemAsync: jest.Mock;
    deleteItemAsync: jest.Mock;
  };

beforeEach(async () => {
  mockedListTodos.mockClear();
  mockedFetchMe.mockClear();
  await secureStore().deleteItemAsync("todo.session-token");
});

it("shows the sign-in form with no stored session and no probe request", async () => {
  await render(<App />);

  await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
  expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy();
  expect(mockedFetchMe).not.toHaveBeenCalled();
  expect(mockedListTodos).not.toHaveBeenCalled();
});

it("restores a stored session into the todo experience", async () => {
  await secureStore().setItemAsync("todo.session-token", "tok");
  mockedFetchMe.mockResolvedValue({
    id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72",
    username: "alice",
  });

  await render(<App />);

  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(screen.getByText("Signed in as alice")).toBeTruthy();
  expect(mockedFetchMe).toHaveBeenCalledWith({ token: "tok" });
  expect(mockedListTodos).toHaveBeenCalledTimes(1);
  expect(mockedListTodos.mock.calls[0]?.[0]?.signal).toBeInstanceOf(AbortSignal);
});

it("keeps one query client across app rerenders without refetching", async () => {
  await secureStore().setItemAsync("todo.session-token", "tok");
  mockedFetchMe.mockResolvedValue({
    id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72",
    username: "alice",
  });

  const view = await render(<App />);
  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(mockedListTodos).toHaveBeenCalledTimes(1);

  await view.rerender(<App />);
  await view.rerender(<App />);

  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(mockedListTodos).toHaveBeenCalledTimes(1);
});
