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
  | "auth-required"
  | "conflict";

export type WorkflowConflictCode =
  | "stale_step"
  | "request_id_reused"
  | "invalid_action"
  | "terminal_workflow"
  | "unsupported_workflow_definition"
  | "revision_exhausted"
  | "suggestion_in_progress"
  | "stale_suggestion"
  | "invalid_state";

export type WorkflowSuggestionErrorCode =
  | "not_configured"
  | "timeout"
  | "provider_unavailable"
  | "invalid_output";

export class TodoApiError extends Error {
  constructor(
    readonly kind: TodoApiErrorKind,
    message: string,
    readonly conflictCode?: WorkflowConflictCode,
    readonly suggestionCode?: WorkflowSuggestionErrorCode,
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

type TodoOperation =
  | "list"
  | "create"
  | "update"
  | "delete"
  | "signup"
  | "login"
  | "logout"
  | "me"
  | "start-workflow"
  | "get-workflow"
  | "advance-workflow"
  | "list-workflows"
  | "get-suggestion"
  | "suggest-workflow";
type RequestBody =
  | { title: string }
  | { completed: boolean }
  | { username: string; password: string }
  | { request_id: string; title: string }
  | {
      request_id: string;
      expected_revision: number;
      step_id: string;
      action: TodoWorkflowAction;
    }
  | { action: "answer_multiple_steps"; answer: boolean }
  | { action: "submit_tasks"; titles: string[] }
  | { action: "confirm" }
  | { action: "cancel" }
  | WorkflowSuggestionRequest;

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
  "start-workflow": {
    unavailable: "Could not start planning.",
    invalidData: "The API returned invalid plan data.",
    validation: "Check the plan details and try again.",
    authRequired: "Please sign in again.",
  },
  "get-workflow": {
    unavailable: "Could not reload the plan.",
    invalidData: "The API returned invalid plan data.",
    validation: "Check the plan details and try again.",
    authRequired: "Please sign in again.",
  },
  "advance-workflow": {
    unavailable: "Could not update the plan.",
    invalidData: "The API returned invalid plan data.",
    validation: "Check the plan details and try again.",
    authRequired: "Please sign in again.",
  },
  "list-workflows": {
    unavailable: "Could not load saved plans.",
    invalidData: "The API returned invalid plan data.",
    validation: "Check the plan details and try again.",
    authRequired: "Please sign in again.",
  },
  "get-suggestion": {
    unavailable: "Could not load todo suggestions.",
    invalidData: "The API returned invalid todo suggestions.",
    validation: "Check the suggestion request and try again.",
    authRequired: "Please sign in again.",
  },
  "suggest-workflow": {
    unavailable: "Could not suggest todos.",
    invalidData: "The API returned invalid todo suggestions.",
    validation: "Check the suggestion request and try again.",
    authRequired: "Please sign in again.",
  },
};

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const workflowOperations: ReadonlySet<TodoOperation> = new Set([
  "start-workflow",
  "get-workflow",
  "advance-workflow",
  "list-workflows",
  "get-suggestion",
  "suggest-workflow",
]);

const workflowConflictMessages: Record<WorkflowConflictCode, string> = {
  stale_step: "This plan changed. Reload it and try again.",
  request_id_reused: "This request ID was already used with different details.",
  invalid_action: "Action is not valid for the current workflow state.",
  terminal_workflow: "Todo workflow is already terminal.",
  unsupported_workflow_definition: "This plan uses an unsupported workflow definition.",
  revision_exhausted: "This plan has reached its revision limit.",
  suggestion_in_progress: "A suggestion request is already in progress.",
  stale_suggestion: "This suggestion request is no longer current.",
  invalid_state: "Suggestions are only available while collecting todo titles.",
};

function parseWorkflowConflictCode(value: unknown): WorkflowConflictCode | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const detail = (value as Record<string, unknown>).detail;
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) {
    return undefined;
  }
  const code = (detail as Record<string, unknown>).code;
  switch (code) {
    case "stale_step":
    case "request_id_reused":
    case "invalid_action":
    case "terminal_workflow":
    case "unsupported_workflow_definition":
    case "revision_exhausted":
    case "suggestion_in_progress":
    case "stale_suggestion":
    case "invalid_state":
      return code;
    default:
      return undefined;
  }
}

function parseSuggestionErrorCode(value: unknown): WorkflowSuggestionErrorCode | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const detail = (value as Record<string, unknown>).detail;
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) return undefined;
  switch ((detail as Record<string, unknown>).code) {
    case "not_configured":
    case "timeout":
    case "provider_unavailable":
    case "invalid_output":
      return (detail as Record<string, unknown>).code as WorkflowSuggestionErrorCode;
    default:
      return undefined;
  }
}

