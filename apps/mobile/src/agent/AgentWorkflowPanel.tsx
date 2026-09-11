import { useCallback, useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  findNodeHandle,
} from "react-native";
import {
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react-native";
import {
  useAgUiSetState,
  useAgUiSteerAway,
} from "@assistant-ui/react-ag-ui";
import type { AgentState } from "./AgentRuntimeProvider";
import {
  CLARIFICATION_FIELDS,
  TodoApiError,
  countCodePoints,
  normalizeTodoTitle,
  type ClarificationField,
  type KnownTodoWorkflow,
  type WorkflowSuggestion,
} from "../todos/todoApi";
import type { TodoWorkflowScreenApi } from "../auth/authenticatedApi";
import type { UuidGenerator } from "../todoWorkflows/pendingWorkflowWrite";

export const CLARIFY_TOOL = "clarify_plan";
export const REVIEW_TOOL = "review_todo_suggestions";

/** Fixed trigger text for a new agent run. The server never treats message
 *  content as authority: it validates state and reads the workflow goal from
 *  PostgreSQL, so this text only starts the run. */
export const AGENT_TRIGGER_TEXT = "Help me break this into smaller todos.";

/** Fixed local copy per catalog field. Only the field travels from the
 *  model; question and label copy never accept model or client text. */
export const FIELD_COPY: Record<
  ClarificationField,
  { question: string; label: string; hint: string }
> = {
  date: {
    question: "When does this need to happen?",
    label: "Date or deadline",
    hint: "e.g. next Saturday",
  },
  location: {
    question: "Where will this happen?",
    label: "Location",
    hint: "e.g. Riverside Park",
  },
  people: {
    question: "Who is involved?",
    label: "People",
    hint: "e.g. six adults",
  },
  budget: {
    question: "What spending limits apply?",
    label: "Budget",
    hint: "e.g. under $50",
  },
  constraints: {
    question: "What other limits apply?",
    label: "Constraints",
    hint: "e.g. no stairs",
  },
};

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const isUuidLike = (value: unknown): value is string =>
  typeof value === "string" && UUID_PATTERN.test(value);

const isInt = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value);

const exactKeys = (value: Record<string, unknown>, keys: string[]): boolean => {
  const actual = Reflect.ownKeys(value);
  return (
    actual.length === keys.length &&
    keys.every((key) => Object.prototype.hasOwnProperty.call(value, key))
  );
};

const isField = (value: unknown): value is ClarificationField =>
  typeof value === "string" &&
  (CLARIFICATION_FIELDS as readonly string[]).includes(value);

export type ClarifyArgs = {
  contract_version: 1;
  workflow_id: string;
  expected_revision: number;
  step_id: string;
  field: ClarificationField;
};

/** Parse exact version-1 clarify_plan arguments. Returns null for streamed
 *  partial JSON and for any shape the server would never emit; callers render
 *  a safe recovery message and never advance the workflow. */
export function parseClarifyArgs(argsText: string): ClarifyArgs | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(argsText);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return null;
  }
  const args = parsed as Record<string, unknown>;
  if (
    !exactKeys(args, [
      "contract_version",
      "workflow_id",
      "expected_revision",
      "step_id",
      "field",
    ]) ||
    args.contract_version !== 1 ||
    !isUuidLike(args.workflow_id) ||
    !isInt(args.expected_revision) ||
    typeof args.step_id !== "string" ||
    args.step_id.length === 0 ||
    !isField(args.field)
  ) {
    return null;
  }
  return {
    contract_version: 1,
    workflow_id: args.workflow_id,
    expected_revision: args.expected_revision,
    step_id: args.step_id,
    field: args.field,
  };
}

export type ReviewArgs = {
  contract_version: 1;
  workflow_id: string;
  expected_revision: number;
  step_id: string;
  suggestion_request_id: string;
  titles: string[];
};

