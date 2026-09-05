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
import App from "./App";
import { listTodos } from "./src/todos/todoApi";

const mockedListTodos = listTodos as jest.MockedFunction<typeof listTodos>;

it("opens the server-backed todo experience through Task 2 defaults", async () => {
  await render(<App />);

  await waitFor(() => expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy());
  expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy();
  expect(screen.getByLabelText("Todo title")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
  expect(mockedListTodos).toHaveBeenCalledTimes(1);
  expect(mockedListTodos.mock.calls[0]?.[0]?.signal).toBeInstanceOf(AbortSignal);
});
