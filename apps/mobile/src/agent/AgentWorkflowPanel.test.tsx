import * as mockReact from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import {
  AGENT_TRIGGER_TEXT,
  ClarifyPlanCardView,
  ReviewSuggestionsCardView,
  isAnswerValid,
  parseClarifyArgs,
  parseReviewArgs,
} from "./AgentWorkflowPanel";
import { isWorkflowSuggestionClarification } from "../todos/todoApi";
import type {
  KnownTodoWorkflow,
  WorkflowSuggestion,
} from "../todos/todoApi";

const mockInputFocus = jest.fn();
const mockAnnounceForAccessibility = jest.fn();
const mockSetAccessibilityFocus = jest.fn();
const mockFindNodeHandle = jest.fn(() => 123);

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const TestTextInput = mockReact.forwardRef(
    (
      props: Record<string, unknown>,
      ref: mockReact.Ref<{ focus: () => void; blur: () => void }>,
    ) => {
      mockReact.useImperativeHandle(
        ref,
        () => ({ focus: mockInputFocus, blur: jest.fn() }),
        [],
      );
      return mockReact.createElement(actual.TextInput, props);
    },
  );
  TestTextInput.displayName = "TestTextInput";
  return new Proxy(actual, {
    get(target, property, receiver) {
      if (property === "TextInput") return TestTextInput;
      if (property === "AccessibilityInfo") {
        return {
          ...actual.AccessibilityInfo,
          announceForAccessibility: mockAnnounceForAccessibility,
          setAccessibilityFocus: mockSetAccessibilityFocus,
        };
      }
      if (property === "findNodeHandle") return mockFindNodeHandle;
      return Reflect.get(target, property, receiver);
    },
  });
});

const WORKFLOW_ID = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const REQUEST_ID = "30bfb542-17f1-48a0-9fd8-3930379d5974";
const TOOL_CALL_ID = "11111111-1111-4111-8111-111111111111:clarify_plan:0";

const collectWorkflow: KnownTodoWorkflow = {
  workflow_id: WORKFLOW_ID,
  revision: 2,
  definition_version: 1,
  view_contract_version: 1,
  state: "COLLECT_TASKS",
  title: "Plan birthday party",
  context: { involves_multiple_steps: true, proposed_todo_titles: [] },
  result: null,
  view: {
    type: "task_breakdown",
    step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
    title: "Break it into smaller todos",
    min_titles: 2,
    max_titles: 10,
  },
};

const readySuggestion: WorkflowSuggestion = {
  contract_version: 1,
  workflow_id: WORKFLOW_ID,
  request_id: REQUEST_ID,
  base_revision: 2,
  step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  status: "ready",
  proposed_titles: ["Choose a date", "Invite guests"],
  error_code: null,
};

const clarifyArgsText = JSON.stringify({
  contract_version: 1,
  workflow_id: WORKFLOW_ID,
  expected_revision: 2,
  step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  field: "date",
});

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
};