/** Count Unicode code points, returning null for unpaired surrogates. This is
 *  the same surrogate-aware walk normalizeTodoTitle uses, shared so answer
 *  and clarification validation agree with the server exactly. */
export function countCodePoints(value: string): number | null {
  let codePoints = 0;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return null;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return null;
    }
    codePoints += 1;
  }
  return codePoints;
}

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
  expectedStatus: number | number[],
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
        const expectedStatuses = Array.isArray(expectedStatus)
          ? expectedStatus
          : [expectedStatus];
        if (!expectedStatuses.includes(result.status)) {
          if (
            (operation === "get-suggestion" || operation === "suggest-workflow") &&
            result.status !== 409
          ) {
            let suggestionCode: WorkflowSuggestionErrorCode | undefined;
            try {
              suggestionCode = parseSuggestionErrorCode(await result.json());
            } catch {
              suggestionCode = undefined;
            }
            const codeMatchesStatus =
              (suggestionCode === "not_configured" && result.status === 503) ||
              (suggestionCode === "timeout" && result.status === 504) ||
              ((suggestionCode === "provider_unavailable" ||
                suggestionCode === "invalid_output") &&
                result.status === 502);
            if (suggestionCode !== undefined && codeMatchesStatus) {
              finish(
                new TodoApiError(
                  "unavailable",
                  operationMessages[operation].unavailable,
                  undefined,
                  suggestionCode,
                )
              );
              controller.abort();
              return;
            }
          }
          if (result.status === 409 && workflowOperations.has(operation)) {
            let code: WorkflowConflictCode | undefined;
            try {
              code = parseWorkflowConflictCode(await result.json());
            } catch {
              code = undefined;
            }
            if (settled) return;
            finish(
              code === undefined
                ? new TodoApiError("conflict", "The plan changed. Reload to continue.")
                : new TodoApiError("conflict", workflowConflictMessages[code], code)
            );
            controller.abort();
            return;
          }
          const error = result.status === 422
            ? new TodoApiError("validation", operationMessages[operation].validation)
            : result.status === 401
              ? new TodoApiError("auth-required", operationMessages[operation].authRequired)
              : result.status === 409
                ? new TodoApiError("conflict", "The plan changed. Reload to continue.")
                : (operation === "get-workflow" || operation === "advance-workflow" ||
                    operation === "get-suggestion" || operation === "suggest-workflow") &&
                    result.status === 404
                  ? new TodoApiError(
                      "not-found",
                      operation === "get-suggestion"
                        ? "That plan has no saved todo suggestions."
                        : "That plan no longer exists. Refresh the list."
                    )
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

export type TodoWorkflowState = string;

export const MAX_WORKFLOW_REVISION = 2147483647;

export type KnownTodoWorkflow = {
  workflow_id: string;
  revision: number;
  definition_version: 1;
  view_contract_version: 1;
  state: TodoWorkflowState;
  title: string;
  context: {
    involves_multiple_steps: boolean | null;
    proposed_todo_titles: string[];
  };
  result: { created_todos: Todo[] } | null;
  view: TodoWorkflowView;
};

export type UnsupportedContractWorkflow = {
  workflow_id: string;
  revision: number;
  definition_version: number;
  view_contract_version: number;
  view: {
    type: "unsupported";
    server_type: string;
    step_id: string;
  };
};

export type TodoWorkflow = KnownTodoWorkflow | UnsupportedContractWorkflow;

export type WorkflowStartRequest = { request_id: string; title: string };

export type WorkflowActionRequest = {
  request_id: string;
  expected_revision: number;
  step_id: string;
  action: TodoWorkflowAction;
};

export type TodoWorkflowAction =
  | { action: "answer_multiple_steps"; answer: boolean }
  | { action: "submit_tasks"; titles: string[] }
  | { action: "confirm" }
  | { action: "cancel" };

type KnownTodoWorkflowView =
  | {
      type: "yes_no";
      step_id: string;
      title: string;
      question: string;
      actions: [{ id: "yes"; label: string }, { id: "no"; label: string }];
    }
  | { type: "task_breakdown"; step_id: string; title: string; min_titles: number; max_titles: number }
  | { type: "review"; step_id: string; title: string; proposed_titles: string[] }
  | { type: "completion"; step_id: string; title: string; outcome: "completed" | "cancelled"; created_todos: Todo[] };

type UnsupportedTodoWorkflowView = {
  type: "unsupported";
  server_type: string;
  step_id: string;
};

export type TodoWorkflowView = KnownTodoWorkflowView | UnsupportedTodoWorkflowView;

const exactObject = (value: unknown, keys: string[]): value is Record<string, unknown> =>
  typeof value === "object" &&
  value !== null &&
  !Array.isArray(value) &&
  Reflect.ownKeys(value).length === keys.length &&
  keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));

