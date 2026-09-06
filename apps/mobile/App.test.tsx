jest.mock("./src/todos/todoApi", () => {
  const actual = jest.requireActual<typeof import("./src/todos/todoApi")>("./src/todos/todoApi");
  return {
    ...actual,
    listTodos: jest.fn().mockResolvedValue([]),
    createTodo: jest.fn(),
    setTodoCompleted: jest.fn(),
  };
});

import { render, screen, waitFor } from "@testing-library/react-native";
import { timeoutManager } from "@tanstack/react-query";
import App from "./App";
import { listTodos } from "./src/todos/todoApi";

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

beforeEach(() => {
  mockedListTodos.mockClear();
});

it("opens the server-backed todo experience through Task 2 defaults", async () => {
  await render(<App />);

  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy();
  expect(screen.getByLabelText("Todo title")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
  expect(mockedListTodos).toHaveBeenCalledTimes(1);
  expect(mockedListTodos.mock.calls[0]?.[0]?.signal).toBeInstanceOf(AbortSignal);
});

it("keeps one query client across app rerenders without refetching", async () => {
  const view = await render(<App />);
  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(mockedListTodos).toHaveBeenCalledTimes(1);

  await view.rerender(<App />);
  await view.rerender(<App />);

  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(mockedListTodos).toHaveBeenCalledTimes(1);
});