describe("agent tool argument parsers", () => {
  it("parses exact version-1 clarify arguments", () => {
    expect(parseClarifyArgs(clarifyArgsText)).toEqual({
      contract_version: 1,
      workflow_id: WORKFLOW_ID,
      expected_revision: 2,
      step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
      field: "date",
    });
  });

  it.each([
    ["partial stream", '{"contract_version":1,"workflow_id":'],
    ["empty", ""],
    ["not json", "hello"],
    ["array", "[]"],
    ["wrong version", JSON.stringify({ contract_version: 2, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", field: "date" })],
    ["extra key", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", field: "date", schema: "http://evil" })],
    ["missing field", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s" })],
    ["unknown field", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", field: "weather" })],
    ["non-uuid workflow", JSON.stringify({ contract_version: 1, workflow_id: "main", expected_revision: 2, step_id: "s", field: "date" })],
    ["boolean revision", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: true, step_id: "s", field: "date" })],
  ])("rejects clarify arguments with %s", (_label, argsText) => {
    expect(parseClarifyArgs(argsText)).toBeNull();
  });

  it("parses exact version-1 review arguments with titles", () => {
    const argsText = JSON.stringify({
      contract_version: 1,
      workflow_id: WORKFLOW_ID,
      expected_revision: 2,
      step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
      suggestion_request_id: REQUEST_ID,
      titles: ["Choose a date", "Invite guests"],
    });
    expect(parseReviewArgs(argsText)).toEqual({
      contract_version: 1,
      workflow_id: WORKFLOW_ID,
      expected_revision: 2,
      step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
      suggestion_request_id: REQUEST_ID,
      titles: ["Choose a date", "Invite guests"],
    });
  });

  it.each([
    ["partial stream", '{"contract_version":1,"titles":'],
    ["one title", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", suggestion_request_id: REQUEST_ID, titles: ["Only"] })],
    ["eleven titles", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", suggestion_request_id: REQUEST_ID, titles: Array.from({ length: 11 }, (_, i) => `Title ${i}`) })],
    ["blank title", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", suggestion_request_id: REQUEST_ID, titles: ["Fine title", "   "] })],
    ["extra key", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", suggestion_request_id: REQUEST_ID, titles: ["A fine title", "Another fine title"], action: "confirm" })],
    ["wrong version", JSON.stringify({ contract_version: 7, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", suggestion_request_id: REQUEST_ID, titles: ["A fine title", "Another fine title"] })],
    ["non-uuid request", JSON.stringify({ contract_version: 1, workflow_id: WORKFLOW_ID, expected_revision: 2, step_id: "s", suggestion_request_id: "nope", titles: ["A fine title", "Another fine title"] })],
  ])("rejects review arguments with %s", (_label, argsText) => {
    expect(parseReviewArgs(argsText)).toBeNull();
  });

  it.each([
    ["simple answer", "next Saturday", true],
    ["single character", "a", true],
    ["boundary length", "x".repeat(200), true],
    ["padded boundary", `  ${"x".repeat(200)}  `, true],
    ["empty", "", false],
    ["blank", "   ", false],
    ["oversize", "x".repeat(201), false],
    ["embedded NUL", "ab\0cd", false],
    ["leading NUL", "\0next Saturday", false],
  ])("validates answers (%s)", (_label, value, valid) => {
    expect(isAnswerValid(value)).toBe(valid);
  });

  it.each([
    "next Saturday",
    "a",
    "x".repeat(200),
    `  ${"x".repeat(200)}  `,
    "caf\u00e9 \uD83C\uDF82 party",
    "\u00e9".repeat(200),
  ])("every UI-valid answer is pending-store-valid (%s)", (value) => {
    expect(isAnswerValid(value)).toBe(true);
    expect(
      isWorkflowSuggestionClarification({ field: "date", value }),
    ).toBe(true);
  });

  it.each(["ab\0cd", "", "   ", "x".repeat(201)])(
    "every UI-invalid answer is pending-store-invalid (%s)",
    (value) => {
      expect(isAnswerValid(value)).toBe(false);
      expect(
        isWorkflowSuggestionClarification({ field: "date", value }),
      ).toBe(false);
    },
  );

  it("exposes a fixed trigger message for new runs", () => {
    expect(typeof AGENT_TRIGGER_TEXT).toBe("string");
    expect(AGENT_TRIGGER_TEXT.trim().length).toBeGreaterThan(0);
  });
});

async function renderClarifyCard(overrides: {
  argsText?: string;
  resolved?: boolean;
  loading?: boolean;
  interrupted?: boolean;
  workflow?: KnownTodoWorkflow;
  submitAnswer?: jest.Mock;
  setAgentState?: jest.Mock;
  addToolResult?: jest.Mock;
  sessionEpoch?: number;
  isSessionCurrent?: (epoch: number) => boolean;
  requestId?: string;
}) {
  const submitAnswer =
    overrides.submitAnswer ??
    jest.fn(async (): Promise<WorkflowSuggestion> => readySuggestion);
  const setAgentState = overrides.setAgentState ?? jest.fn();
  const addToolResult = overrides.addToolResult ?? jest.fn();
  const args = parseClarifyArgs(overrides.argsText ?? clarifyArgsText);
  const view = await render(
    <ClarifyPlanCardView
      toolCallId={TOOL_CALL_ID}
      args={args}
      resolved={overrides.resolved ?? false}
      loading={overrides.loading ?? false}
      interrupted={overrides.interrupted ?? false}
      workflow={overrides.workflow ?? collectWorkflow}
      submitAnswer={submitAnswer}
      setAgentState={setAgentState}
      addToolResult={addToolResult}
      generateRequestId={() => overrides.requestId ?? REQUEST_ID}
      sessionEpoch={overrides.sessionEpoch ?? 1}
      isSessionCurrent={overrides.isSessionCurrent ?? (() => true)}
    />,
  );
  return { view, submitAnswer, setAgentState, addToolResult };
}

describe("ClarifyPlanCardView", () => {
  it("renders fixed catalog copy with a labeled answer field", async () => {
    await renderClarifyCard({});
    expect(screen.getByText("When does this need to happen?")).toBeTruthy();
    expect(screen.getByLabelText("Your answer")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
  });

  it("submits once: save, then setAgentState, then addToolResult with the same id", async () => {
    const setAgentState = jest.fn();
    const addToolResult = jest.fn();
    const order: string[] = [];
    setAgentState.mockImplementation(() => void order.push("setAgentState"));
    addToolResult.mockImplementation(() => void order.push("addToolResult"));
    const submitAnswer = jest.fn(async () => {
      order.push("submitAnswer");
      return readySuggestion;
    });
    await renderClarifyCard({ submitAnswer, setAgentState, addToolResult });

    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(submitAnswer).toHaveBeenCalledTimes(1));
    expect(submitAnswer).toHaveBeenCalledWith("date", "next Saturday", REQUEST_ID);
    await waitFor(() => expect(addToolResult).toHaveBeenCalledTimes(1));
    expect(order).toEqual(["submitAnswer", "setAgentState", "addToolResult"]);
    expect(setAgentState).toHaveBeenCalledWith({
      contract_version: 1,
      expected_revision: 2,
      step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
      suggestion_request_id: REQUEST_ID,
    });
    expect(addToolResult).toHaveBeenCalledWith({
      contract_version: 1,
      suggestion_request_id: REQUEST_ID,
    });
  });

  it("disables Continue for invalid answers and never submits", async () => {
    const submitAnswer = jest.fn();
    await renderClarifyCard({ submitAnswer });
    const button = screen.getByRole("button", { name: "Continue" });
    expect(button.props.accessibilityState?.disabled).toBe(true);
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "x".repeat(201));
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    expect(submitAnswer).not.toHaveBeenCalled();
  });

  it("retains the saved request and sends nothing on uncertain failure", async () => {
    const setAgentState = jest.fn();
    const addToolResult = jest.fn();
    const gate = deferred<WorkflowSuggestion>();
    await renderClarifyCard({
      submitAnswer: jest.fn(() => gate.promise),
      setAgentState,
      addToolResult,
      requestId: REQUEST_ID,
    });

    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy());
    gate.reject(new Error("Could not suggest todos."));
    await waitFor(() =>
      expect(screen.getByText("The answer is saved. Retry or discard the saved request.")).toBeTruthy(),
    );
    expect(setAgentState).not.toHaveBeenCalled();
    expect(addToolResult).not.toHaveBeenCalled();
  });

  it("omits a late result after sign-out", async () => {
    const setAgentState = jest.fn();
    const addToolResult = jest.fn();
    const gate = deferred<WorkflowSuggestion>();
    const { view } = await renderClarifyCard({
      submitAnswer: jest.fn(() => gate.promise),
      setAgentState,
      addToolResult,
      sessionEpoch: 1,
      isSessionCurrent: (epoch) => epoch === 2,
    });

    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    gate.resolve(readySuggestion);
    await waitFor(() => expect(setAgentState).not.toHaveBeenCalled());
    await view.unmount();
    expect(addToolResult).not.toHaveBeenCalled();
  });

  it("renders stale recovery without calling the API when the plan moved on", async () => {
    const submitAnswer = jest.fn();
    const movedOn: KnownTodoWorkflow = {
      ...collectWorkflow,
      revision: 3,
      state: "REVIEW",
      view: {
        type: "review",
        step_id: `${WORKFLOW_ID}:REVIEW`,
        title: "Review your plan",
        proposed_titles: ["Send invitations", "Buy decorations"],
      },
    };
    await renderClarifyCard({ submitAnswer, workflow: movedOn });
    expect(screen.getByText("This question is for an older plan. Reload to continue.")).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    expect(submitAnswer).not.toHaveBeenCalled();
  });

  it("shows a resolved state and never resubmits for a replayed tool", async () => {
    const submitAnswer = jest.fn();
    const addToolResult = jest.fn();
    await renderClarifyCard({ submitAnswer, addToolResult, resolved: true });
    expect(screen.getByText("Answer sent. Suggestions are on the way.")).toBeTruthy();
    expect(addToolResult).not.toHaveBeenCalled();
    expect(submitAnswer).not.toHaveBeenCalled();
  });

  it("announces loading while arguments stream and recovery after interruption", async () => {
    const first = await renderClarifyCard({ argsText: '{"contract_version":1', loading: true });
    expect(screen.getByText("Loading the agent question…")).toBeTruthy();
    await first.view.unmount();
    await renderClarifyCard({ argsText: '{"contract_version":1', interrupted: true });
    expect(screen.getByText("The agent response was interrupted. Try agent again.")).toBeTruthy();
  });
});

const REVIEW_TOOL_CALL_ID = "22222222-2222-4222-8222-222222222222:review_todo_suggestions:0";

const reviewWorkflow: KnownTodoWorkflow = {
  workflow_id: WORKFLOW_ID,
  revision: 3,
  definition_version: 1,
  view_contract_version: 1,
  state: "REVIEW",
  title: "Plan birthday party",
  context: {
    involves_multiple_steps: true,
    proposed_todo_titles: ["Choose a date", "Invite guests"],
  },
  result: null,
  view: {
    type: "review",
    step_id: `${WORKFLOW_ID}:REVIEW`,
    title: "Review your plan",
    proposed_titles: ["Choose a date", "Invite guests"],
  },
};

const reviewArgsText = JSON.stringify({
  contract_version: 1,
  workflow_id: WORKFLOW_ID,
  expected_revision: 2,
  step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  suggestion_request_id: REQUEST_ID,
  titles: ["Choose a date", "Invite guests"],
});

async function renderReviewCard(overrides: {
  argsText?: string;
  resolved?: boolean;
  loading?: boolean;
  interrupted?: boolean;
  workflow?: KnownTodoWorkflow;
  submitTitles?: jest.Mock;
  setAgentState?: jest.Mock;
  addToolResult?: jest.Mock;
  sessionEpoch?: number;
  isSessionCurrent?: (epoch: number) => boolean;
}) {
  const submitTitles =
    overrides.submitTitles ?? jest.fn(async () => reviewWorkflow);
  const setAgentState = overrides.setAgentState ?? jest.fn();
  const addToolResult = overrides.addToolResult ?? jest.fn();
  const args = parseReviewArgs(overrides.argsText ?? reviewArgsText);
  const view = await render(
    <ReviewSuggestionsCardView
      toolCallId={REVIEW_TOOL_CALL_ID}
      args={args}
      resolved={overrides.resolved ?? false}
      loading={overrides.loading ?? false}
      interrupted={overrides.interrupted ?? false}
      workflow={overrides.workflow ?? collectWorkflow}
      submitTitles={submitTitles}
      setAgentState={setAgentState}
      addToolResult={addToolResult}
      sessionEpoch={overrides.sessionEpoch ?? 1}
      isSessionCurrent={overrides.isSessionCurrent ?? (() => true)}
    />,
  );
  return { view, submitTitles, setAgentState, addToolResult };
}

describe("ReviewSuggestionsCardView", () => {
  it("renders an editable checklist with removal and a submit action", async () => {
    await renderReviewCard({});
    expect(screen.getByText("Review suggested todos")).toBeTruthy();
    expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy();
    expect(screen.getByLabelText("Suggestion 2 of 2")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use these suggestions" })).toBeTruthy();
  });

  it("edits titles and removes extras, keeping at least two", async () => {
    await renderReviewCard({
      argsText: JSON.stringify({
        contract_version: 1,
        workflow_id: WORKFLOW_ID,
        expected_revision: 2,
        step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
        suggestion_request_id: REQUEST_ID,
        titles: ["Choose a date", "Invite guests", "Book a venue"],
      }),
    });
    await fireEvent.changeText(screen.getByLabelText("Suggestion 1 of 3"), "Pick a date");
    expect(screen.getByLabelText("Suggestion 1 of 3").props.value).toBe("Pick a date");
    await fireEvent.press(screen.getByRole("button", { name: "Remove suggestion 3" }));
    expect(screen.queryByLabelText("Suggestion 3 of 3")).toBeNull();
    expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy();
  });

  it("submits edited titles: advance, then REVIEW state, then review result", async () => {
    const setAgentState = jest.fn();
    const addToolResult = jest.fn();
    const order: string[] = [];
    setAgentState.mockImplementation(() => void order.push("setAgentState"));
    addToolResult.mockImplementation(() => void order.push("addToolResult"));
    const submitTitles = jest.fn(async () => {
      order.push("submitTitles");
      return reviewWorkflow;
    });
    await renderReviewCard({ submitTitles, setAgentState, addToolResult });

    await fireEvent.changeText(screen.getByLabelText("Suggestion 1 of 2"), "Pick a date");
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));

    await waitFor(() => expect(submitTitles).toHaveBeenCalledTimes(1));
    expect(submitTitles).toHaveBeenCalledWith(
      ["Pick a date", "Invite guests"],
      REQUEST_ID,
    );
    await waitFor(() => expect(addToolResult).toHaveBeenCalledTimes(1));
    expect(order).toEqual(["submitTitles", "setAgentState", "addToolResult"]);
    expect(setAgentState).toHaveBeenCalledWith({
      contract_version: 1,
      expected_revision: 3,
      step_id: `${WORKFLOW_ID}:REVIEW`,
      suggestion_request_id: REQUEST_ID,
    });
    expect(addToolResult).toHaveBeenCalledWith({
      contract_version: 1,
      request_id: REQUEST_ID,
      accepted_revision: 3,
    });
  });

  it("disables submit for invalid titles and never submits", async () => {
    const submitTitles = jest.fn();
    await renderReviewCard({ submitTitles });
    await fireEvent.changeText(screen.getByLabelText("Suggestion 1 of 2"), "   ");
    const button = screen.getByRole("button", { name: "Use these suggestions" });
    expect(button.props.accessibilityState?.disabled).toBe(true);
    await fireEvent.press(button);
    expect(submitTitles).not.toHaveBeenCalled();
    expect(screen.getByText("Keep 2 to 10 valid todo titles.")).toBeTruthy();
  });

  it("renders stale recovery without submitting when the plan moved on", async () => {
    const submitTitles = jest.fn();
    await renderReviewCard({ submitTitles, workflow: reviewWorkflow });
    expect(
      screen.getByText("These suggestions are for an older plan. Reload to continue."),
    ).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));
    expect(submitTitles).not.toHaveBeenCalled();
  });

  it("retains the saved request and sends no result on uncertain failure", async () => {
    const setAgentState = jest.fn();
    const addToolResult = jest.fn();
    const gate = deferred<WorkflowSuggestion>();
    await renderReviewCard({
      submitTitles: jest.fn(() => gate.promise.then(() => reviewWorkflow)),
      setAgentState,
      addToolResult,
    });
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));
    gate.reject(new Error("Could not submit todos."));
    await waitFor(() =>
      expect(
        screen.getByText("The suggestions are saved. Retry or discard the saved request."),
      ).toBeTruthy(),
    );
    expect(setAgentState).not.toHaveBeenCalled();
    expect(addToolResult).not.toHaveBeenCalled();
  });

  it("omits a late result after unmount", async () => {
    const setAgentState = jest.fn();
    const addToolResult = jest.fn();
    const gate = deferred<WorkflowSuggestion>();
    const { view } = await renderReviewCard({
      submitTitles: jest.fn(() => gate.promise.then(() => reviewWorkflow)),
      setAgentState,
      addToolResult,
    });
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));
    await view.unmount();
    gate.resolve(readySuggestion);
    expect(setAgentState).not.toHaveBeenCalled();
    expect(addToolResult).not.toHaveBeenCalled();
  });

  it("shows a resolved state and never resubmits for a replayed tool", async () => {
    const submitTitles = jest.fn();
    const addToolResult = jest.fn();
    await renderReviewCard({ submitTitles, addToolResult, resolved: true });
    expect(
      screen.getByText("Suggestions submitted. Review your plan to confirm."),
    ).toBeTruthy();
    expect(submitTitles).not.toHaveBeenCalled();
    expect(addToolResult).not.toHaveBeenCalled();
  });

  it("announces loading while arguments stream and recovery after interruption", async () => {
    const first = await renderReviewCard({ argsText: '{"contract_version":1', loading: true });
    expect(screen.getByText("Loading suggested todos…")).toBeTruthy();
    await first.view.unmount();
    await renderReviewCard({ argsText: '{"contract_version":1', interrupted: true });
    expect(screen.getByText("The agent response was interrupted. Try agent again.")).toBeTruthy();
  });

  it("rejects unusable review arguments with manual fallback", async () => {
    await renderReviewCard({
      argsText: JSON.stringify({
        contract_version: 1,
        workflow_id: WORKFLOW_ID,
        expected_revision: 2,
        step_id: "s",
        suggestion_request_id: REQUEST_ID,
        titles: ["Only one"],
      }),
    });
    expect(
      screen.getByText("The agent sent suggestions this app cannot use. Continue manually below."),
    ).toBeTruthy();
  });
});

describe("agent card focus movement", () => {
  beforeEach(() => {
    mockInputFocus.mockClear();
    mockAnnounceForAccessibility.mockClear();
    mockSetAccessibilityFocus.mockClear();
    mockFindNodeHandle.mockClear();
  });

  it("focuses the answer input once when the clarify form arrives", async () => {
    await renderClarifyCard({});
    await waitFor(() => expect(mockInputFocus).toHaveBeenCalledTimes(1));
    expect(mockSetAccessibilityFocus).toHaveBeenCalledWith(123);
    expect(mockAnnounceForAccessibility).toHaveBeenCalledWith(
      "When does this need to happen?",
    );
  });

  it("does not move focus for a stale card", async () => {
    const movedOn: KnownTodoWorkflow = {
      ...collectWorkflow,
      revision: 3,
      state: "REVIEW",
      view: {
        type: "review",
        step_id: `${WORKFLOW_ID}:REVIEW`,
        title: "Review your plan",
        proposed_titles: ["Send invitations", "Buy decorations"],
      },
    };
    await renderClarifyCard({ workflow: movedOn });
    expect(
      screen.getByText("This question is for an older plan. Reload to continue."),
    ).toBeTruthy();
    expect(mockInputFocus).not.toHaveBeenCalled();
    expect(mockSetAccessibilityFocus).not.toHaveBeenCalled();
  });

  it("focuses the first title input once when the review checklist arrives", async () => {
    await renderReviewCard({});
    await waitFor(() => expect(mockInputFocus).toHaveBeenCalledTimes(1));
    expect(mockSetAccessibilityFocus).toHaveBeenCalledWith(123);
  });

  it("announces completion when the answer is sent", async () => {
    await renderClarifyCard({});
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    mockSetAccessibilityFocus.mockClear();
    mockInputFocus.mockClear();
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(mockAnnounceForAccessibility).toHaveBeenCalledWith(
        "Answer sent. Suggestions are on the way.",
      ),
    );
    // The actionable form is removed: focus moves to the resolved status.
    await waitFor(() => expect(mockSetAccessibilityFocus).toHaveBeenCalledWith(123));
  });

  it("announces completion when suggestions are submitted", async () => {
    await renderReviewCard({});
    mockSetAccessibilityFocus.mockClear();
    mockInputFocus.mockClear();
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));
    await waitFor(() =>
      expect(mockAnnounceForAccessibility).toHaveBeenCalledWith(
        "Suggestions submitted. Review your plan to confirm.",
      ),
    );
    // The editable checklist is removed: focus moves to the resolved status.
    await waitFor(() => expect(mockSetAccessibilityFocus).toHaveBeenCalledWith(123));
  });
});

