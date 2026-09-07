import { TodoApiError, type Todo } from "../todos/todoApi";
import { createAuthenticatedApi, type TodoTransport } from "./authenticatedApi";

const row = (id: string): Todo => ({ id, title: "Row", completed: false });

const makeTransport = (): TodoTransport & {
  [K in keyof TodoTransport]: jest.Mock;
} => ({
  listTodos: jest.fn(async () => [row("1")]),
  createTodo: jest.fn(async () => row("2")),
  setTodoTitle: jest.fn(async () => row("1")),
  setTodoCompleted: jest.fn(async () => row("1")),
  deleteTodo: jest.fn(async () => undefined),
});

it("injects the token into every call", async () => {
  const transport = makeTransport();
  const api = createAuthenticatedApi(() => "tok", jest.fn(), transport);

  await api.list({ signal: new AbortController().signal });
  await api.create("Hi");
  await api.rename("1", "New");
  await api.setCompleted("1", true);
  await api.remove("1");

  expect(transport.listTodos).toHaveBeenCalledWith({
    signal: expect.any(AbortSignal),
    token: "tok",
  });
  expect(transport.createTodo).toHaveBeenCalledWith("Hi", { token: "tok" });
  expect(transport.setTodoTitle).toHaveBeenCalledWith("1", "New", { token: "tok" });
  expect(transport.setTodoCompleted).toHaveBeenCalledWith("1", true, { token: "tok" });
  expect(transport.deleteTodo).toHaveBeenCalledWith("1", { token: "tok" });
});

it("signs out and rethrows on auth-required", async () => {
  const transport = makeTransport();
  const failure = new TodoApiError("auth-required", "Please sign in again.");
  transport.listTodos.mockRejectedValueOnce(failure);
  const onAuthRequired = jest.fn();
  const api = createAuthenticatedApi(() => "tok", onAuthRequired, transport);

  await expect(api.list({ signal: new AbortController().signal })).rejects.toBe(failure);
  expect(onAuthRequired).toHaveBeenCalledTimes(1);
});

it("does not sign out for other errors", async () => {
  const transport = makeTransport();
  transport.createTodo.mockRejectedValueOnce(new Error("boom"));
  const onAuthRequired = jest.fn();
  const api = createAuthenticatedApi(() => "tok", onAuthRequired, transport);

  await expect(api.create("Hi")).rejects.toThrow("boom");
  expect(onAuthRequired).not.toHaveBeenCalled();
});

it("sends no token when signed out", async () => {
  const transport = makeTransport();
  const api = createAuthenticatedApi(() => null, jest.fn(), transport);

  await api.create("Hi");

  expect(transport.createTodo).toHaveBeenCalledWith("Hi", {});
});
