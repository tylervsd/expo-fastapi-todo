// Phase 12 browser E2E: four signed-in journeys through the real Expo web
// export, fixture FastAPI entry point, and PostgreSQL on Chromium.
//
// Every case seeds a fresh account (never shared between cases), signs in
// through the UI, and ends with sign-out. API assertions use separate real
// sessions via /auth/login and never inject browser tokens. No sleeps,
// route interception, or token injection; optimistic writes are awaited with
// expect.poll around real /todos reads.
import { execFileSync } from "node:child_process";
import * as path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "..", "..");
const apiBase = process.env.E2E_API_URL ?? "http://127.0.0.1:8001";

type Account = {
  username: string;
  password: string;
};

type TodoRow = {
  title: string;
  completed: boolean;
};

function seedAccount(prefix: string): Account {
  const output = execFileSync(
    "uv",
    [
      "run",
      "--directory",
      "apps/api",
      "python",
      "-m",
      "e2e.support",
      "seed",
      "--prefix",
      prefix,
    ],
    { cwd: repoRoot, encoding: "utf-8" },
  );
  return JSON.parse(output) as Account;
}

function sortedRows(todos: TodoRow[]): TodoRow[] {
  return [...todos].sort((a, b) =>
    a.title < b.title ? -1 : a.title > b.title ? 1 : 0,
  );
}