describe("agent card accessibility contracts", () => {
  it("exposes polite live regions on async card states", async () => {
    const { view } = await renderReviewCard({
      argsText: '{"contract_version":1',
      loading: true,
    });
    expect(screen.getByText("Loading suggested todos…").props.accessibilityLiveRegion).toBe(
      "polite",
    );
    await view.unmount();
  });

  it("marks disabled actions through accessibilityState", async () => {
    await renderClarifyCard({});
    expect(
      screen.getByRole("button", { name: "Continue" }).props.accessibilityState?.disabled,
    ).toBe(true);
  });

  it("keeps touch targets at 44 points or larger", async () => {
    const { StyleSheet } = require("react-native");
    await renderClarifyCard({});
    const continueStyle = StyleSheet.flatten(
      screen.getByRole("button", { name: "Continue" }).props.style,
    );
    expect(continueStyle.minHeight).toBeGreaterThanOrEqual(44);
    expect(continueStyle.minWidth).toBeGreaterThanOrEqual(44);
    const answerStyle = StyleSheet.flatten(screen.getByLabelText("Your answer").props.style);
    expect(answerStyle.minHeight).toBeGreaterThanOrEqual(44);
    const { view } = await renderReviewCard({});
    await view.unmount();
  });

  it("keeps secondary controls and editable rows at 44 points or larger", async () => {
    const { StyleSheet } = require("react-native");
    await renderReviewCard({});
    const removeStyle = StyleSheet.flatten(
      screen.getByRole("button", { name: "Remove suggestion 1" }).props.style,
    );
    expect(removeStyle.minHeight).toBeGreaterThanOrEqual(44);
    expect(removeStyle.minWidth).toBeGreaterThanOrEqual(44);
    const rowStyle = StyleSheet.flatten(
      screen.getByLabelText("Suggestion 1 of 2").props.style,
    );
    expect(rowStyle.minHeight).toBeGreaterThanOrEqual(44);
    const submitStyle = StyleSheet.flatten(
      screen.getByRole("button", { name: "Use these suggestions" }).props.style,
    );
    expect(submitStyle.minHeight).toBeGreaterThanOrEqual(44);
  });
});