/** Parse exact version-1 review_todo_suggestions arguments. Titles must be
 *  canonical (normalizeTodoTitle is identity): anything needing
 *  canonicalization renders a safe recovery message and never advances. */
export function parseReviewArgs(argsText: string): ReviewArgs | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(argsText);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return null;
  }
  const args = parsed as Record<string, unknown>;
  if (
    !exactKeys(args, [
      "contract_version",
      "workflow_id",
      "expected_revision",
      "step_id",
      "suggestion_request_id",
      "titles",
    ]) ||
    args.contract_version !== 1 ||
    !isUuidLike(args.workflow_id) ||
    !isInt(args.expected_revision) ||
    typeof args.step_id !== "string" ||
    args.step_id.length === 0 ||
    !isUuidLike(args.suggestion_request_id) ||
    !Array.isArray(args.titles) ||
    args.titles.length < 2 ||
    args.titles.length > 10 ||
    !args.titles.every(
      (title): title is string =>
        typeof title === "string" && normalizeTodoTitle(title) === title,
    )
  ) {
    return null;
  }
  return {
    contract_version: 1,
    workflow_id: args.workflow_id,
    expected_revision: args.expected_revision,
    step_id: args.step_id,
    suggestion_request_id: args.suggestion_request_id,
    titles: [...args.titles],
  };
}

/** The shared 1–200-code-point answer bound (measured after trimming, in code
 *  points so emoji and astral text count like the server does). Mirrors the
 *  pending-store validator exactly, including NUL and unpaired-surrogate
 *  rejection, so every UI-valid answer is durable-store-valid. */
export function isAnswerValid(value: string): boolean {
  if (typeof value !== "string" || value.includes("\0")) return false;
  const trimmed = value.trim();
  if (trimmed.length === 0) return false;
  const codePoints = countCodePoints(trimmed);
  return codePoints !== null && codePoints <= 200;
}

export type ClarifyResult = {
  contract_version: 1;
  suggestion_request_id: string;
};

export type ReviewResult = {
  contract_version: 1;
  request_id: string;
  accepted_revision: number;
};

function useBlockingReport(
  toolCallId: string,
  blocking: boolean,
  onBlockingChange: ((toolCallId: string, blocking: boolean) => void) | undefined,
): void {
  useEffect(() => {
    onBlockingChange?.(toolCallId, blocking);
    return () => {
      onBlockingChange?.(toolCallId, false);
    };
  }, [toolCallId, blocking, onBlockingChange]);
}

function announce(message: string): void {
  try {
    AccessibilityInfo.announceForAccessibility(message);
  } catch {
    // Announcements are enhancement-only; live regions carry the semantics.
  }
}

function useAnnounceOnMount(message: string): void {
  useEffect(() => {
    announce(message);
  }, [message]);
}

/** Move screen-reader and keyboard focus when a card arrives in an
 *  actionable or settled phase. Fires once per tool call and phase so
 *  replays and rerenders never yank focus twice. */
function useCardFocus(
  toolCallId: string,
  phase: "interactive" | "resolved" | "idle",
  target: { readonly current: unknown },
): void {
  const firedRef = useRef<string | null>(null);
  useEffect(() => {
    if (phase === "idle") return;
    const key = `${toolCallId}:${phase}`;
    if (firedRef.current === key) return;
    firedRef.current = key;
    const control = target.current as { focus?: () => void } | null;
    try {
      control?.focus?.();
    } catch {
      // Best effort: focus is enhancement over live-region announcements.
    }
    try {
      const node = findNodeHandle(
        target.current as React.Component | null,
      );
      if (node !== null && Platform.OS !== "web") {
        AccessibilityInfo.setAccessibilityFocus(node);
      }
    } catch {
      // Best effort: see above.
    }
  }, [toolCallId, phase, target]);
}

type CardChrome = {
  toolCallId: string;
  sessionEpoch: number;
  isSessionCurrent: (epoch: number) => boolean;
  onBusyChange?: (busy: boolean) => void;
  onBlockingChange?: (toolCallId: string, blocking: boolean) => void;
};