const isCanonicalTitle = (value: unknown): value is string =>
  typeof value === "string" && normalizeTodoTitle(value) === value;

type BreakdownView = Extract<KnownTodoWorkflowView, { type: "task_breakdown" }>;
type ReviewView = Extract<KnownTodoWorkflowView, { type: "review" }>;
type CompletionView = Extract<KnownTodoWorkflowView, { type: "completion" }>;

function isExactBreakdownView(
  view: Record<string, unknown>,
): view is BreakdownView {
  return (
    exactObject(view, ["type", "step_id", "title", "min_titles", "max_titles"]) &&
    isCanonicalTitle(view.title) &&
    Number.isInteger(view.min_titles) &&
    Number.isInteger(view.max_titles) &&
    (view.min_titles as number) >= 1 &&
    (view.min_titles as number) <= (view.max_titles as number)
  );
}

function isExactReviewView(view: Record<string, unknown>): view is ReviewView {
  return (
    exactObject(view, ["type", "step_id", "title", "proposed_titles"]) &&
    isCanonicalTitle(view.title) &&
    Array.isArray(view.proposed_titles) &&
    view.proposed_titles.every(isCanonicalTitle)
  );
}

function isExactCompletionView(
  view: Record<string, unknown>,
): view is CompletionView {
  return (
    exactObject(view, ["type", "step_id", "title", "outcome", "created_todos"]) &&
    isCanonicalTitle(view.title) &&
    (view.outcome === "completed" || view.outcome === "cancelled") &&
    Array.isArray(view.created_todos) &&
    view.created_todos.every(isTodo)
  );
}

function parseWorkflowView(
  value: unknown,
  expectedStepId: string,
): TodoWorkflowView | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const view = value as Record<string, unknown>;
  if (typeof view.type !== "string" || view.type.length === 0) return null;
  if (view.step_id !== expectedStepId) return null;
  switch (view.type) {
    case "yes_no":
      if (!exactObject(view, ["type", "step_id", "title", "question", "actions"])) return null;
      if (!isCanonicalTitle(view.title) || typeof view.question !== "string") return null;
      if (!Array.isArray(view.actions) || view.actions.length !== 2) return null;
      if (!exactObject(view.actions[0], ["id", "label"]) || view.actions[0].id !== "yes") return null;
      if (!exactObject(view.actions[1], ["id", "label"]) || view.actions[1].id !== "no") return null;
      if (typeof view.actions[0].label !== "string" || typeof view.actions[1].label !== "string") return null;
      return view as KnownTodoWorkflowView;
    case "task_breakdown":
      return isExactBreakdownView(view) ? view : null;
    case "review":
      return isExactReviewView(view) ? view : null;
    case "completion":
      return isExactCompletionView(view) ? view : null;
    default:
      return { type: "unsupported", server_type: view.type, step_id: expectedStepId };
  }
}

type WorkflowMetadata = {
  workflow_id: string;
  revision: number;
  definition_version: number;
  view_contract_version: number;
};

function parseWorkflowMetadata(value: unknown): WorkflowMetadata | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const { workflow_id, revision, definition_version, view_contract_version } = record;
  if (typeof workflow_id !== "string" || !uuidPattern.test(workflow_id)) return null;
  if (
    !Number.isInteger(revision) ||
    (revision as number) < 0 ||
    (revision as number) > MAX_WORKFLOW_REVISION
  ) {
    return null;
  }
  if (!Number.isSafeInteger(definition_version) || (definition_version as number) < 1) {
    return null;
  }
  if (
    !Number.isSafeInteger(view_contract_version) ||
    (view_contract_version as number) < 1
  ) {
    return null;
  }
  return {
    workflow_id,
    revision: revision as number,
    definition_version: definition_version as number,
    view_contract_version: view_contract_version as number,
  };
}