/* ---- Full-panel integration: real runtime against a server-emulating fixture ---- */

import { AgentSessionProvider } from "./AgentSessionProvider";
import {
  AgentRuntimeProvider,
  type AgentState,
} from "./AgentRuntimeProvider";
import { AgentWorkflowPanel } from "./AgentWorkflowPanel";
import { TodoApiError } from "../todos/todoApi";
import type { ClarificationField } from "../todos/todoApi";

const API_URL = "https://api.example.test";

const sse = (events: unknown[]): string =>
  events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");

const sseResponse = (events: unknown[]): Response =>
  new Response(sse(events), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });

type ReadyEntry = {
  requestId: string;
  base_revision: number;
  step_id: string;
  titles: string[];
};

type AgentPost = {
  threadId: string;
  runId: string;
  state: AgentState | null;
  messages: Array<{
    role: string;
    content?: unknown;
    toolCalls?: Array<{ id: string; function?: { name?: string; arguments?: string } }>;
    toolCallId?: string;
  }>;
};

const runStarted = (post: AgentPost) => ({
  type: "RUN_STARTED",
  threadId: post.threadId,
  runId: post.runId,
});
const runFinished = (post: AgentPost) => ({
  type: "RUN_FINISHED",
  threadId: post.threadId,
  runId: post.runId,
});
const runError = () => ({
  type: "RUN_ERROR",
  message: "The agent request was invalid. Restart the conversation or continue manually.",
  code: "invalid_request",
});