function argsMatchSnapshot(
  args: { workflow_id: string; expected_revision: number; step_id: string },
  workflow: KnownTodoWorkflow,
): boolean {
  return (
    args.workflow_id === workflow.workflow_id &&
    args.expected_revision === workflow.revision &&
    args.step_id === workflow.view.step_id
  );
}

export function ClarifyPlanCardView(
  props: CardChrome & {
    args: ClarifyArgs | null;
    resolved: boolean;
    loading: boolean;
    interrupted: boolean;
    workflow: KnownTodoWorkflow;
    submitAnswer: (
      field: ClarificationField,
      value: string,
      requestId: string,
    ) => Promise<WorkflowSuggestion>;
    setAgentState: (state: AgentState) => void;
    addToolResult: (result: ClarifyResult) => void;
    generateRequestId: UuidGenerator;
  },
): React.JSX.Element {
  const {
    toolCallId,
    args,
    resolved,
    loading,
    interrupted,
    workflow,
    submitAnswer,
    setAgentState,
    addToolResult,
    generateRequestId,
    sessionEpoch,
    isSessionCurrent,
    onBusyChange,
    onBlockingChange,
  } = props;
  const copy = args === null ? null : FIELD_COPY[args.field];
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const answerRef = useRef<TextInput>(null);
  const clarifyStatusRef = useRef<Text>(null);
  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );
  useAnnounceOnMount(copy === null ? "Agent update" : copy.question);

  const stale = args === null ? false : !argsMatchSnapshot(args, workflow);
  // A complete tool call without a result waits for this form — including a
  // stale or malformed one, which the user can only clear by reloading.
  // Streaming and interrupted parts never block a fresh run.
  const blocking = !resolved && !completed && !loading && !interrupted;
  useBlockingReport(toolCallId, blocking, onBlockingChange);
  const clarifyInteractive =
    args !== null &&
    !resolved &&
    !completed &&
    !loading &&
    !interrupted &&
    !stale;
  useCardFocus(toolCallId, clarifyInteractive ? "interactive" : "idle", answerRef);
  useCardFocus(
    toolCallId,
    resolved || completed ? "resolved" : "idle",
    clarifyStatusRef,
  );
  useEffect(() => {
    if (completed) announce("Answer sent. Suggestions are on the way.");
  }, [completed]);

  if (resolved || completed) {
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>{copy === null ? "Agent question" : copy.question}</Text>
        <Text ref={clarifyStatusRef} accessibilityLiveRegion="polite" style={styles.status}>
          Answer sent. Suggestions are on the way.
        </Text>
      </View>
    );
  }
  if (loading) {
    return (
      <View style={styles.card}>
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          Loading the agent question…
        </Text>
      </View>
    );
  }
  if (interrupted) {
    return (
      <View style={styles.card}>
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          The agent response was interrupted. Try agent again.
        </Text>
      </View>
    );
  }
  if (args === null) {
    return (
      <View style={styles.card}>
        <Text accessibilityRole="alert" style={styles.status}>
          The agent sent a question this app cannot use. Continue manually below.
        </Text>
      </View>
    );
  }
  const formCopy = FIELD_COPY[args.field];

  const valid = isAnswerValid(answer);
  const disabled = submitting || !valid || stale;

  const onContinue = () => {
    if (submitting || completed || stale || !isAnswerValid(answer)) return;
    const captured = sessionEpoch;
    const value = answer.trim();
    const requestId = generateRequestId();
    setSubmitting(true);
    setError(null);
    onBusyChange?.(true);
    void (async () => {
      try {
        const suggestion = await submitAnswer(args.field, value, requestId);
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        if (
          suggestion.workflow_id !== args.workflow_id ||
          suggestion.request_id !== requestId
        ) {
          setError("The answer is saved. Retry or discard the saved request.");
          return;
        }
        // The authoritative suggestion identity — not the possibly moved-on
        // snapshot prop — is what the next run must observe.
        setAgentState({
          contract_version: 1,
          expected_revision: suggestion.base_revision,
          step_id: suggestion.step_id,
          suggestion_request_id: suggestion.request_id,
        });
        setCompleted(true);
        addToolResult({
          contract_version: 1,
          suggestion_request_id: suggestion.request_id,
        });
      } catch {
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        setError("The answer is saved. Retry or discard the saved request.");
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) {
          setSubmitting(false);
          onBusyChange?.(false);
        }
      }
    })();
  };

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.cardTitle}>
        {formCopy.question}
      </Text>
      {stale && !submitting && (
        <Text accessibilityRole="alert" style={styles.error}>
          This question is for an older plan. Reload to continue.
        </Text>
      )}
      <Text style={styles.fieldLabel}>{formCopy.label}</Text>
      <TextInput
        accessibilityLabel="Your answer"
        ref={answerRef}
        value={answer}
        onChangeText={setAnswer}
        editable={!submitting}
        placeholder={formCopy.hint}
        returnKeyType="done"
        onSubmitEditing={onContinue}
        style={styles.input}
      />
      {!valid && answer.length > 0 && (
        <Text accessibilityLiveRegion="polite" style={styles.error}>
          Enter 1 to 200 characters.
        </Text>
      )}
      {error !== null && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Continue"
        accessibilityState={{ disabled }}
        disabled={disabled}
        onPress={onContinue}
        style={styles.primaryButton}
      >
        <Text style={styles.primaryButtonText}>
          {submitting ? "Sending…" : "Continue"}
        </Text>
      </Pressable>
    </View>
  );
}

