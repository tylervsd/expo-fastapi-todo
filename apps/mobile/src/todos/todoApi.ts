export type Todo = {
  id: string;
  title: string;
  completed: boolean;
};

export type TodoApiErrorKind = "validation" | "not-found" | "unavailable" | "invalid-data";

export class TodoApiError extends Error {
  constructor(
    readonly kind: TodoApiErrorKind,
    message: string,
  ) {
    super(message);
    this.name = "TodoApiError";
  }
}

export type TodoRequestOptions = {
  apiUrl?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
};

type TodoOperation = "list" | "create" | "update" | "delete";
type RequestBody = { title: string } | { completed: boolean };

const operationMessages: Record<TodoOperation, { unavailable: string; invalidData: string }> = {
  list: {
    unavailable: "Could not load todos.",
    invalidData: "The API returned invalid todo data while loading.",
  },
  create: {
    unavailable: "Could not create todo.",
    invalidData: "The API returned invalid todo data while creating.",
  },
  update: {
    unavailable: "Could not update todo.",
    invalidData: "The API returned invalid todo data while updating.",
  },
  delete: {
    unavailable: "Could not delete todo.",
    invalidData: "Could not delete todo.",
  },
};

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function normalizeTodoTitle(input: string): string | null {
  if (typeof input !== "string") return null;
  const title = input.trim();
  if (title.length === 0) return null;
  if (title.includes("\u0000")) return null;
  let codePoints = 0;
  for (let index = 0; index < title.length; index += 1) {
    const code = title.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = title.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return null;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return null;
    }
    codePoints += 1;
  }
  if (codePoints > 120) return null;
  return title;
}

function isTodo(value: unknown): value is Todo {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = Reflect.ownKeys(record);
  if (
    keys.length !== 3 ||
    !keys.every((key) => typeof key === "string") ||
    !keys.includes("id") ||
    !keys.includes("title") ||
    !keys.includes("completed")
  ) {
    return false;
  }

  const id = record.id;
  const title = record.title;
  return (
    typeof id === "string" &&
    uuidPattern.test(id) &&
    typeof title === "string" &&
    normalizeTodoTitle(title) === title &&
    typeof record.completed === "boolean"
  );
}

function requestJson(
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  expectedStatus: number,
  operation: TodoOperation,
  options: TodoRequestOptions,
  body?: RequestBody,
): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const finish = (error?: Error, value?: unknown) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      options.signal?.removeEventListener("abort", cancel);
      if (error) reject(error);
      else resolve(value);
    };

    const cancel = () => {
      const error = new Error("The todo request was cancelled.");
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
      url = new URL(path, parsed).toString();
    } catch {
      finish(new TodoApiError("unavailable", operationMessages[operation].unavailable));
      return;
    }

    timer = setTimeout(() => {
      finish(new TodoApiError("unavailable", operationMessages[operation].unavailable));
      controller.abort();
    }, options.timeoutMs ?? 5_000);

    void (async () => {
      try {
        const request: RequestInit = { method, signal: controller.signal };
        if (body !== undefined) {
          request.headers = { "Content-Type": "application/json" };
          request.body = JSON.stringify(body);
        }
        const result = await (options.fetchImpl ?? fetch)(url, request);
        if (settled) return;
        if (result.status !== expectedStatus) {
          const error = result.status === 422
            ? new TodoApiError("validation", "Check the todo title and try again.")
            : (operation === "update" || operation === "delete") && result.status === 404
              ? new TodoApiError("not-found", "That todo no longer exists. Refresh the list.")
              : new TodoApiError("unavailable", operationMessages[operation].unavailable);
          finish(error);
          controller.abort();
          return;
        }

        if (expectedStatus === 204) {
          finish(undefined, undefined);
          return;
        }

        let parsedBody: unknown;
        try {
          parsedBody = await result.json();
        } catch {
          finish(new TodoApiError("invalid-data", operationMessages[operation].invalidData));
          return;
        }
        if (settled) return;
        finish(undefined, parsedBody);
      } catch {
        if (!settled) finish(new TodoApiError("unavailable", operationMessages[operation].unavailable));
      }
    })();
  });
}

export async function listTodos(options: TodoRequestOptions = {}): Promise<Todo[]> {
  const body = await requestJson("/todos", "GET", 200, "list", options);
  if (!Array.isArray(body) || !body.every(isTodo)) {
    throw new TodoApiError("invalid-data", operationMessages.list.invalidData);
  }
  return body;
}

export async function createTodo(title: string, options: TodoRequestOptions = {}): Promise<Todo> {
  const body = await requestJson("/todos", "POST", 201, "create", options, { title });
  if (!isTodo(body)) throw new TodoApiError("invalid-data", operationMessages.create.invalidData);
  return body;
}

export async function setTodoCompleted(
  id: string,
  completed: boolean,
  options: TodoRequestOptions = {},
): Promise<Todo> {
  const body = await requestJson(`/todos/${id}`, "PATCH", 200, "update", options, {
    completed,
  });
  if (!isTodo(body)) throw new TodoApiError("invalid-data", operationMessages.update.invalidData);
  return body;
}

export async function setTodoTitle(
  id: string,
  title: string,
  options: TodoRequestOptions = {},
): Promise<Todo> {
  const body = await requestJson(`/todos/${id}`, "PATCH", 200, "update", options, {
    title,
  });
  if (!isTodo(body)) throw new TodoApiError("invalid-data", operationMessages.update.invalidData);
  return body;
}

export async function deleteTodo(id: string, options: TodoRequestOptions = {}): Promise<void> {
  await requestJson(`/todos/${id}`, "DELETE", 204, "delete", options);
}
