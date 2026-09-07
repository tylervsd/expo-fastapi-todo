export type Todo = {
  id: string;
  title: string;
  completed: boolean;
};

export type TodoApiErrorKind =
  | "validation"
  | "not-found"
  | "unavailable"
  | "invalid-data"
  | "auth-required";

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
  token?: string;
};

type TodoOperation = "list" | "create" | "update" | "delete" | "signup" | "login" | "logout" | "me";
type RequestBody = { title: string } | { completed: boolean } | { username: string; password: string };

const operationMessages: Record<
  TodoOperation,
  { unavailable: string; invalidData: string; validation: string; authRequired: string }
> = {
  list: {
    unavailable: "Could not load todos.",
    invalidData: "The API returned invalid todo data while loading.",
    validation: "Check the todo title and try again.",
    authRequired: "Please sign in again.",
  },
  create: {
    unavailable: "Could not create todo.",
    invalidData: "The API returned invalid todo data while creating.",
    validation: "Check the todo title and try again.",
    authRequired: "Please sign in again.",
  },
  update: {
    unavailable: "Could not update todo.",
    invalidData: "The API returned invalid todo data while updating.",
    validation: "Check the todo title and try again.",
    authRequired: "Please sign in again.",
  },
  delete: {
    unavailable: "Could not delete todo.",
    invalidData: "Could not delete todo.",
    validation: "Check the todo title and try again.",
    authRequired: "Please sign in again.",
  },
  signup: {
    unavailable: "Could not create account.",
    invalidData: "The API returned invalid account data.",
    validation: "Check the username and password and try again.",
    authRequired: "Please sign in again.",
  },
  login: {
    unavailable: "Could not sign in.",
    invalidData: "The API returned invalid session data.",
    validation: "Check the username and password and try again.",
    authRequired: "Invalid username or password.",
  },
  logout: {
    unavailable: "Could not sign out.",
    invalidData: "Could not sign out.",
    validation: "Could not sign out.",
    authRequired: "Could not sign out.",
  },
  me: {
    unavailable: "Could not restore session.",
    invalidData: "The API returned invalid session data.",
    validation: "Please sign in again.",
    authRequired: "Please sign in again.",
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
        const headers: Record<string, string> = {};
        if (body !== undefined) {
          headers["Content-Type"] = "application/json";
          request.body = JSON.stringify(body);
        }
        if (options.token !== undefined) {
          headers["Authorization"] = `Bearer ${options.token}`;
        }
        if (Object.keys(headers).length > 0) {
          request.headers = headers;
        }
        const result = await (options.fetchImpl ?? fetch)(url, request);
        if (settled) return;
        if (result.status !== expectedStatus) {
          const error = result.status === 422
            ? new TodoApiError("validation", operationMessages[operation].validation)
            : result.status === 401
              ? new TodoApiError("auth-required", operationMessages[operation].authRequired)
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

export type AuthUser = {
  id: string;
  username: string;
};

export type Session = {
  token: string;
  expires_at: string;
  user: AuthUser;
};

const usernamePattern = /^[A-Za-z0-9_-]{3,32}$/;

function isAuthUser(value: unknown): value is AuthUser {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = Reflect.ownKeys(record);
  return (
    keys.length === 2 &&
    keys.every((key) => typeof key === "string") &&
    typeof record.id === "string" &&
    uuidPattern.test(record.id) &&
    typeof record.username === "string" &&
    usernamePattern.test(record.username)
  );
}

function isSession(value: unknown): value is Session {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = Reflect.ownKeys(record);
  return (
    keys.length === 3 &&
    keys.every((key) => typeof key === "string") &&
    typeof record.token === "string" &&
    record.token.length > 0 &&
    typeof record.expires_at === "string" &&
    record.expires_at.length > 0 &&
    isAuthUser(record.user)
  );
}

export async function signup(
  username: string,
  password: string,
  options: TodoRequestOptions = {},
): Promise<AuthUser> {
  const body = await requestJson("/auth/signup", "POST", 201, "signup", options, {
    username,
    password,
  });
  if (!isAuthUser(body)) throw new TodoApiError("invalid-data", operationMessages.signup.invalidData);
  return body;
}

export async function login(
  username: string,
  password: string,
  options: TodoRequestOptions = {},
): Promise<Session> {
  const body = await requestJson("/auth/login", "POST", 200, "login", options, {
    username,
    password,
  });
  if (!isSession(body)) throw new TodoApiError("invalid-data", operationMessages.login.invalidData);
  return body;
}

export async function logout(options: TodoRequestOptions = {}): Promise<void> {
  await requestJson("/auth/logout", "POST", 204, "logout", options);
}

export async function fetchMe(options: TodoRequestOptions = {}): Promise<AuthUser> {
  const body = await requestJson("/auth/me", "GET", 200, "me", options);
  if (!isAuthUser(body)) throw new TodoApiError("invalid-data", operationMessages.me.invalidData);
  return body;
}