export function ReviewSuggestionsCardView(
  props: CardChrome & {
    args: ReviewArgs | null;
    resolved: boolean;
    loading: boolean;
    interrupted: boolean;
    workflow: KnownTodoWorkflow;
    submitTitles: (
      titles: string[],
      suggestionRequestId: string,
    ) => Promise<KnownTodoWorkflow>;
    setAgentState: (state: AgentState) => void;
    addToolResult: (result: ReviewResult) => void;
    sessionEpoch: number;
    isSessionCurrent: (epoch: number) => boolean;
  },
): React.JSX.Element {
  const {
    toolCallId,
    args,
    resolved,
    loading,
    interrupted,
    workflow,
    submitTitles,
    setAgentState,
    addToolResult,
    sessionEpoch,
    isSessionCurrent,
    onBusyChange,
    onBlockingChange,
  } = props;
  const [lines, setLines] = useState<string[]>(args === null ? [] : args.titles);
  const [submitting, setSubmitting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const firstTitleRef = useRef<TextInput>(null);
  const reviewStatusRef = useRef<Text>(null);
  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );
  useAnnounceOnMount("Review suggested todos");

  const stale = args === null ? false : !argsMatchSnapshot(args, workflow);
  const blocking = !resolved && !completed && !loading && !interrupted;
  useBlockingReport(toolCallId, blocking, onBlockingChange);
  const reviewInteractive =
    args !== null &&
    !resolved &&
    !completed &&
    !loading &&
    !interrupted &&
    !stale;
  useCardFocus(toolCallId, reviewInteractive ? "interactive" : "idle", firstTitleRef);
  useCardFocus(
    toolCallId,
    resolved || completed ? "resolved" : "idle",
    reviewStatusRef,
  );
  useEffect(() => {
    if (completed) announce("Suggestions submitted. Review your plan to confirm.");
  }, [completed]);

  if (resolved || completed) {
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Review suggested todos</Text>
        <Text ref={reviewStatusRef} accessibilityLiveRegion="polite" style={styles.status}>
          Suggestions submitted. Review your plan to confirm.
        </Text>
      </View>
    );
  }
  if (loading) {
    return (
      <View style={styles.card}>
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          Loading suggested todos…
        </Text>
      </View>
    );
  }
  if (interrupted) {
    return (
      <View style={styles.card}>
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          The agent response was interrupted. Try agent again.
        </Text>
      </View>
    );
  }
  if (args === null) {
    return (
      <View style={styles.card}>
        <Text accessibilityRole="alert" style={styles.status}>
          The agent sent suggestions this app cannot use. Continue manually below.
        </Text>
      </View>
    );
  }

  const canonical = lines.map((line) => normalizeTodoTitle(line));
  const titlesValid =
    lines.length >= 2 &&
    lines.length <= 10 &&
    canonical.every((title) => title !== null);
  const disabled = submitting || !titlesValid || stale;

  const changeLine = (index: number, value: string) => {
    setLines((current) => current.map((line, i) => (i === index ? value : line)));
  };
  const removeLine = (index: number) => {
    setLines((current) =>
      current.length <= 2 ? current : current.filter((_, i) => i !== index),
    );
  };

  const onUseSuggestions = () => {
    if (submitting || completed || stale) return;
    const titles = lines.map((line) => normalizeTodoTitle(line));
    if (
      titles.length < 2 ||
      titles.length > 10 ||
      titles.some((title) => title === null)
    ) {
      return;
    }
    const canonicalTitles = titles as string[];
    const captured = sessionEpoch;
    setSubmitting(true);
    setError(null);
    onBusyChange?.(true);
    void (async () => {
      try {
        const next = await submitTitles(canonicalTitles, args.suggestion_request_id);
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        if (
          next.workflow_id !== args.workflow_id ||
          next.state !== "REVIEW"
        ) {
          setError("The suggestions are saved. Retry or discard the saved request.");
          return;
        }
        // State first so the automatic continuation runs against REVIEW;
        // the result only acknowledges, it never writes or regenerates.
        setAgentState({
          contract_version: 1,
          expected_revision: next.revision,
          step_id: next.view.step_id,
          suggestion_request_id: args.suggestion_request_id,
        });
        setCompleted(true);
        addToolResult({
          contract_version: 1,
          request_id: args.suggestion_request_id,
          accepted_revision: next.revision,
        });
      } catch {
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        setError("The suggestions are saved. Retry or discard the saved request.");
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) {
          setSubmitting(false);
          onBusyChange?.(false);
        }
      }
    })();
  };

  return (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.cardTitle}>
        Review suggested todos
      </Text>
      {stale && !submitting && (
        <Text accessibilityRole="alert" style={styles.error}>
          These suggestions are for an older plan. Reload to continue.
        </Text>
      )}
      {lines.map((line, index) => (
        <View key={`${index}`} style={styles.titleRow}>
          <TextInput
            accessibilityLabel={`Suggestion ${index + 1} of ${lines.length}`}
            ref={index === 0 ? firstTitleRef : undefined}
            value={line}
            onChangeText={(value) => changeLine(index, value)}
            editable={!submitting}
            style={styles.input}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Remove suggestion ${index + 1}`}
            accessibilityState={{ disabled: submitting || lines.length <= 2 }}
            disabled={submitting || lines.length <= 2}
            onPress={() => removeLine(index)}
            style={styles.secondaryButton}
          >
            <Text style={styles.secondaryButtonText}>Remove</Text>
          </Pressable>
        </View>
      ))}
      {!titlesValid && (
        <Text accessibilityLiveRegion="polite" style={styles.error}>
          Keep 2 to 10 valid todo titles.
        </Text>
      )}
      {error !== null && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Use these suggestions"
        accessibilityState={{ disabled }}
        disabled={disabled}
        onPress={onUseSuggestions}
        style={styles.primaryButton}
      >
        <Text style={styles.primaryButtonText}>
          {submitting ? "Submitting…" : "Use these suggestions"}
        </Text>
      </Pressable>
    </View>
  );
}

type ToolPart = {
  type: string;
  toolCallId: string;
  toolName?: string;
  argsText?: string;
  result?: unknown;
  status?: { type?: string };
};

export function AgentWorkflowPanel(props: {
  userId: string;
  workflow: KnownTodoWorkflow;
  api: Pick<TodoWorkflowScreenApi, "getSuggestion">;
  generateRequestId: UuidGenerator;
  sessionEpoch: number;
  isSessionCurrent: (epoch: number) => boolean;
  submitAgentSuggestion: (
    field: ClarificationField,
    value: string,
    requestId: string,
  ) => Promise<WorkflowSuggestion>;
  submitAgentTasks: (
    titles: string[],
    suggestionRequestId: string,
  ) => Promise<KnownTodoWorkflow>;
  dataReady: boolean;
  onBusyChange?: (busy: boolean) => void;
  /** Fires on mount/unmount inside the runtime provider, i.e. after the
   *  state gate releases the thread UI. The screen refires step focus on
   *  this signal so gated templates still receive focus on first mount. */
  onReadyChange?: (ready: boolean) => void;
}): React.JSX.Element | null {
  const {
    workflow,
    api,
    generateRequestId,
    sessionEpoch,
    isSessionCurrent,
    submitAgentSuggestion,
    submitAgentTasks,
    dataReady,
    onBusyChange,
    onReadyChange,
  } = props;
  const setAgentState = useAgUiSetState<AgentState>();
  const steerAway = useAgUiSteerAway();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const [askedOnce, setAskedOnce] = useState(false);
  const [askBusy, setAskBusy] = useState(false);
  const [cardBusy, setCardBusy] = useState(false);
  const [blockingIds, setBlockingIds] = useState<readonly string[]>([]);
  const [askError, setAskError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const workflowRef = useRef(workflow);
  const askAbortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    workflowRef.current = workflow;
  });
  useEffect(
    () => () => {
      mountedRef.current = false;
      askAbortRef.current?.abort();
    },
    [],
  );
  useEffect(() => {
    onReadyChange?.(true);
    return () => {
      onReadyChange?.(false);
    };
  }, [onReadyChange]);

  const reportCardBusy = useCallback((busy: boolean) => {
    setCardBusy(busy);
  }, []);
  useEffect(() => {
    onBusyChange?.(askBusy || cardBusy);
  }, [askBusy, cardBusy, onBusyChange]);
  const reportBlocking = useCallback((toolCallId: string, blocking: boolean) => {
    setBlockingIds((current) => {
      const has = current.includes(toolCallId);
      if (blocking && !has) return [...current, toolCallId];
      if (!blocking && has) return current.filter((id) => id !== toolCallId);
      return current;
    });
  }, []);

  // The panel rests outside the breakdown step, but an in-flight submission
  // or an unresolved tool keeps the thread mounted until its result is sent:
  // unmounting mid-submit would omit the acknowledgement continuation.
  const onBreakdownStep = workflow.view.type === "task_breakdown";
  const threadActive = isRunning || askBusy || cardBusy || blockingIds.length > 0;
  if (!onBreakdownStep && !threadActive) {
    return null;
  }

  const askDisabled =
    !dataReady || isRunning || askBusy || cardBusy || blockingIds.length > 0;

  const onAsk = () => {
    if (askDisabled) return;
    const captured = sessionEpoch;
    setAskBusy(true);
    setAskError(null);
    onBusyChange?.(true);
    askAbortRef.current?.abort();
    const controller = new AbortController();
    askAbortRef.current = controller;
    void (async () => {
      try {
        const current = workflowRef.current;
        let readyId: string | null = null;
        try {
          const found = await api.getSuggestion(current.workflow_id, {
            signal: controller.signal,
          });
          if (
            found.status === "ready" &&
            found.workflow_id === current.workflow_id &&
            found.base_revision === current.revision &&
            found.step_id === current.view.step_id
          ) {
            readyId = found.request_id;
          }
        } catch (error) {
          if (error instanceof Error && error.name === "AbortError") return;
          if (error instanceof TodoApiError && error.kind === "not-found") {
            readyId = null;
          } else {
            throw error;
          }
        }
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        const identity = workflowRef.current;
        if (identity.workflow_id !== current.workflow_id) return;
        // A ready proposal replays from storage with no model call; without
        // one the run takes a fresh paid choice. Either way the state the
        // run observes is installed synchronously before it starts.
        setAgentState({
          contract_version: 1,
          expected_revision: identity.revision,
          step_id: identity.view.step_id,
          suggestion_request_id: readyId,
        });
        await steerAway(AGENT_TRIGGER_TEXT);
        if (mountedRef.current && isSessionCurrent(captured)) {
          setAskedOnce(true);
        }
      } catch {
        if (mountedRef.current && isSessionCurrent(captured)) {
          setAskError("The agent could not be reached. Try again or continue manually.");
        }
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) {
          setAskBusy(false);
          onBusyChange?.(false);
        }
      }
    })();
  };

  const renderPart = (part: ToolPart): React.ReactNode => {
    if (part.type === "text") {
      const text = (part as { text?: unknown }).text;
      if (typeof text !== "string" || text.length === 0) return null;
      return <Text style={styles.agentText}>{text}</Text>;
    }
    if (part.type !== "tool-call") return null;
    const statusType = part.status?.type ?? "unknown";
    const resolved = part.result !== undefined;
    if (part.toolName === CLARIFY_TOOL) {
      const args = parseClarifyArgs(part.argsText ?? "");
      if (args === null) {
        if (statusType === "running") {
          return (
            <View style={styles.card}>
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                Loading the agent question…
              </Text>
            </View>
          );
        }
        if (statusType === "incomplete") {
          return (
            <View style={styles.card}>
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                The agent response was interrupted. Try agent again.
              </Text>
            </View>
          );
        }
        return (
          <ToolRecovery
            toolCallId={part.toolCallId}
            blocking={!resolved}
            onBlockingChange={reportBlocking}
            message="The agent sent a question this app cannot use. Continue manually below."
          />
        );
      }
      return (
        <ClarifyPlanCardView
          toolCallId={part.toolCallId}
          args={args}
          resolved={resolved}
          loading={statusType === "running"}
          interrupted={statusType === "incomplete"}
          workflow={workflow}
          submitAnswer={submitAgentSuggestion}
          setAgentState={setAgentState}
          addToolResult={(result) =>
            (part as { addResult?: (result: unknown) => void }).addResult?.(result)
          }
          generateRequestId={generateRequestId}
          sessionEpoch={sessionEpoch}
          isSessionCurrent={isSessionCurrent}
          onBusyChange={reportCardBusy}
          onBlockingChange={reportBlocking}
        />
      );
    }
    if (part.toolName === REVIEW_TOOL) {
      const args = parseReviewArgs(part.argsText ?? "");
      if (args === null) {
        if (statusType === "running") {
          return (
            <View style={styles.card}>
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                Loading suggested todos…
              </Text>
            </View>
          );
        }
        if (statusType === "incomplete") {
          return (
            <View style={styles.card}>
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                The agent response was interrupted. Try agent again.
              </Text>
            </View>
          );
        }
        return (
          <ToolRecovery
            toolCallId={part.toolCallId}
            blocking={!resolved}
            onBlockingChange={reportBlocking}
            message="The agent sent suggestions this app cannot use. Continue manually below."
          />
        );
      }
      return (
        <ReviewSuggestionsCardView
          toolCallId={part.toolCallId}
          args={args}
          resolved={resolved}
          loading={statusType === "running"}
          interrupted={statusType === "incomplete"}
          workflow={workflow}
          submitTitles={submitAgentTasks}
          setAgentState={setAgentState}
          addToolResult={(result) =>
            (part as { addResult?: (result: unknown) => void }).addResult?.(result)
          }
          sessionEpoch={sessionEpoch}
          isSessionCurrent={isSessionCurrent}
          onBusyChange={reportCardBusy}
          onBlockingChange={reportBlocking}
        />
      );
    }
    return (
      <ToolRecovery
        toolCallId={part.toolCallId}
        blocking={!resolved}
        onBlockingChange={reportBlocking}
        message="The agent sent a response this app cannot use. Continue manually below."
      />
    );
  };

  return (
    <View style={styles.panel}>
      <ThreadPrimitive.Root>
        <ThreadPrimitive.MessagesFlatList
          scrollEnabled={false}
          autoScroll={false}
          ListEmptyComponent={
            <Text style={styles.status}>
              Ask the agent for help breaking this into smaller todos.
            </Text>
          }
        >
          {({ message }) =>
            message.role === "user" ? (
              <Text style={styles.agentText}>You asked the agent for help.</Text>
            ) : (
              <MessagePrimitive.Parts>
                {({ part }) => renderPart(part as unknown as ToolPart)}
              </MessagePrimitive.Parts>
            )
          }
        </ThreadPrimitive.MessagesFlatList>
      </ThreadPrimitive.Root>
      {isRunning && (
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          Agent working…
        </Text>
      )}
      {askError !== null && (
        <Text accessibilityRole="alert" style={styles.error}>
          {askError}
        </Text>
      )}
      {onBreakdownStep && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={askedOnce ? "Try agent again" : "Ask agent for help"}
          accessibilityState={{ disabled: askDisabled }}
          disabled={askDisabled}
          onPress={onAsk}
          style={styles.secondaryButton}
        >
          <Text style={styles.secondaryButtonText}>
            {askBusy ? "Asking…" : askedOnce ? "Try agent again" : "Ask agent for help"}
          </Text>
        </Pressable>
      )}
      {isRunning && onBreakdownStep && (
        <ComposerPrimitive.Cancel accessibilityLabel="Cancel agent run">
          <Text style={styles.cancelText}>Cancel agent run</Text>
        </ComposerPrimitive.Cancel>
      )}
      <Text style={styles.status}>
        If the agent can&apos;t help, use Suggest todos or enter titles manually.
      </Text>
    </View>
  );
}

function ToolRecovery({
  toolCallId,
  blocking,
  onBlockingChange,
  message,
}: {
  toolCallId: string;
  blocking: boolean;
  onBlockingChange?: (toolCallId: string, blocking: boolean) => void;
  message: string;
}): React.JSX.Element {
  useBlockingReport(toolCallId, blocking, onBlockingChange);
  return (
    <View style={styles.card}>
      <Text accessibilityRole="alert" style={styles.status}>
        {message}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    gap: 10,
  },
  card: {
    backgroundColor: "#eef3ff",
    borderRadius: 10,
    gap: 10,
    padding: 16,
  },
  cardTitle: {
    color: "#172033",
    fontSize: 19,
    fontWeight: "700",
  },
  fieldLabel: {
    color: "#42526b",
    fontSize: 15,
    fontWeight: "600",
  },
  input: {
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    color: "#172033",
    fontSize: 17,
    minHeight: 48,
    paddingHorizontal: 14,
  },
  titleRow: {
    flexDirection: "row",
    gap: 8,
  },
  primaryButton: {
    alignItems: "center",
    backgroundColor: "#2457d6",
    borderRadius: 10,
    justifyContent: "center",
    minHeight: 48,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  primaryButtonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  secondaryButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  secondaryButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
  // The Cancel primitive owns its pressable, so the text child itself
  // guarantees the 44-point target every other control gets from its button.
  cancelText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
    minHeight: 44,
    minWidth: 44,
    textAlign: "center",
    textAlignVertical: "center",
  },
  status: {
    color: "#42526b",
    fontSize: 15,
  },
  error: {
    color: "#b42318",
    fontSize: 15,
  },
  agentText: {
    color: "#42526b",
    fontSize: 15,
  },
});