const clarifyEvents = (post: AgentPost, field = "date") => {
  const toolCallId = `${post.runId}:clarify_plan:0`;
  return [
    runStarted(post),
    { type: "TOOL_CALL_START", toolCallId, toolCallName: "clarify_plan" },
    {
      type: "TOOL_CALL_ARGS",
      toolCallId,
      delta: JSON.stringify({
        contract_version: 1,
        workflow_id: WORKFLOW_ID,
        expected_revision: post.state?.expected_revision ?? 2,
        step_id: post.state?.step_id ?? `${WORKFLOW_ID}:COLLECT_TASKS`,
        field,
      }),
    },
    { type: "TOOL_CALL_END", toolCallId },
    runFinished(post),
  ];
};

const reviewEvents = (post: AgentPost, entry: ReadyEntry) => {
  const toolCallId = `${post.runId}:review_todo_suggestions:0`;
  return [
    runStarted(post),
    { type: "TOOL_CALL_START", toolCallId, toolCallName: "review_todo_suggestions" },
    {
      type: "TOOL_CALL_ARGS",
      toolCallId,
      delta: JSON.stringify({
        contract_version: 1,
        workflow_id: WORKFLOW_ID,
        expected_revision: post.state?.expected_revision ?? 2,
        step_id: post.state?.step_id ?? `${WORKFLOW_ID}:COLLECT_TASKS`,
        suggestion_request_id: entry.requestId,
        titles: entry.titles,
      }),
    },
    { type: "TOOL_CALL_END", toolCallId },
    runFinished(post),
  ];
};

/** Mirrors the Python agent branches: state-first ready check, REVIEW ack
 *  against submitted titles, clarify-continuation replay, fresh choice. */
function makeAgentFetch(options: {
  ready: ReadyEntry[];
  bodies: AgentPost[];
  onCall?: (index: number) => unknown[] | null;
  outcomes?: string[];
}) {
  return jest.fn(async (_url: unknown, init?: RequestInit) => {
    const post = JSON.parse(String(init?.body)) as AgentPost;
    options.bodies.push(post);
    const index = options.bodies.length - 1;
    const override = options.onCall?.(index);
    if (override !== undefined && override !== null) return sseResponse(override);
    const state = post.state;
    const toolMessages = post.messages.filter((m) => m.role === "tool");
    const lastTool = toolMessages[toolMessages.length - 1];
    const preceding =
      lastTool !== undefined
        ? post.messages[post.messages.lastIndexOf(lastTool) - 1]
        : undefined;
    const matchReady = (id: string) =>
      options.ready.find(
        (r) =>
          r.requestId === id &&
          r.base_revision === state?.expected_revision &&
          r.step_id === state?.step_id,
      );
    if (state !== null && typeof state.suggestion_request_id === "string") {
      if (state.step_id.endsWith(":REVIEW")) {
        const call = preceding?.toolCalls?.find((c) => c.id === lastTool?.toolCallId);
        if (
          preceding?.role === "assistant" &&
          call?.function?.name === "review_todo_suggestions" &&
          lastTool !== undefined
        ) {
          try {
            const result = JSON.parse(String(lastTool.content));
            const callArgs = JSON.parse(String(call.function?.arguments ?? "{}"));
            // Fixed server rule: the call replays the saved pre-submit
            // proposal, not the edited REVIEW snapshot.
            const saved = options.ready.find(
              (r) => r.requestId === String(result.request_id),
            );
            if (
              result.contract_version === 1 &&
              result.accepted_revision === state.expected_revision &&
              String(callArgs.suggestion_request_id) === String(result.request_id) &&
              saved !== undefined &&
              JSON.stringify(callArgs.titles) === JSON.stringify(saved.titles)
            ) {
              options.outcomes?.push("ack");
              return sseResponse([runStarted(post), runFinished(post)]);
            }
          } catch {
            /* fall through to error */
          }
        }
        options.outcomes?.push("review-error");
        return sseResponse([runStarted(post), runError()]);
      }
      const entry = matchReady(state.suggestion_request_id);
      if (entry) return sseResponse(reviewEvents(post, entry));
      return sseResponse([runStarted(post), runError()]);
    }
    if (lastTool !== undefined && preceding?.role === "assistant") {
      const call = preceding.toolCalls?.find((c) => c.id === lastTool.toolCallId);
      if (call?.function?.name === "clarify_plan") {
        try {
          const result = JSON.parse(String(lastTool.content));
          const entry = matchReady(String(result.suggestion_request_id));
          if (
            result.contract_version === 1 &&
            entry !== undefined
          ) {
            return sseResponse(reviewEvents(post, entry));
          }
        } catch {
          /* fall through to error */
        }
        return sseResponse([runStarted(post), runError()]);
      }
      return sseResponse([runStarted(post), runError()]);
    }
    return sseResponse(clarifyEvents(post));
  });
}