function parseTodoWorkflow(value: unknown): TodoWorkflow | null {
  const metadata = parseWorkflowMetadata(value);
  if (metadata === null) return null;
  if (
    metadata.view_contract_version !== 1 ||
    metadata.definition_version !== 1
  ) {
    if (metadata.view_contract_version === 1) return null;
    return {
      workflow_id: metadata.workflow_id,
      revision: metadata.revision,
      definition_version: metadata.definition_version,
      view_contract_version: metadata.view_contract_version,
      view: {
        type: "unsupported",
        server_type: `contract:${metadata.view_contract_version}`,
        step_id: `${metadata.workflow_id}:unsupported-contract:${metadata.view_contract_version}`,
      },
    };
  }
  if (!exactObject(value, ["workflow_id", "revision", "definition_version", "view_contract_version", "state", "title", "context", "result", "view"])) {
    return null;
  }
  if (
    typeof value.state !== "string" ||
    value.state.length === 0 ||
    !isCanonicalTitle(value.title) ||
    !exactObject(value.context, ["involves_multiple_steps", "proposed_todo_titles"])
  ) {
    return null;
  }

  const answer = value.context.involves_multiple_steps;
  const proposals = value.context.proposed_todo_titles;
  if (
    !(answer === null || typeof answer === "boolean") ||
    !Array.isArray(proposals) ||
    !proposals.every(isCanonicalTitle)
  ) {
    return null;
  }

  let result: KnownTodoWorkflow["result"] = null;
  if (value.result !== null) {
    if (!exactObject(value.result, ["created_todos"])) return null;
    if (!Array.isArray(value.result.created_todos) || !value.result.created_todos.every(isTodo)) {
      return null;
    }
    result = { created_todos: value.result.created_todos };
  }

  const view = parseWorkflowView(
    value.view,
    `${value.workflow_id}:${value.state}`,
  );
  if (view === null) return null;
  return {
    workflow_id: metadata.workflow_id,
    revision: metadata.revision,
    definition_version: 1,
    view_contract_version: 1,
    state: value.state,
    title: value.title,
    context: {
      involves_multiple_steps: answer,
      proposed_todo_titles: proposals,
    },
    result,
    view,
  };
}

export async function startTodoWorkflow(
  request: WorkflowStartRequest,
  options: TodoRequestOptions = {}
): Promise<TodoWorkflow> {
  const body = await requestJson(
    "/todo-workflows",
    "POST",
    201,
    "start-workflow",
    options,
    { request_id: request.request_id, title: request.title }
  );
  const parsed = parseTodoWorkflow(body);
  if (parsed === null) {
    throw new TodoApiError("invalid-data", operationMessages["start-workflow"].invalidData);
  }
  return parsed;
}

export async function getTodoWorkflow(
  id: string,
  options: TodoRequestOptions = {}
): Promise<TodoWorkflow> {
  const body = await requestJson(`/todo-workflows/${id}`, "GET", 200, "get-workflow", options);
  const parsed = parseTodoWorkflow(body);
  if (parsed === null) {
    throw new TodoApiError("invalid-data", operationMessages["get-workflow"].invalidData);
  }
  return parsed;
}

export type WorkflowSuggestionRequest = {
  request_id: string;
  expected_revision: number;
  step_id: string;
  clarification?: WorkflowSuggestionClarification;
};

/** Fixed clarification catalog shared with the Python agent (Task 2/3). The
 *  server chooses only the field; question copy stays local to the panel. */
export const CLARIFICATION_FIELDS = [
  "date",
  "location",
  "people",
  "budget",
  "constraints",
] as const;

export type ClarificationField = (typeof CLARIFICATION_FIELDS)[number];

export type WorkflowSuggestionClarification = {
  field: ClarificationField;
  value: string;
};

const isClarificationField = (value: unknown): value is ClarificationField =>
  typeof value === "string" &&
  (CLARIFICATION_FIELDS as readonly string[]).includes(value);

/** Client-side shape check mirroring the server bounds: catalog field plus a
 *  1–200-code-point answer after trimming. The server remains authoritative;
 *  this keeps invalid payloads out of durable pending storage. */
export function isWorkflowSuggestionClarification(
  value: unknown
): value is WorkflowSuggestionClarification {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (!exactObject(record, ["field", "value"])) return false;
  if (!isClarificationField(record.field)) return false;
  if (typeof record.value !== "string" || record.value.includes("\0")) {
    return false;
  }
  const trimmed = record.value.trim();
  if (trimmed.length === 0) return false;
  const codePoints = countCodePoints(trimmed);
  if (codePoints === null || codePoints > 200) return false;
  return true;
}

export type WorkflowSuggestionStatus = "pending" | "ready" | "failed" | "superseded";