async function readTodos(account: Account): Promise<TodoRow[]> {
  const login = await fetch(`${apiBase}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: account.username,
      password: account.password,
    }),
  });
  if (!login.ok) {
    throw new Error(`e2e login failed with status ${login.status}`);
  }
  const session = (await login.json()) as { token: string };
  const response = await fetch(`${apiBase}/todos`, {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  if (!response.ok) {
    throw new Error(`e2e /todos failed with status ${response.status}`);
  }
  const todos = (await response.json()) as Array<
    TodoRow & Record<string, unknown>
  >;
  return sortedRows(
    todos.map((todo) => ({
      title: String(todo.title),
      completed: Boolean(todo.completed),
    })),
  );
}

async function expectTodos(
  account: Account,
  expected: TodoRow[],
): Promise<void> {
  await expect
    .poll(() => readTodos(account), { timeout: 10_000 })
    .toEqual(sortedRows(expected));
}

async function signIn(page: Page, account: Account): Promise<void> {
  await page.getByLabel("Username", { exact: true }).fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByLabel("Todo title", { exact: true }),
  ).toBeVisible();
}

async function signOut(page: Page, absentTitles: string[] = []): Promise<void> {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByLabel("Username", { exact: true })).toBeVisible();
  for (const title of absentTitles) {
    await expect(
      page.getByRole("checkbox", { name: title, exact: true }),
    ).toBeHidden();
    await expect(page.getByText(title, { exact: true })).toBeHidden();
  }
}

// Guided, direct-suggest, and agent flows all start from the task-breakdown
// step of a fresh workflow; only the title differs per case.
async function startCollectStep(page: Page, title: string): Promise<void> {
  await page
    .getByRole("button", { name: "Help me plan a task", exact: true })
    .click();
  await page.getByLabel("Task title", { exact: true }).fill(title);
  await page
    .getByRole("button", { name: "Start planning", exact: true })
    .click();
  await expect(
    page.getByText("Does this task involve multiple steps?", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Yes", exact: true }).click();
  await expect(
    page.getByText("Would you like to split it into smaller todos?", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Yes", exact: true }).click();
  await expect(
    page.getByLabel("Todo titles (one per line)", { exact: true }),
  ).toBeVisible();
}

let account: Account;

test.beforeEach(async ({ page }) => {
  account = seedAccount("web");
  await page.goto("/");
});

test("core todo CRUD isolates accounts", async ({ page }) => {
  await signIn(page, account);

  await page.getByLabel("Todo title", { exact: true }).fill("Buy milk");
  await page.getByRole("button", { name: "Add todo", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "Buy milk", exact: true }),
  ).toBeVisible();
  await expectTodos(account, [{ title: "Buy milk", completed: false }]);

  await page
    .getByRole("button", { name: "Edit Buy milk", exact: true })
    .click();
  await page.getByLabel("Edit todo title", { exact: true }).fill("Buy oat milk");
  await page
    .getByRole("button", { name: "Save changes", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "Buy oat milk", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "Buy milk", exact: true }),
  ).toBeHidden();
  await expectTodos(account, [{ title: "Buy oat milk", completed: false }]);

  await page
    .getByRole("checkbox", { name: "Buy oat milk", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", {
      name: "Buy oat milk",
      exact: true,
      checked: true,
    }),
  ).toBeVisible();
  await expectTodos(account, [{ title: "Buy oat milk", completed: true }]);

  await page.getByRole("button", { name: "Completed", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "Buy oat milk", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Active", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "Buy oat milk", exact: true }),
  ).toBeHidden();
  await expect(
    page.getByText("No active todos.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "Buy oat milk", exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Delete Buy oat milk", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm delete", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "Buy oat milk", exact: true }),
  ).toBeHidden();
  await expectTodos(account, []);

  await signOut(page, ["Buy oat milk"]);

  const second = seedAccount("web");
  await signIn(page, second);
  await expect(
    page.getByText("No todos yet. Add one above.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Buy oat milk", { exact: true }),
  ).toBeHidden();
  await expectTodos(second, []);
  await signOut(page, ["Buy oat milk"]);
});

test("guided creation survives reload", async ({ page }) => {
  await signIn(page, account);
  await startCollectStep(page, "Prepare weekend");

  await page
    .getByLabel("Todo titles (one per line)", { exact: true })
    .fill("Pack bag\nCheck weather");
  await page.getByRole("button", { name: "Save tasks", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Confirm plan", exact: true }),
  ).toBeVisible();
  await expectTodos(account, []);

  await page.reload();
  await page
    .getByRole("button", {
      name: "Prepare weekend, Review your plan",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("button", { name: "Confirm plan", exact: true }),
  ).toBeVisible();
  await expectTodos(account, []);

  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  await page
    .getByRole("button", { name: "Back to todos", exact: true })
    .click();
  const expected: TodoRow[] = [
    { title: "Check weather", completed: false },
    { title: "Pack bag", completed: false },
  ];
  await expectTodos(account, expected);
  await expect(
    page.getByRole("checkbox", { name: "Pack bag", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "Check weather", exact: true }),
  ).toBeVisible();

  await page.reload();
  await expect(
    page.getByRole("checkbox", { name: "Pack bag", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "Check weather", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await expectTodos(account, expected);

  await signOut(page, ["Pack bag", "Check weather"]);
});

test("direct suggestions create edited todos", async ({ page }) => {
  await signIn(page, account);
  await startCollectStep(page, "Organize supplies");

  await page
    .getByRole("button", { name: "Suggest todos", exact: true })
    .click();
  const draft = page.getByLabel("Todo titles (one per line)", {
    exact: true,
  });
  await expect(draft).toHaveValue(
    "Gather supplies\nPrepare workspace\nComplete the task",
    { timeout: 10_000 },
  );
  await expectTodos(account, []);

  await draft.fill("Gather reusable supplies\nPrepare workspace");
  await page.getByRole("button", { name: "Save tasks", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Confirm plan", exact: true }),
  ).toBeVisible();
  await expectTodos(account, []);

  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  await page
    .getByRole("button", { name: "Back to todos", exact: true })
    .click();
  const expected: TodoRow[] = [
    { title: "Gather reusable supplies", completed: false },
    { title: "Prepare workspace", completed: false },
  ];
  await expectTodos(account, expected);
  await expect(
    page.getByRole("checkbox", {
      name: "Gather reusable supplies",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "Prepare workspace", exact: true }),
  ).toBeVisible();

  await signOut(page, ["Gather reusable supplies", "Prepare workspace"]);
});

test("agent suggestions create edited todos", async ({ page }) => {
  // Passive observation only: record successful POST /agent stream
  // responses (status and path; never headers or bodies) to prove the agent
  // case runs through real AG-UI streaming. No route interception.
  const agentStreams: Array<{ status: number; path: string }> = [];
  page.on("response", (response) => {
    if (response.request().method() !== "POST") {
      return;
    }
    const url = new URL(response.url());
    if (
      url.host === "127.0.0.1:8001" &&
      url.pathname === "/agent" &&
      response.status() === 200
    ) {
      agentStreams.push({ status: response.status(), path: url.pathname });
    }
  });

  await signIn(page, account);
  await startCollectStep(page, "Organize supplies");

  await page
    .getByRole("button", { name: "Ask agent for help", exact: true })
    .click();
  await expect(
    page.getByLabel("Your answer", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Your answer", { exact: true })
    .fill("Use supplies already available");
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(
    page.getByLabel("Suggestion 1 of 3", { exact: true }),
  ).toBeVisible();
  await expectTodos(account, []);

  await page
    .getByLabel("Suggestion 1 of 3", { exact: true })
    .fill("Gather reusable supplies");
  await page
    .getByRole("button", { name: "Remove suggestion 3", exact: true })
    .click();
  await expect(
    page.getByLabel("Suggestion 3 of 3", { exact: true }),
  ).toBeHidden();
  await page
    .getByRole("button", { name: "Use these suggestions", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Confirm plan", exact: true }),
  ).toBeVisible();
  await expectTodos(account, []);

  await page.getByRole("button", { name: "Confirm plan", exact: true }).click();
  await page
    .getByRole("button", { name: "Back to todos", exact: true })
    .click();
  const expected: TodoRow[] = [
    { title: "Gather reusable supplies", completed: false },
    { title: "Prepare workspace", completed: false },
  ];
  await expectTodos(account, expected);
  await expect(
    page.getByRole("checkbox", {
      name: "Gather reusable supplies",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("checkbox", { name: "Prepare workspace", exact: true }),
  ).toBeVisible();
  expect(agentStreams.length).toBeGreaterThan(0);

  await signOut(page, ["Gather reusable supplies", "Prepare workspace"]);
});