function notFound(): Promise<never> {
  return Promise.reject(
    new TodoApiError("not-found", "That plan has no saved todo suggestions."),
  );
}

// Stable fixture token getter: one shared closure so session identity is
// constant across renders and rerenders in these panel tests.
const panelGetToken = () => "tok";

async function renderPanelHarness(overrides: {
  workflow?: KnownTodoWorkflow;
  getSuggestion?: jest.Mock;
  submitAgentSuggestion?: jest.Mock;
  submitAgentTasks?: jest.Mock;
  generateRequestId?: jest.Mock;
  sessionEpoch?: number;
  isSessionCurrent?: (epoch: number) => boolean;
  dataReady?: boolean;
  onBusyChange?: jest.Mock;
  onReadyChange?: jest.Mock;
  initialState?: AgentState;
}) {
  const getSuggestion = overrides.getSuggestion ?? jest.fn(() => notFound());
  const submitAgentSuggestion =
    overrides.submitAgentSuggestion ??
    jest.fn(async (_field: ClarificationField, _value: string, requestId: string) => ({
      ...readySuggestion,
      request_id: requestId,
    }));
  const submitAgentTasks =
    overrides.submitAgentTasks ?? jest.fn(async () => reviewWorkflow);
  const generateRequestId = overrides.generateRequestId ?? jest.fn(() => REQUEST_ID);
  const onBusyChange = overrides.onBusyChange ?? jest.fn();
  const onReadyChange = overrides.onReadyChange;
  const workflow = overrides.workflow ?? collectWorkflow;
  const view = await render(
    <AgentSessionProvider getToken={panelGetToken} sessionEpoch={overrides.sessionEpoch ?? 1}>
      <AgentRuntimeProvider
        workflowId={workflow.workflow_id}
        initialState={
          overrides.initialState ?? {
            contract_version: 1,
            expected_revision: workflow.revision,
            step_id: workflow.view.step_id,
            suggestion_request_id: null,
          }
        }
      >
        <AgentWorkflowPanel
          userId="9a4b3c2d-1e2f-4a5b-8c6d-7e8f9a0b1c2d"
          workflow={workflow}
          api={{ getSuggestion }}
          generateRequestId={generateRequestId}
          sessionEpoch={overrides.sessionEpoch ?? 1}
          isSessionCurrent={overrides.isSessionCurrent ?? (() => true)}
          submitAgentSuggestion={submitAgentSuggestion}
          submitAgentTasks={submitAgentTasks}
          dataReady={overrides.dataReady ?? true}
          onBusyChange={onBusyChange}
          onReadyChange={onReadyChange}
        />
      </AgentRuntimeProvider>
    </AgentSessionProvider>,
  );
  return {
    view,
    getSuggestion,
    submitAgentSuggestion,
    submitAgentTasks,
    generateRequestId,
    onBusyChange,
    onReadyChange,
  };
}