export type WorkflowSuggestion = {
  contract_version: 1;
  workflow_id: string;
  request_id: string;
  base_revision: number;
  step_id: string;
  status: WorkflowSuggestionStatus;
  proposed_titles: string[];
  error_code: WorkflowSuggestionErrorCode | null;
};

function isWorkflowSuggestion(value: unknown, workflowId: string): value is WorkflowSuggestion {
  if (
    !exactObject(value, [
      "contract_version",
      "workflow_id",
      "request_id",
      "base_revision",
      "step_id",
      "status",
      "proposed_titles",
      "error_code",
    ]) ||
    value.contract_version !== 1 ||
    typeof value.workflow_id !== "string" ||
    !uuidPattern.test(value.workflow_id) ||
    value.workflow_id !== workflowId ||
    typeof value.request_id !== "string" ||
    !uuidPattern.test(value.request_id) ||
    !Number.isInteger(value.base_revision) ||
    (value.base_revision as number) < 0 ||
    (value.base_revision as number) > MAX_WORKFLOW_REVISION ||
    typeof value.step_id !== "string" ||
    !value.step_id.startsWith(`${workflowId}:`) ||
    !Array.isArray(value.proposed_titles) ||
    !value.proposed_titles.every(isCanonicalTitle)
  ) {
    return false;
  }
  const status = value.status;
  const errorCode = value.error_code;
  if (
    status !== "pending" &&
    status !== "ready" &&
    status !== "failed" &&
    status !== "superseded"
  ) {
    return false;
  }
  if (
    errorCode !== null &&
    errorCode !== "not_configured" &&
    errorCode !== "timeout" &&
    errorCode !== "provider_unavailable" &&
    errorCode !== "invalid_output"
  ) {
    return false;
  }
  if (status === "ready") {
    return (
      errorCode === null &&
      value.proposed_titles.length >= 2 &&
      value.proposed_titles.length <= 10
    );
  }
  if (status === "failed") {
    return errorCode !== null && value.proposed_titles.length === 0;
  }
  return errorCode === null && value.proposed_titles.length === 0;
}

export async function getWorkflowSuggestion(
  id: string,
  options: TodoRequestOptions = {},
): Promise<WorkflowSuggestion> {
  const body = await requestJson(
    `/todo-workflows/${id}/suggestions`,
    "GET",
    200,
    "get-suggestion",
    options,
  );
  if (!isWorkflowSuggestion(body, id)) {
    throw new TodoApiError("invalid-data", operationMessages["get-suggestion"].invalidData);
  }
  return body;
}

export async function suggestWorkflowTodos(
  id: string,
  request: WorkflowSuggestionRequest,
  options: TodoRequestOptions = {},
): Promise<WorkflowSuggestion> {
  const body = await requestJson(
    `/todo-workflows/${id}/suggestions`,
    "POST",
    [200, 201],
    "suggest-workflow",
    { ...options, timeoutMs: 35_000 },
    request,
  );
  if (!isWorkflowSuggestion(body, id)) {
    throw new TodoApiError("invalid-data", operationMessages["suggest-workflow"].invalidData);
  }
  return body;
}

export async function advanceTodoWorkflow(
  id: string,
  request: WorkflowActionRequest,
  options: TodoRequestOptions = {}
): Promise<TodoWorkflow> {
  const body = await requestJson(
    `/todo-workflows/${id}/actions`,
    "POST",
    200,
    "advance-workflow",
    options,
    {
      request_id: request.request_id,
      expected_revision: request.expected_revision,
      step_id: request.step_id,
      action: request.action,
    }
  );
  const parsed = parseTodoWorkflow(body);
  if (parsed === null) {
    throw new TodoApiError("invalid-data", operationMessages["advance-workflow"].invalidData);
  }
  return parsed;
}

export async function listTodoWorkflows(
  options: TodoRequestOptions = {}
): Promise<{ items: TodoWorkflow[] }> {
  const body = await requestJson(
    "/todo-workflows?status=active",
    "GET",
    200,
    "list-workflows",
    options
  );
  if (!exactObject(body, ["items"]) || !Array.isArray(body.items)) {
    throw new TodoApiError("invalid-data", operationMessages["list-workflows"].invalidData);
  }
  const items: TodoWorkflow[] = [];
  for (const item of body.items) {
    const parsed = parseTodoWorkflow(item);
    if (parsed === null) {
      throw new TodoApiError("invalid-data", operationMessages["list-workflows"].invalidData);
    }
    items.push(parsed);
  }
  return { items };
}