describe("AgentWorkflowPanel integration", () => {
  const realFetch = globalThis.fetch;
  const savedApiUrl = process.env.EXPO_PUBLIC_API_URL;
  beforeEach(() => {
    process.env.EXPO_PUBLIC_API_URL = API_URL;
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
    if (savedApiUrl === undefined) delete process.env.EXPO_PUBLIC_API_URL;
    else process.env.EXPO_PUBLIC_API_URL = savedApiUrl;
    jest.restoreAllMocks();
  });

  it("asks, answers, and replays review: POST bodies prove setState-before-addResult", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({
      ready: [
        {
          requestId: REQUEST_ID,
          base_revision: 2,
          step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
          titles: ["Choose a date", "Invite guests"],
        },
      ],
      bodies,
    }) as unknown as typeof fetch;
    const harness = await renderPanelHarness({});

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    expect(bodies).toHaveLength(1);
    expect(bodies[0].state?.suggestion_request_id).toBeNull();

    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));

    await waitFor(
      () => expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy(),
      { timeout: 10000 },
    );
    expect(harness.submitAgentSuggestion).toHaveBeenCalledTimes(1);
    expect(harness.submitAgentSuggestion).toHaveBeenCalledWith(
      "date",
      "next Saturday",
      REQUEST_ID,
    );
    await waitFor(() => expect(bodies).toHaveLength(2), { timeout: 10000 });
    // The automatic continuation observes the synchronously installed state.
    expect(bodies[1].state).toEqual({
      contract_version: 1,
      expected_revision: 2,
      step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
      suggestion_request_id: REQUEST_ID,
    });
    const toolContents = bodies[1].messages
      .filter((m) => m.role === "tool")
      .map((m) => String(m.content));
    expect(toolContents.some((c) => c.includes(REQUEST_ID))).toBe(true);
    // Exactly one continuation: no hidden retry loop.
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(bodies).toHaveLength(2);
  }, 30000);

  it("retains the saved request with no result and no new id on failure", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    const submitAgentSuggestion = jest.fn(async () => {
      throw new Error("Could not suggest todos.");
    });
    const generateRequestId = jest.fn(() => REQUEST_ID);
    await renderPanelHarness({ submitAgentSuggestion, generateRequestId });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(
        screen.getByText("The answer is saved. Retry or discard the saved request."),
      ).toBeTruthy(),
    );
    expect(bodies).toHaveLength(1);
    expect(generateRequestId).toHaveBeenCalledTimes(1);
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(bodies).toHaveLength(1);
  }, 30000);

  it("accepts unedited suggestions with a no-write REVIEW acknowledgement", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({
      ready: [
        {
          requestId: REQUEST_ID,
          base_revision: 2,
          step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
          titles: ["Choose a date", "Invite guests"],
        },
      ],
      bodies,
    }) as unknown as typeof fetch;
    const submitAgentTasks = jest.fn(async () => reviewWorkflow);
    const harness = await renderPanelHarness({ submitAgentTasks });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(
      () => expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy(),
      { timeout: 10000 },
    );
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));
    await waitFor(
      () =>
        expect(
          screen.getByText("Suggestions submitted. Review your plan to confirm."),
        ).toBeTruthy(),
      { timeout: 10000 },
    );
    expect(submitAgentTasks).toHaveBeenCalledTimes(1);
    expect(submitAgentTasks).toHaveBeenCalledWith(
      ["Choose a date", "Invite guests"],
      REQUEST_ID,
    );
    await waitFor(() => expect(bodies).toHaveLength(3), { timeout: 10000 });
    expect(bodies[2].state).toEqual({
      contract_version: 1,
      expected_revision: 3,
      step_id: `${WORKFLOW_ID}:REVIEW`,
      suggestion_request_id: REQUEST_ID,
    });
    const reviewResults = bodies[2].messages
      .filter((m) => m.role === "tool")
      .map((m) => String(m.content));
    expect(
      reviewResults.some(
        (c) => c.includes(REQUEST_ID) && c.includes('"accepted_revision":3'),
      ),
    ).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(bodies).toHaveLength(3);
    expect(harness.submitAgentSuggestion).toHaveBeenCalledTimes(1);
  }, 45000);

  it("accepts edited suggestions with a RUN_FINISHED ack against the saved proposal", async () => {
    const bodies: AgentPost[] = [];
    const outcomes: string[] = [];
    globalThis.fetch = makeAgentFetch({
      ready: [
        {
          requestId: REQUEST_ID,
          base_revision: 2,
          step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
          titles: ["Choose a date", "Invite guests"],
        },
      ],
      bodies,
      outcomes,
    }) as unknown as typeof fetch;
    const editedReview = {
      ...reviewWorkflow,
      context: {
        involves_multiple_steps: true,
        proposed_todo_titles: ["Pick a date", "Invite guests"],
      },
      view: {
        type: "review" as const,
        step_id: `${WORKFLOW_ID}:REVIEW`,
        title: "Review your plan",
        proposed_titles: ["Pick a date", "Invite guests"],
      },
    };
    const submitAgentTasks = jest.fn(async () => editedReview);
    const harness = await renderPanelHarness({ submitAgentTasks });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(
      () => expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy(),
      { timeout: 10000 },
    );
    await fireEvent.changeText(screen.getByLabelText("Suggestion 1 of 2"), "Pick a date");
    await fireEvent.press(screen.getByRole("button", { name: "Use these suggestions" }));
    await waitFor(
      () =>
        expect(
          screen.getByText("Suggestions submitted. Review your plan to confirm."),
        ).toBeTruthy(),
      { timeout: 10000 },
    );
    expect(submitAgentTasks).toHaveBeenCalledTimes(1);
    expect(submitAgentTasks).toHaveBeenCalledWith(
      ["Pick a date", "Invite guests"],
      REQUEST_ID,
    );
    // The ack compares the original call titles against the saved proposal,
    // not the edited snapshot: RUN_FINISHED with no write and no regen.
    await waitFor(() => expect(bodies).toHaveLength(3), { timeout: 10000 });
    expect(outcomes).toEqual(["ack"]);
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(bodies).toHaveLength(3);
    expect(harness.submitAgentSuggestion).toHaveBeenCalledTimes(1);
  }, 45000);

  it("recovers a ready proposal with no model call after reload", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({
      ready: [
        {
          requestId: REQUEST_ID,
          base_revision: 2,
          step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
          titles: ["Choose a date", "Invite guests"],
        },
      ],
      bodies,
    }) as unknown as typeof fetch;
    const getSuggestion = jest.fn(async () => readySuggestion);
    const submitAgentSuggestion = jest.fn();
    await renderPanelHarness({ getSuggestion, submitAgentSuggestion });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(
      () => expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy(),
      { timeout: 10000 },
    );
    expect(bodies).toHaveLength(1);
    expect(bodies[0].state?.suggestion_request_id).toBe(REQUEST_ID);
    expect(submitAgentSuggestion).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Your answer")).toBeNull();
  }, 30000);

  it("omits the late continuation when unmounted mid-submit", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    const gate = deferred<WorkflowSuggestion>();
    const harness = await renderPanelHarness({
      submitAgentSuggestion: jest.fn(() => gate.promise),
    });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(harness.submitAgentSuggestion).toHaveBeenCalledTimes(1));
    await harness.view.unmount();
    gate.resolve({ ...readySuggestion, request_id: REQUEST_ID });
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(bodies).toHaveLength(1);
  }, 30000);

  it("omits the late continuation after sign-out", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    let current = true;
    const gate = deferred<WorkflowSuggestion>();
    const harness = await renderPanelHarness({
      submitAgentSuggestion: jest.fn(() => gate.promise),
      isSessionCurrent: () => current,
    });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(harness.submitAgentSuggestion).toHaveBeenCalledTimes(1));
    current = false;
    gate.resolve({ ...readySuggestion, request_id: REQUEST_ID });
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(bodies).toHaveLength(1);
  }, 30000);

  it("restarts cleanly after remount with a new session epoch", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    const first = await renderPanelHarness({ sessionEpoch: 1 });
    await first.view.unmount();
    await renderPanelHarness({ sessionEpoch: 2 });
    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    expect(bodies).toHaveLength(1);
    expect(bodies[0].threadId).toBe(WORKFLOW_ID);
  }, 30000);

  it("recovers from an interrupted run with a fresh choice and no poisoned history", async () => {
    const bodies: AgentPost[] = [];
    let releaseFirst!: () => void;
    const firstGate = new Promise<Response>((resolve) => {
      releaseFirst = () =>
        resolve(
          sseResponse([
            {
              type: "RUN_STARTED",
              threadId: WORKFLOW_ID,
              runId: "99999999-9999-4999-8999-999999999999",
            },
          ]),
        );
    });
    let calls = 0;
    globalThis.fetch = jest.fn(async (_url: unknown, init?: RequestInit) => {
      calls += 1;
      if (calls === 1) {
        const signal = init?.signal;
        return new Promise<Response>((resolve, reject) => {
          if (signal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
          void firstGate.then(resolve);
        });
      }
      const post = JSON.parse(String(init?.body)) as AgentPost;
      bodies.push(post);
      return sseResponse(clarifyEvents(post));
    }) as unknown as typeof fetch;
    await renderPanelHarness({});

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(calls).toBe(1), { timeout: 10000 });
    // The cancel control itself guarantees a 44-point target while running.
    const { StyleSheet } = require("react-native");
    const cancelStyle = StyleSheet.flatten(screen.getByText("Cancel agent run").props.style);
    expect(cancelStyle.minHeight).toBeGreaterThanOrEqual(44);
    expect(cancelStyle.minWidth).toBeGreaterThanOrEqual(44);
    await fireEvent.press(screen.getByRole("button", { name: "Cancel agent run" }));
    releaseFirst();
    await waitFor(
      () => expect(screen.getByRole("button", { name: "Try agent again" })).toBeTruthy(),
      { timeout: 10000 },
    );
    await fireEvent.press(screen.getByRole("button", { name: "Try agent again" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    // The retry carries no poisoned tool result: the server branch is a fresh choice.
    const retryBody = bodies[bodies.length - 1];
    expect(
      retryBody.messages.some(
        (m) => m.role === "tool" && String(m.content).includes("error"),
      ),
    ).toBe(false);
  }, 45000);

  it("renders safe recovery for unknown tools and blocks a poisoned retry", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = jest.fn(async (_url: unknown, init?: RequestInit) => {
      const post = JSON.parse(String(init?.body)) as AgentPost;
      bodies.push(post);
      const toolCallId = `${post.runId}:do_anything:0`;
      return sseResponse([
        runStarted(post),
        { type: "TOOL_CALL_START", toolCallId, toolCallName: "do_anything" },
        { type: "TOOL_CALL_ARGS", toolCallId, delta: '{"plan":"anything"}' },
        { type: "TOOL_CALL_END", toolCallId },
        runFinished(post),
      ]);
    }) as unknown as typeof fetch;
    await renderPanelHarness({});

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(
      () =>
        expect(
          screen.getByText("The agent sent a response this app cannot use. Continue manually below."),
        ).toBeTruthy(),
      { timeout: 10000 },
    );
    const ask = screen.queryByRole("button", { name: "Try agent again" });
    expect(ask?.props.accessibilityState?.disabled).toBe(true);
    expect(bodies).toHaveLength(1);
  }, 30000);

  it("renders safe recovery for malformed arguments", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = jest.fn(async (_url: unknown, init?: RequestInit) => {
      const post = JSON.parse(String(init?.body)) as AgentPost;
      bodies.push(post);
      const toolCallId = `${post.runId}:clarify_plan:0`;
      return sseResponse([
        runStarted(post),
        { type: "TOOL_CALL_START", toolCallId, toolCallName: "clarify_plan" },
        { type: "TOOL_CALL_ARGS", toolCallId, delta: '{"contract_version":1,' },
        { type: "TOOL_CALL_END", toolCallId },
        runFinished(post),
      ]);
    }) as unknown as typeof fetch;
    await renderPanelHarness({});

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(
      () =>
        expect(
          screen.getByText("The agent sent a question this app cannot use. Continue manually below."),
        ).toBeTruthy(),
      { timeout: 10000 },
    );
    expect(screen.queryByLabelText("Your answer")).toBeNull();
  }, 30000);

  it("renders stale recovery for arguments from an older revision", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = jest.fn(async (_url: unknown, init?: RequestInit) => {
      const post = JSON.parse(String(init?.body)) as AgentPost;
      bodies.push(post);
      const toolCallId = `${post.runId}:clarify_plan:0`;
      return sseResponse([
        runStarted(post),
        { type: "TOOL_CALL_START", toolCallId, toolCallName: "clarify_plan" },
        {
          type: "TOOL_CALL_ARGS",
          toolCallId,
          delta: JSON.stringify({
            contract_version: 1,
            workflow_id: WORKFLOW_ID,
            expected_revision: 1,
            step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
            field: "date",
          }),
        },
        { type: "TOOL_CALL_END", toolCallId },
        runFinished(post),
      ]);
    }) as unknown as typeof fetch;
    const submitAgentSuggestion = jest.fn();
    await renderPanelHarness({ submitAgentSuggestion });

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(
      () =>
        expect(
          screen.getByText("This question is for an older plan. Reload to continue."),
        ).toBeTruthy(),
      { timeout: 10000 },
    );
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    expect(submitAgentSuggestion).not.toHaveBeenCalled();
  }, 30000);

  it("keeps the ask action disabled until plan data is ready", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    await renderPanelHarness({ dataReady: false });
    expect(
      screen.getByRole("button", { name: "Ask agent for help" }).props.accessibilityState
        ?.disabled,
    ).toBe(true);
    expect(bodies).toHaveLength(0);
  });

  it("renders nothing once the workflow leaves the breakdown step", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    await renderPanelHarness({ workflow: reviewWorkflow });
    expect(screen.queryByRole("button", { name: "Ask agent for help" })).toBeNull();
    expect(bodies).toHaveLength(0);
  });

  it("signals thread-UI readiness on mount and release on unmount", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({ ready: [], bodies }) as unknown as typeof fetch;
    const onReadyChange = jest.fn();
    const harness = await renderPanelHarness({ onReadyChange });
    await waitFor(() => expect(onReadyChange).toHaveBeenCalledWith(true));
    await harness.view.unmount();
    await waitFor(() => expect(onReadyChange).toHaveBeenCalledWith(false));
    expect(bodies).toHaveLength(0);
  });

  it("replays a resolved tool without resubmitting on rerender", async () => {
    const bodies: AgentPost[] = [];
    globalThis.fetch = makeAgentFetch({
      ready: [
        {
          requestId: REQUEST_ID,
          base_revision: 2,
          step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
          titles: ["Choose a date", "Invite guests"],
        },
      ],
      bodies,
    }) as unknown as typeof fetch;
    const harness = await renderPanelHarness({});

    await fireEvent.press(screen.getByRole("button", { name: "Ask agent for help" }));
    await waitFor(() => expect(screen.getByLabelText("Your answer")).toBeTruthy(), {
      timeout: 10000,
    });
    await fireEvent.changeText(screen.getByLabelText("Your answer"), "next Saturday");
    await fireEvent.press(screen.getByRole("button", { name: "Continue" }));
    await waitFor(
      () => expect(screen.getByLabelText("Suggestion 1 of 2")).toBeTruthy(),
      { timeout: 10000 },
    );
    await harness.view.rerender(
      <AgentSessionProvider getToken={panelGetToken} sessionEpoch={1}>
        <AgentRuntimeProvider
          workflowId={WORKFLOW_ID}
          initialState={{
            contract_version: 1,
            expected_revision: 2,
            step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
            suggestion_request_id: null,
          }}
        >
          <AgentWorkflowPanel
            userId="9a4b3c2d-1e2f-4a5b-8c6d-7e8f9a0b1c2d"
            workflow={collectWorkflow}
            api={{ getSuggestion: harness.getSuggestion }}
            generateRequestId={() => REQUEST_ID}
            sessionEpoch={1}
            isSessionCurrent={() => true}
            submitAgentSuggestion={harness.submitAgentSuggestion}
            submitAgentTasks={harness.submitAgentTasks}
            dataReady
            onBusyChange={harness.onBusyChange}
          />
        </AgentRuntimeProvider>
      </AgentSessionProvider>,
    );
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(harness.submitAgentSuggestion).toHaveBeenCalledTimes(1);
    expect(bodies).toHaveLength(2);
  }, 45000);
});
