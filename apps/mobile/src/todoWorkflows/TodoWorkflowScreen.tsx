import { useEffect, useRef, useState, type RefObject } from "react";
import {
  AccessibilityInfo,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  findNodeHandle,
} from "react-native";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  normalizeTodoTitle,
  TodoApiError,
  type TodoWorkflow,
  type TodoWorkflowAction,
  type WorkflowSuggestion,
} from "../todos/todoApi";
import type { TodoWorkflowScreenApi } from "../auth/authenticatedApi";
import {
  defaultUuidGenerator,
  pendingWriteStore,
  saveAndSendPendingWrite,
  type PendingWorkflowWrite,
  type PendingWriteStore,
  type UuidGenerator,
} from "./pendingWorkflowWrite";
import {
  keepLatestWorkflow,
  shareWorkflowSnapshot,
  StaleWorkflowSessionError,
} from "./workflowCache";

export function workflowQueryKey(userId: string, workflowId: string) {
  return ["todo-workflow", userId, workflowId] as const;
}

const EMPTY_TITLE = "Enter a task title.";
const INVALID_TITLE = "Check the plan title and try again.";
const SERVER_INVALID = "Check the plan details and try again.";
const STORAGE_FAILURE =
  "This device could not save a safe retry. The plan was not sent. Try again.";
const PENDING_EXISTS =
  "Another workflow write is still pending. Retry or discard it before sending a new one.";
const RECOVERY_PENDING =
  "The plan was saved, but recovery is still pending. Retry or discard the saved request.";
const DISCARD_WARNING =
  "The saved request was discarded locally, but the server may already have applied it. Refresh the list to check.";
const UNKNOWN_START_FAILURE = "Could not start planning. Retry the saved request.";
const UNKNOWN_ADVANCE_FAILURE = "Could not update the plan. Retry the saved request.";
const INVALID_RESPONSE = "The API returned invalid plan data.";

type StartRecord = Extract<PendingWorkflowWrite, { operation: "start" }>;
type AdvanceRecord = Extract<PendingWorkflowWrite, { operation: "advance" }>;
type SuggestRecord = Extract<PendingWorkflowWrite, { operation: "suggest" }>;

function messageForGetError(error: unknown): string {
  if (error instanceof TodoApiError) return error.message;
  return "Could not reload the plan.";
}

const templateRegistry = {
  yes_no: YesNoTemplate,
  task_breakdown: TaskBreakdownTemplate,
  review: ReviewTemplate,
  completion: CompletionTemplate,
} as const;

export function TodoWorkflowScreen({
  userId,
  api,
  onExit,
  initialWorkflowId = null,
  pendingStore = pendingWriteStore,
  generateRequestId = defaultUuidGenerator,
  sessionEpoch,
  isSessionCurrent,
}: {
  userId: string;
  api: TodoWorkflowScreenApi;
  onExit: () => void;
  initialWorkflowId?: string | null;
  pendingStore?: PendingWriteStore;
  generateRequestId?: UuidGenerator;
  sessionEpoch: number;
  isSessionCurrent: (epoch: number) => boolean;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [workflowId, setWorkflowId] = useState<string | null>(initialWorkflowId);
  const [startDraft, setStartDraft] = useState("");
  const [tasksDraft, setTasksDraft] = useState("");
  const [tasksDraftEditCounter, setTasksDraftEditCounter] = useState(0);
  const [suggestionRecord, setSuggestionRecord] = useState<WorkflowSuggestion | null>(null);
  const [suggestionFetching, setSuggestionFetching] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [replaceSuggestions, setReplaceSuggestions] = useState(false);
  const [newSuggestionWarning, setNewSuggestionWarning] = useState(false);
  const [discardSuggestionWarning, setDiscardSuggestionWarning] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<{
    message: string;
    lock: boolean;
    sticky?: boolean;
  } | null>(null);
  const [pendingRecord, setPendingRecord] = useState<PendingWorkflowWrite | null>(null);
  const [persisting, setPersisting] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [reconcileFailed, setReconcileFailed] = useState(false);
  const [focusSignal, setFocusSignal] = useState(0);
  const busy = useRef(false);
  const mountedRef = useRef(true);
  const reconcileAbortRef = useRef<AbortController | null>(null);
  const suggestionAbortRef = useRef<AbortController | null>(null);
  const focusedSignal = useRef(-1);
  const tasksDraftRef = useRef(tasksDraft);
  const tasksDraftEditCounterRef = useRef(tasksDraftEditCounter);
  const suggestionFetchSequence = useRef(0);
  const hydratedSuggestionRequestIds = useRef(new Set<string>());
  const liveRequestIds = useRef(new Set<string>());
  const previousStepId = useRef<string | null>(null);
  const titleInput = useRef<TextInput>(null);
  const tasksInput = useRef<TextInput>(null);
  const yesButton = useRef<View>(null);
  const confirmButton = useRef<View>(null);
  const backButton = useRef<View>(null);

  useEffect(() => () => {
    mountedRef.current = false;
    reconcileAbortRef.current?.abort();
    suggestionAbortRef.current?.abort();
  }, []);

  const livePending =
    pendingRecord !== null && pendingRecord.ownerId === userId ? pendingRecord : null;

  // Offer a durable unknown write recorded by an earlier app instance. The
  // record is never sent automatically; the owner explicitly retries it.
  useEffect(() => {
    const captured = sessionEpoch;
    const owner = userId;
    let cancelled = false;
    void (async () => {
      let record: PendingWorkflowWrite | null = null;
      try {
        record = await pendingStore.read(owner);
      } catch {
        record = null;
      }
      if (cancelled || !mountedRef.current) return;
      if (!isSessionCurrent(captured)) return;
      if (record === null || record.ownerId !== owner) return;
      const targetWorkflow =
        record.operation === "start" ? null : record.workflowId;
      if (record.operation === "suggest" && !liveRequestIds.current.has(record.requestId)) {
        hydratedSuggestionRequestIds.current.add(record.requestId);
      }
      setPendingRecord((current) =>
        current !== null && liveRequestIds.current.has(current.requestId) ? current : record,
      );
      if (targetWorkflow !== null) {
        setWorkflowId((current) => current ?? targetWorkflow);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, pendingStore, sessionEpoch, isSessionCurrent]);

  const workflowQuery = useQuery({
    queryKey:
      workflowId === null
        ? (["todo-workflow", userId, "new"] as const)
        : workflowQueryKey(userId, workflowId),
    queryFn: async ({ signal }) => {
      const captured = sessionEpoch;
      const id = workflowId as string;
      const fetched = await api.getWorkflow(id, { signal });
      if (fetched.workflow_id !== id) {
        throw new TodoApiError("invalid-data", "The API returned invalid plan data.");
      }
      if (!isSessionCurrent(captured)) {
        const previous = queryClient.getQueryData<TodoWorkflow>(
          workflowQueryKey(userId, id)
        );
        if (previous !== undefined) return previous;
        throw new StaleWorkflowSessionError();
      }
      return fetched;
    },
    enabled: workflowId !== null,
    structuralSharing: (oldData, incoming) =>
      shareWorkflowSnapshot(oldData, incoming),
  });
  const workflowQueryRef = useRef(workflowQuery);
  const pendingRecordRef = useRef(pendingRecord);
  const reconcileFailedRef = useRef(reconcileFailed);
  const writeErrorRef = useRef(writeError);
  // Mirror render values for async callbacks without touching refs
  // during render. Declared before the step effect so mirrors are fresh
  // when it runs.
  useEffect(() => {
    workflowQueryRef.current = workflowQuery;
    pendingRecordRef.current = pendingRecord;
    reconcileFailedRef.current = reconcileFailed;
    writeErrorRef.current = writeError;
    tasksDraftRef.current = tasksDraft;
    tasksDraftEditCounterRef.current = tasksDraftEditCounter;
  });

  const snapshot = workflowId === null ? undefined : workflowQuery.data;
  const view = snapshot?.view;
  const stepId = view?.step_id;
  const hasData = snapshot !== undefined;
  const isFetching = workflowQuery.isFetching;
  const isStale = workflowQuery.isStale;
  const fresh = hasData && !isStale;
  const getError = workflowQuery.error;
  const definitionUnsupported =
    workflowId !== null &&
    getError instanceof TodoApiError &&
    getError.kind === "conflict" &&
    getError.conflictCode === "unsupported_workflow_definition";

  useEffect(() => {
    if (stepId === undefined || stepId === previousStepId.current) return;
    previousStepId.current = stepId;
    tasksDraftRef.current = "";
    tasksDraftEditCounterRef.current += 1;
    setTasksDraft("");
    setTasksDraftEditCounter((counter) => counter + 1);
    setSuggestionRecord(null);
    setSuggestionError(null);
    setReplaceSuggestions(false);
    setNewSuggestionWarning(false);
    setLocalError(null);
    // An arrived step clears alerts only when no recovery is outstanding:
    // a pending write or a failed reconciliation owns the message. A stale
    // notice is sticky: it must survive the reconciled step arrival that it
    // explains, and is cleared only by the next write or manual reload.
    if (
      writeErrorRef.current?.sticky !== true &&
      pendingRecordRef.current === null &&
      !reconcileFailedRef.current
    ) {
      setWriteError(null);
    }
    setFocusSignal((signal) => signal + 1);
  }, [stepId]);

  const seedSnapshot = (workflow: TodoWorkflow) => {
    const key = workflowQueryKey(userId, workflow.workflow_id);
    queryClient.setQueryData<TodoWorkflow>(key, (old) => {
      if (old === undefined) return workflow;
      if (old.workflow_id !== workflow.workflow_id) return old;
      return keepLatestWorkflow(old, workflow);
    });
  };

  const noteTerminalOutcome = (workflow: TodoWorkflow) => {
    if (workflow.view.type === "completion") {
      void queryClient.invalidateQueries({ queryKey: ["todos"] });
      void queryClient.invalidateQueries({
        queryKey: ["todo-workflows", userId, "active"],
      });
    }
  };

  const clearPendingRecord = async (
    record: PendingWorkflowWrite,
    captured: number
  ): Promise<boolean> => {
    try {
      await pendingStore.clear(userId, record.requestId);
    } catch {
      if (mountedRef.current && isSessionCurrent(captured)) {
        setPendingRecord(record);
        setWriteError({ message: RECOVERY_PENDING, lock: true });
      }
      return false;
    }
    if (mountedRef.current && isSessionCurrent(captured)) {
      setPendingRecord(null);
    }
    return true;
  };

  type CurrentFetch = { ok: true; snapshot: TodoWorkflow } | { ok: false; message: string };

  const shouldClearSuggestionRecord = (
    retained: SuggestRecord,
    fetched: WorkflowSuggestion,
  ): boolean => {
    if (
      retained.workflowId !== fetched.workflow_id ||
      retained.body.expected_revision !== fetched.base_revision ||
      retained.body.step_id !== fetched.step_id
    ) {
      return false;
    }
    if (hydratedSuggestionRequestIds.current.has(retained.requestId)) {
      return fetched.status !== "pending" || fetched.request_id !== retained.requestId;
    }
    return fetched.status !== "pending" && fetched.request_id === retained.requestId;
  };

  const fetchCurrentSnapshot = async (
    id: string,
    captured: number
  ): Promise<CurrentFetch | null> => {
    reconcileAbortRef.current?.abort();
    const controller = new AbortController();
    reconcileAbortRef.current = controller;
    let fetched: TodoWorkflow;
    try {
      fetched = await api.getWorkflow(id, { signal: controller.signal });
    } catch (error) {
      if (!mountedRef.current || !isSessionCurrent(captured)) return null;
      if (error instanceof Error && error.name === "AbortError") return null;
      return { ok: false, message: messageForGetError(error) };
    }
    if (!mountedRef.current || !isSessionCurrent(captured)) return null;
    if (
      typeof fetched !== "object" ||
      fetched === null ||
      (fetched as TodoWorkflow).workflow_id !== id
    ) {
      return { ok: false, message: INVALID_RESPONSE };
    }
    seedSnapshot(fetched);
    return { ok: true, snapshot: fetched };
  };

  const fetchSuggestionRecord = async (
    id: string,
    captured: number,
    expectedRevision: number,
    expectedStepId: string,
    capturedEditCounter: number,
  ): Promise<WorkflowSuggestion | null> => {
    const sequence = suggestionFetchSequence.current + 1;
    suggestionFetchSequence.current = sequence;
    if (mountedRef.current && isSessionCurrent(captured)) {
      setSuggestionFetching(true);
      setSuggestionError(null);
    }
    suggestionAbortRef.current?.abort();
    const controller = new AbortController();
    suggestionAbortRef.current = controller;
    let fetched: WorkflowSuggestion;
    try {
      fetched = await api.getSuggestion(id, { signal: controller.signal });
    } catch (error) {
      if (!mountedRef.current || !isSessionCurrent(captured) || sequence !== suggestionFetchSequence.current) {
        return null;
      }
      setSuggestionFetching(false);
      if (error instanceof TodoApiError && error.kind === "not-found") {
        setSuggestionRecord(null);
        return null;
      }
      if (error instanceof Error && error.name === "AbortError") return null;
      setSuggestionRecord(null);
      setSuggestionError(error instanceof TodoApiError ? error.message : "Could not load todo suggestions.");
      return null;
    }
    if (!mountedRef.current || !isSessionCurrent(captured) || sequence !== suggestionFetchSequence.current) {
      return null;
    }
    const current = workflowQueryRef.current.data;
    if (
      current === undefined ||
      current.workflow_id !== id ||
      current.revision !== expectedRevision ||
      current.view.step_id !== expectedStepId ||
      fetched.workflow_id !== id ||
      fetched.base_revision !== expectedRevision ||
      fetched.step_id !== expectedStepId
    ) {
      setSuggestionFetching(false);
      return null;
    }
    setSuggestionRecord(fetched);
    setSuggestionFetching(false);
    const retained = pendingRecordRef.current;
    if (
      retained?.operation === "suggest" &&
      shouldClearSuggestionRecord(retained, fetched)
    ) {
      void clearPendingRecord(retained, captured);
    }
    if (
      fetched.status === "ready" &&
      tasksDraftRef.current === "" &&
      tasksDraftEditCounterRef.current === capturedEditCounter
    ) {
      const seededDraft = fetched.proposed_titles.join("\n");
      tasksDraftRef.current = seededDraft;
      setTasksDraft(seededDraft);
      setFocusSignal((signal) => signal + 1);
    }
    return fetched;
  };

  useEffect(() => {
    if (
      workflowId === null ||
      !fresh ||
      snapshot === undefined ||
      snapshot.view.type !== "task_breakdown"
    ) {
      return;
    }
    const captured = sessionEpoch;
    const id = workflowId;
    const revision = snapshot.revision;
    const currentStepId = snapshot.view.step_id;
    const editCounter = tasksDraftEditCounterRef.current;
    void fetchSuggestionRecord(id, captured, revision, currentStepId, editCounter);
    // The workflow revision and step identity are the authoritative trigger;
    // a suggestion GET never changes either value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, snapshot?.revision, snapshot?.view.step_id, fresh, sessionEpoch]);

  // The pending-record read and the authoritative suggestion GET can finish
  // in either order on restart. Re-run the resolution check when the stored
  // record arrives after the GET so a ready/failed result never leaves a
  // retry lock on an already-settled request.
  useEffect(() => {
    const retained = pendingRecord;
    const fetched = suggestionRecord;
    if (
      retained?.operation !== "suggest" ||
      fetched === null ||
      !shouldClearSuggestionRecord(retained, fetched)
    ) {
      return;
    }
    void clearPendingRecord(retained, sessionEpoch);
    // clearPendingRecord is recreated with the current render state; the
    // tracked values above are the intended resolution trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingRecord, suggestionRecord, sessionEpoch]);

  const reconcileSuggestionAfterWrite = async (
    record: SuggestRecord,
    captured: number,
    message: string | null,
  ): Promise<void> => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    setReconciling(true);
    setSuggestionError(null);
    try {
      const current = await fetchCurrentSnapshot(record.workflowId, captured);
      if (!mountedRef.current || !isSessionCurrent(captured) || current === null) return;
      if (!current.ok) {
        setReconcileFailed(true);
        setWriteError({ message: current.message, lock: true });
        return;
      }
      const sameStep =
        current.snapshot.revision === record.body.expected_revision &&
        current.snapshot.view.step_id === record.body.step_id;
      if (!sameStep) {
        await clearPendingRecord(record, captured);
        if (message !== null && mountedRef.current && isSessionCurrent(captured)) {
          setWriteError({ message, lock: false });
        }
        return;
      }
      const saved = await fetchSuggestionRecord(
        record.workflowId,
        captured,
        record.body.expected_revision,
        record.body.step_id,
        tasksDraftEditCounterRef.current,
      );
      if (!mountedRef.current || !isSessionCurrent(captured)) return;
      if (saved === null) {
        setPendingRecord(record);
        setWriteError({ message: RECOVERY_PENDING, lock: true });
        return;
      }
      if (saved.request_id !== record.requestId || saved.status === "pending") {
        // A different result may be an older read that raced the request, and
        // a pending same-ID result has not established a terminal outcome.
        // Keep the live retry until a later authoritative GET proves this
        // request settled.
        setPendingRecord(record);
        setWriteError({ message: RECOVERY_PENDING, lock: true });
        return;
      }
      await clearPendingRecord(record, captured);
      if (!mountedRef.current || !isSessionCurrent(captured)) return;
      if (message !== null) setWriteError({ message, lock: false });
      else setWriteError(null);
    } finally {
      if (mountedRef.current && isSessionCurrent(captured)) setReconciling(false);
    }
  };

  const settleSuggestionResponse = async (
    record: SuggestRecord,
    response: WorkflowSuggestion,
    captured: number,
  ): Promise<void> => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    if (
      response.workflow_id !== record.workflowId ||
      response.request_id !== record.requestId ||
      response.base_revision !== record.body.expected_revision ||
      response.step_id !== record.body.step_id
    ) {
      setWriteError({ message: INVALID_RESPONSE, lock: true });
      return;
    }
    await reconcileSuggestionAfterWrite(record, captured, null);
  };

  const settleSuggestionError = (
    record: SuggestRecord,
    error: unknown,
    captured: number,
  ): void => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    if (error instanceof TodoApiError && error.suggestionCode !== undefined) {
      void reconcileSuggestionAfterWrite(record, captured, error.message);
      return;
    }
    if (error instanceof TodoApiError && error.kind === "conflict") {
      if (error.conflictCode === "stale_suggestion") {
        void reconcileSuggestionAfterWrite(record, captured, error.message);
        return;
      }
      setWriteError({ message: error.message, lock: true });
      return;
    }
    setWriteError({
      message: error instanceof TodoApiError ? error.message : "Could not suggest todos.",
      lock: true,
    });
  };

  const reconcileAfterWrite = async (
    id: string,
    captured: number,
    options: {
      clearRecord: PendingWorkflowWrite | null;
      keepMessage: boolean;
      clearFirst: boolean;
    }
  ): Promise<void> => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    setReconciling(true);
    setReconcileFailed(false);
    try {
      // Conflict paths clear the matching record before the reconciliation
      // GET: a failed GET must not resurrect a Retry for a request the server
      // already rejected. Success paths keep clear-after-GET so an unproven
      // reconciliation retains its safe retry. The clear-first step shares
      // this try/finally so a clear failure still resets the reconciling
      // indicator (the pending record stays, keeping its own retry lock).
      if (options.clearFirst && options.clearRecord !== null) {
        const cleared = await clearPendingRecord(options.clearRecord, captured);
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        if (!cleared) return;
      }
      const fetched = await fetchCurrentSnapshot(id, captured);
      if (!mountedRef.current || !isSessionCurrent(captured)) return;
      if (fetched === null) return;
      if (!fetched.ok) {
        setReconcileFailed(true);
        setWriteError({ message: fetched.message, lock: true });
        return;
      }
      noteTerminalOutcome(fetched.snapshot);
      setReconcileFailed(false);
      let cleared = true;
      if (!options.clearFirst && options.clearRecord !== null) {
        cleared = await clearPendingRecord(options.clearRecord, captured);
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
      }
      if (!cleared) return;
      if (options.clearRecord !== null) setPendingRecord(null);
      if (!options.keepMessage) setWriteError(null);
    } finally {
      if (mountedRef.current && isSessionCurrent(captured)) setReconciling(false);
    }
  };

  const settleStartResponse = async (
    record: StartRecord,
    response: TodoWorkflow,
    captured: number
  ): Promise<void> => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    // The start protocol echoes no request ID: the recorded outcome is keyed
    // by OUR request ID server-side, so the recovered workflow ID is trusted
    // by construction. (Advance responses carry an expected workflow ID and
    // are verified in settleAdvanceResponse.)
    const id = response.workflow_id;
    seedSnapshot(response);
    noteTerminalOutcome(response);
    void queryClient.invalidateQueries({
      queryKey: ["todo-workflows", userId, "active"],
    });
    await reconcileAfterWrite(id, captured, {
      clearRecord: record,
      keepMessage: false,
      clearFirst: false,
    });
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    setWorkflowId(id);
  };

  const settleStartError = (record: StartRecord, error: unknown, captured: number): void => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    if (error instanceof TodoApiError && error.kind === "conflict") {
      if (error.conflictCode === "request_id_reused") {
        setWriteError({ message: error.message, lock: true });
        return;
      }
      setWriteError({ message: error.message, lock: false });
      void (async () => {
        await clearPendingRecord(record, captured);
      })();
      return;
    }
    if (error instanceof TodoApiError && error.kind === "validation") {
      setWriteError({ message: SERVER_INVALID, lock: false });
      void (async () => {
        await clearPendingRecord(record, captured);
      })();
      return;
    }
    if (error instanceof TodoApiError && error.kind === "not-found") {
      setWriteError({ message: error.message, lock: false });
      void (async () => {
        await clearPendingRecord(record, captured);
      })();
      return;
    }
    setWriteError({
      message: error instanceof TodoApiError ? error.message : UNKNOWN_START_FAILURE,
      lock: true,
    });
  };

  const settleAdvanceResponse = async (
    record: AdvanceRecord,
    response: TodoWorkflow,
    captured: number
  ): Promise<void> => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    if (response.workflow_id !== record.workflowId) {
      // A mutation response naming another workflow is invalid-response
      // evidence, never a reason to switch plans: retain the pending record
      // for an explicit retry and leave cache and selection untouched.
      // Nothing renders here because only the reconciliation GET seeds.
      setWriteError({ message: INVALID_RESPONSE, lock: true });
      return;
    }
    // The response is recovery evidence only: rendering waits for the
    // reconciliation GET below, which seeds via keepLatestWorkflow.
    noteTerminalOutcome(response);
    void queryClient.invalidateQueries({
      queryKey: ["todo-workflows", userId, "active"],
    });
    await reconcileAfterWrite(response.workflow_id, captured, {
      clearRecord: record,
      keepMessage: false,
      clearFirst: false,
    });
  };

  const settleAdvanceError = (record: AdvanceRecord, error: unknown, captured: number): void => {
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    if (error instanceof TodoApiError && error.kind === "conflict") {
      if (error.conflictCode === "stale_step") {
        // The stale explanation is sticky: reconciliation clears the
        // record but the message must survive the reconciled step so the
        // submitted stale answer stays explained after the current step
        // renders. The next write or manual reload clears it.
        setWriteError({ message: error.message, lock: true, sticky: true });
        void reconcileAfterWrite(record.workflowId, captured, {
          clearRecord: record,
          keepMessage: true,
          clearFirst: true,
        });
        return;
      }
      if (error.conflictCode === "request_id_reused") {
        setWriteError({ message: error.message, lock: true });
        void reconcileAfterWrite(record.workflowId, captured, {
          clearRecord: null,
          keepMessage: true,
          clearFirst: false,
        });
        return;
      }
      setWriteError({ message: error.message, lock: false });
      void reconcileAfterWrite(record.workflowId, captured, {
        clearRecord: record,
        keepMessage: true,
        clearFirst: true,
      });
      return;
    }
    if (error instanceof TodoApiError && error.kind === "validation") {
      setWriteError({ message: SERVER_INVALID, lock: false });
      void (async () => {
        await clearPendingRecord(record, captured);
      })();
      return;
    }
    if (error instanceof TodoApiError && error.kind === "not-found") {
      setWriteError({ message: error.message, lock: false });
      void (async () => {
        await clearPendingRecord(record, captured);
        void queryClient.invalidateQueries({
          queryKey: ["todo-workflows", userId, "active"],
        });
      })();
      return;
    }
    setWriteError({
      message: error instanceof TodoApiError ? error.message : UNKNOWN_ADVANCE_FAILURE,
      lock: true,
    });
  };

  const sendExactStoredRequest = (
    record: PendingWorkflowWrite,
    captured: number
  ): Promise<void> => {
    // Settlement (including the reconciliation GET) is part of the returned
    // promise, so the before-send sequence stays pending until the outcome
    // is reconciled.
    if (record.operation === "start") {
      return startMutation.mutateAsync(record).then(
        (response) => settleStartResponse(record, response, captured),
        (error: unknown) => {
          settleStartError(record, error, captured);
        }
      );
    }
    if (record.operation === "advance") {
      return advanceMutation.mutateAsync(record).then(
        (response) => settleAdvanceResponse(record, response, captured),
        (error: unknown) => {
          settleAdvanceError(record, error, captured);
        }
      );
    }
    return suggestionMutation.mutateAsync(record).then(
      (response) => settleSuggestionResponse(record, response, captured),
      (error: unknown) => {
        settleSuggestionError(record, error, captured);
      }
    );
  };

  const handleSaveFailure = async (
    record: PendingWorkflowWrite,
    captured: number
  ): Promise<void> => {
    let existing: PendingWorkflowWrite | null = null;
    try {
      existing = await pendingStore.read(userId);
    } catch {
      existing = null;
    }
    if (!mountedRef.current || !isSessionCurrent(captured)) return;
    if (existing !== null && existing.ownerId === userId) {
      setPendingRecord(existing);
      if (existing.requestId !== record.requestId) {
        setWriteError({ message: PENDING_EXISTS, lock: true });
      }
    } else {
      setPendingRecord(null);
      setWriteError({ message: STORAGE_FAILURE, lock: false });
    }
  };

  const persistAndSend = (
    record: PendingWorkflowWrite,
    replacedRecord: PendingWorkflowWrite | null = null,
  ): void => {
    if (busy.current) return;
    busy.current = true;
    setLocalError(null);
    setWriteError(null);
    const captured = sessionEpoch;
    liveRequestIds.current.add(record.requestId);
    if (record.operation === "suggest") {
      hydratedSuggestionRequestIds.current.delete(record.requestId);
    }
    setPersisting(true);
    // The write is in flight from here: surface it immediately so a second
    // write cannot replace it and the callbacks below only ever clear it.
    setPendingRecord(record);
    void (async () => {
      try {
        if (replacedRecord !== null) {
          await pendingStore.clear(userId, replacedRecord.requestId);
        }
        const outcome = await saveAndSendPendingWrite({
          record,
          store: pendingStore,
          sessionEpoch: captured,
          isSessionCurrent,
          send: (saved) => sendExactStoredRequest(saved, captured),
        });
        if (
          outcome === "stale-session" &&
          mountedRef.current &&
          isSessionCurrent(captured)
        ) {
          setPendingRecord(record);
        }
      } catch {
        await handleSaveFailure(record, captured);
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) setPersisting(false);
        busy.current = false;
      }
    })();
  };

  const startMutation = useMutation({
    mutationFn: (record: StartRecord) => api.startWorkflow(record.body),
  });

  const advanceMutation = useMutation({
    mutationFn: (record: AdvanceRecord) =>
      api.advanceWorkflow(record.workflowId, record.body),
  });

  const suggestionMutation = useMutation({
    mutationFn: (record: SuggestRecord) =>
      api.suggestWorkflow(record.workflowId, record.body),
  });

  const startPending = startMutation.isPending;
  const advancePending = advanceMutation.isPending;
  const suggestionPending = suggestionMutation.isPending;
  // `busy` stays a synchronous re-entrancy guard for handlers only: refs
  // must not be read during render, so the discard path mirrors it into
  // state (every other busy window already has a state flag). This also
  // disables the recovery buttons for the whole discard instead of only
  // after the next unrelated render.
  const [discarding, setDiscarding] = useState(false);
  const ioBusy =
    discarding || persisting || startPending || advancePending || suggestionPending ||
    suggestionFetching || reconciling;
  const buttonsDisabled =
    !fresh || isFetching || advancePending || suggestionPending || persisting ||
    suggestionFetching || reconciling || reconcileFailed || livePending !== null ||
    suggestionRecord?.status === "pending";
  const suggestionControlDisabled =
    !fresh || isFetching || suggestionPending || suggestionFetching || reconciling ||
    livePending !== null;
  const suggestionInFlight =
    suggestionPending ||
    suggestionFetching ||
    (persisting && livePending?.operation === "suggest");

  useEffect(() => {
    if (workflowQuery.data?.view.type === "completion") {
      const outcome = workflowQuery.data.view.outcome;
      if (outcome === "completed" || outcome === "cancelled") {
        void queryClient.invalidateQueries({ queryKey: ["todos"] });
        void queryClient.invalidateQueries({
          queryKey: ["todo-workflows", userId, "active"],
        });
      }
    }
  }, [workflowQuery.data, queryClient, userId]);

  useEffect(() => {
    if (focusSignal === focusedSignal.current) return;
    focusedSignal.current = focusSignal;
    if (view === undefined) {
      titleInput.current?.focus();
      return;
    }
    if (view.type === "yes_no") {
      AccessibilityInfo.announceForAccessibility(view.question);
    } else if (view.type === "unsupported") {
      AccessibilityInfo.announceForAccessibility("Unsupported step");
    } else {
      AccessibilityInfo.announceForAccessibility(view.title);
    }
    const focusButton = (ref: ControlRef) => {
      const control = ref.current as unknown as { focus?: () => void } | null;
      control?.focus?.();
      if (Platform.OS !== "web") {
        const node = findNodeHandle(ref.current);
        if (node !== null) AccessibilityInfo.setAccessibilityFocus(node);
      }
    };
    switch (view.type) {
      case "yes_no":
        focusButton(yesButton);
        break;
      case "task_breakdown":
        tasksInput.current?.focus();
        break;
      case "review":
        focusButton(confirmButton);
        break;
      default:
        focusButton(backButton);
        break;
    }
  }, [focusSignal, view]);

  const submitStart = () => {
    if (busy.current || startPending || persisting || livePending !== null) return;
    if (startDraft.trim() === "") {
      setLocalError(EMPTY_TITLE);
      return;
    }
    const canonical = normalizeTodoTitle(startDraft);
    if (canonical === null) {
      setLocalError(INVALID_TITLE);
      return;
    }
    const requestId = generateRequestId();
    persistAndSend({
      version: 1,
      ownerId: userId,
      requestId,
      operation: "start",
      body: { request_id: requestId, title: canonical },
    });
  };

  const submitAction = (action: TodoWorkflowAction) => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    if (livePending !== null) return;
    const cached = queryClient.getQueryData<TodoWorkflow>(
      workflowQueryKey(userId, workflowId)
    );
    if (
      cached === undefined ||
      cached.workflow_id !== workflowId
    ) {
      return;
    }
    const requestId = generateRequestId();
    persistAndSend({
      version: 1,
      ownerId: userId,
      requestId,
      operation: "advance",
      workflowId,
      body: {
        request_id: requestId,
        expected_revision: cached.revision,
        step_id: cached.view.step_id,
        action,
      },
    });
  };

  const sendAnswer = (actionId: string) => {
    submitAction({ action: "answer_multiple_steps", answer: actionId === "yes" });
  };

  const cancel = () => {
    submitAction({ action: "cancel" });
  };

  const confirm = () => {
    submitAction({ action: "confirm" });
  };

  const submitTasks = (bounds: { min_titles: number; max_titles: number }) => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    const lines = tasksDraft
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line !== "");
    if (lines.length < bounds.min_titles || lines.length > bounds.max_titles) {
      setLocalError(
        `Enter ${bounds.min_titles} to ${bounds.max_titles} todo titles, one per line.`
      );
      return;
    }
    const canonical: string[] = [];
    for (const line of lines) {
      const title = normalizeTodoTitle(line);
      if (title === null) {
        setLocalError(SERVER_INVALID);
        return;
      }
      canonical.push(title);
    }
    submitAction({ action: "submit_tasks", titles: canonical });
  };

  const changeTasksDraft = (value: string) => {
    // Draft edits are mirrored synchronously so a deferred provider cannot
    // observe the previous render's value.
    tasksDraftRef.current = value;
    tasksDraftEditCounterRef.current += 1;
    setTasksDraft(value);
    setTasksDraftEditCounter((counter) => counter + 1);
  };

  const startSuggestion = (allowPending = false) => {
    if (
      workflowId === null ||
      busy.current ||
      (buttonsDisabled && !(allowPending && suggestionRecord?.status === "pending")) ||
      suggestionPending ||
      suggestionFetching ||
      view?.type !== "task_breakdown"
    ) {
      return;
    }
    const cached = queryClient.getQueryData<TodoWorkflow>(
      workflowQueryKey(userId, workflowId)
    );
    if (cached === undefined || cached.workflow_id !== workflowId) return;
    const requestId = generateRequestId();
    setSuggestionError(null);
    setNewSuggestionWarning(false);
    persistAndSend(
      {
        version: 1,
        ownerId: userId,
        requestId,
        operation: "suggest",
        workflowId,
        body: {
          request_id: requestId,
          expected_revision: cached.revision,
          step_id: cached.view.step_id,
        },
      },
      allowPending && livePending?.operation === "suggest" ? livePending : null,
    );
  };

  const checkSuggestionStatus = () => {
    if (workflowId === null || busy.current || ioBusy || view?.type !== "task_breakdown") return;
    const captured = sessionEpoch;
    const id = workflowId;
    setReconciling(true);
    void (async () => {
      try {
        const current = await fetchCurrentSnapshot(id, captured);
        if (!mountedRef.current || !isSessionCurrent(captured) || current === null) return;
        if (!current.ok || current.snapshot.view.type !== "task_breakdown") {
          if (!current.ok) setWriteError({ message: current.message, lock: true });
          return;
        }
        await fetchSuggestionRecord(
          id,
          captured,
          current.snapshot.revision,
          current.snapshot.view.step_id,
          tasksDraftEditCounterRef.current,
        );
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) setReconciling(false);
      }
    })();
  };

  const retryPending = () => {
    const record = livePending;
    if (
      record === null ||
      busy.current ||
      persisting ||
      startPending ||
      advancePending ||
      suggestionPending ||
      suggestionFetching ||
      reconciling
    ) {
      return;
    }
    if (record.operation !== "suggest") {
      persistAndSend(record);
      return;
    }
    const captured = sessionEpoch;
    setReconciling(true);
    void (async () => {
      try {
        const current = await fetchCurrentSnapshot(record.workflowId, captured);
        if (!mountedRef.current || !isSessionCurrent(captured) || current === null) return;
        if (
          !current.ok ||
          current.snapshot.revision !== record.body.expected_revision ||
          current.snapshot.view.step_id !== record.body.step_id
        ) {
          if (!current.ok) setWriteError({ message: current.message, lock: true });
          else {
            await clearPendingRecord(record, captured);
            if (mountedRef.current && isSessionCurrent(captured)) {
              setWriteError({ message: "This suggestion request is no longer current.", lock: false });
            }
          }
          return;
        }
        persistAndSend(record);
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) setReconciling(false);
      }
    })();
  };

  const discardPending = () => {
    const record = livePending;
    if (
      record === null ||
      busy.current ||
      persisting ||
      startPending ||
      advancePending ||
      suggestionPending ||
      suggestionFetching ||
      reconciling
    ) {
      return;
    }
    if (record.operation === "suggest" && !discardSuggestionWarning) {
      setDiscardSuggestionWarning(true);
      return;
    }
    busy.current = true;
    const captured = sessionEpoch;
    setDiscarding(true);
    void (async () => {
      try {
        if (record.operation === "suggest") {
          const current = await fetchCurrentSnapshot(record.workflowId, captured);
          if (!mountedRef.current || !isSessionCurrent(captured) || current === null) return;
          if (!current.ok) {
            setReconcileFailed(true);
            setWriteError({ message: current.message, lock: true });
            return;
          }
        }
        await pendingStore.clear(userId, record.requestId);
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        setPendingRecord(null);
        setDiscardSuggestionWarning(false);
        setWriteError({ message: DISCARD_WARNING, lock: false });
        void queryClient.invalidateQueries({
          queryKey: ["todo-workflows", userId, "active"],
        });
        if (record.operation === "advance") {
          const fetched = await fetchCurrentSnapshot(record.workflowId, captured);
          if (!mountedRef.current || !isSessionCurrent(captured)) return;
          if (fetched === null) return;
          if (fetched.ok) {
            noteTerminalOutcome(fetched.snapshot);
          } else {
            setReconcileFailed(true);
            setWriteError({ message: fetched.message, lock: true });
          }
        }
      } catch {
        if (mountedRef.current && isSessionCurrent(captured)) {
          setPendingRecord(record);
          setDiscardSuggestionWarning(false);
          setWriteError({ message: RECOVERY_PENDING, lock: true });
        }
      } finally {
        busy.current = false;
        if (mountedRef.current && isSessionCurrent(captured)) setDiscarding(false);
      }
    })();
  };

  const reload = () => {
    if (workflowQueryRef.current.isFetching) return;
    const captured = sessionEpoch;
    const record = livePending;
    setReconcileFailed(false);
    setReconciling(true);
    void (async () => {
      try {
        const result = await workflowQueryRef.current.refetch();
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        if (result.isError || result.data === undefined) {
          setReconcileFailed(true);
          setWriteError({ message: messageForGetError(result.error), lock: true });
          return;
        }
        // A successful manual reload proves the same outcome the automatic
        // reconciliation would have: the retained request is resolved.
        if (record !== null) {
          try {
            await pendingStore.clear(userId, record.requestId);
          } catch {
            // A deferred clear can reject after the session changed: like
            // every other deferred callback, it must not touch state then.
            if (!mountedRef.current || !isSessionCurrent(captured)) return;
            setPendingRecord(record);
            setReconcileFailed(true);
            setWriteError({ message: RECOVERY_PENDING, lock: true });
            return;
          }
          // The clear resolved after an unknown wait: re-check the session
          // before consuming it, so a stale reload cannot clear the retry.
          if (!mountedRef.current || !isSessionCurrent(captured)) return;
          setPendingRecord(null);
        }
        setReconcileFailed(false);
        setWriteError(null);
        noteTerminalOutcome(result.data);
      } finally {
        if (mountedRef.current && isSessionCurrent(captured)) setReconciling(false);
      }
    })();
  };

  const showWriteError =
    writeError !== null &&
    (writeError.sticky === true ||
      (!writeError.lock || !fresh || livePending !== null || reconcileFailed));
  const getAlert =
    getError !== null &&
    !isFetching &&
    !(getError instanceof StaleWorkflowSessionError)
      ? messageForGetError(getError)
      : null;
  const alert = localError ?? (showWriteError && writeError ? writeError.message : null) ?? getAlert;

  const reloadVisible =
    !definitionUnsupported &&
    view?.type !== "unsupported" &&
    (reconcileFailed ||
      (hasData && isStale && !isFetching) ||
      (workflowId !== null && !hasData && getAlert !== null));

  const renderView = () => {
    if (definitionUnsupported) {
      return (
        <UnsupportedTemplate
          key="unsupported-definition"
          onExit={onExit}
          onReload={reload}
          backRef={backButton}
        />
      );
    }
    if (view === undefined) {
      return (
        <WorkflowStartScreen
          draft={startDraft}
          onChangeDraft={setStartDraft}
          onSubmit={submitStart}
          onExit={onExit}
          exitDisabled={startPending || persisting}
          submitDisabled={startPending || persisting || livePending !== null}
          submitting={startPending || persisting}
          inputRef={titleInput}
          backRef={backButton}
        />
      );
    }
    switch (view.type) {
      case "yes_no": {
        const Template = templateRegistry.yes_no;
        return (
          <Template
            key={view.step_id}
            view={view}
            onAnswer={sendAnswer}
            onCancel={cancel}
            disabled={buttonsDisabled}
            submitting={advancePending}
            yesRef={yesButton}
          />
        );
      }
      case "task_breakdown": {
        const Template = templateRegistry.task_breakdown;
        return (
          <Template
            key={view.step_id}
            view={view}
            draft={tasksDraft}
            onChangeDraft={changeTasksDraft}
            onSubmit={submitTasks}
            onCancel={cancel}
            onSuggest={startSuggestion}
            onCheckSuggestion={checkSuggestionStatus}
            onStartAnother={() => setNewSuggestionWarning(true)}
            onApplySuggestions={() => {
              if (suggestionRecord === null || suggestionRecord.status !== "ready") return;
              if (tasksDraftRef.current !== "") {
                setReplaceSuggestions(true);
                return;
              }
              changeTasksDraft(suggestionRecord.proposed_titles.join("\n"));
            }}
            onReplaceSuggestions={() => {
              if (suggestionRecord === null || suggestionRecord.status !== "ready") return;
              changeTasksDraft(suggestionRecord.proposed_titles.join("\n"));
              setReplaceSuggestions(false);
            }}
            suggestion={suggestionRecord}
            suggestionError={suggestionError}
            suggestionControlsDisabled={suggestionControlDisabled}
            replaceSuggestions={replaceSuggestions}
            onCancelReplace={() => setReplaceSuggestions(false)}
            newSuggestionWarning={newSuggestionWarning}
            onConfirmStartAnother={() => {
              setNewSuggestionWarning(false);
              startSuggestion(true);
            }}
            onCancelStartAnother={() => setNewSuggestionWarning(false)}
            onWarnStartAnother={() => setNewSuggestionWarning(true)}
            disabled={buttonsDisabled}
            submitting={advancePending}
            suggesting={suggestionInFlight}
            inputRef={tasksInput}
          />
        );
      }
      case "review": {
        const Template = templateRegistry.review;
        return (
          <Template
            key={view.step_id}
            view={view}
            onConfirm={confirm}
            onCancel={cancel}
            disabled={buttonsDisabled}
            submitting={advancePending}
            confirmRef={confirmButton}
          />
        );
      }
      case "completion": {
        const Template = templateRegistry.completion;
        return <Template key={view.step_id} view={view} onExit={onExit} backRef={backButton} />;
      }
      case "unsupported":
        return (
          <UnsupportedTemplate
            key={view.step_id}
            onExit={onExit}
            onReload={reload}
            backRef={backButton}
          />
        );
    }
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}
      >
        {renderView()}
        {livePending !== null && (
          <View style={styles.screen}>
            {livePending.operation === "suggest" && discardSuggestionWarning && (
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                The earlier suggestion call may still finish or be billed. Discard its saved retry?
              </Text>
            )}
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Retry saved request"
              disabled={ioBusy}
              style={styles.addButton}
              onPress={retryPending}
            >
              <Text style={styles.addButtonText}>Retry saved request</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={
                livePending.operation === "suggest" && discardSuggestionWarning
                  ? "Discard saved suggestion anyway"
                  : "Discard saved request"
              }
              disabled={ioBusy}
              style={styles.refreshButton}
              onPress={discardPending}
            >
              <Text style={styles.refreshButtonText}>
                {livePending.operation === "suggest" && discardSuggestionWarning
                  ? "Discard saved suggestion anyway"
                  : "Discard saved request"}
              </Text>
            </Pressable>
          </View>
        )}
        {alert && (
          <Text accessibilityRole="alert" style={styles.error}>
            {alert}
          </Text>
        )}
        {workflowId !== null && !hasData && getAlert === null && (
          <Text style={styles.status}>Loading plan…</Text>
        )}
        {persisting && <Text style={styles.status}>Saving safe retry…</Text>}
        {reconciling && <Text style={styles.status}>Reloading plan…</Text>}
        {reloadVisible && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Reload plan"
            style={styles.refreshButton}
            onPress={reload}
          >
            <Text style={styles.refreshButtonText}>Reload plan</Text>
          </Pressable>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

type InputRef = RefObject<TextInput | null>;
type ControlRef = RefObject<View | null>;

function WorkflowStartScreen({
  draft,
  onChangeDraft,
  onSubmit,
  onExit,
  exitDisabled,
  submitDisabled,
  submitting,
  inputRef,
  backRef,
}: {
  draft: string;
  onChangeDraft: (value: string) => void;
  onSubmit: () => void;
  onExit: () => void;
  exitDisabled: boolean;
  submitDisabled: boolean;
  submitting: boolean;
  inputRef: InputRef;
  backRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Help me plan a task
      </Text>
      <Text style={styles.fieldLabel}>Task title</Text>
      <TextInput
        ref={inputRef}
        accessibilityLabel="Task title"
        editable={!submitDisabled}
        value={draft}
        returnKeyType="done"
        submitBehavior="submit"
        onChangeText={onChangeDraft}
        onSubmitEditing={onSubmit}
        placeholder="What needs planning?"
        style={styles.input}
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Start planning"
        disabled={submitDisabled}
        style={styles.addButton}
        onPress={onSubmit}
      >
        <Text style={styles.addButtonText}>Start planning</Text>
      </Pressable>
      {submitting && <Text style={styles.status}>Submitting…</Text>}
      <Pressable
        ref={backRef}
        accessibilityRole="button"
        accessibilityLabel="Back to todos"
        disabled={exitDisabled}
        style={styles.refreshButton}
        onPress={onExit}
      >
        <Text style={styles.refreshButtonText}>Back to todos</Text>
      </Pressable>
    </View>
  );
}

function YesNoTemplate({
  view,
  onAnswer,
  onCancel,
  disabled,
  submitting,
  yesRef,
}: {
  view: Extract<TodoWorkflow["view"], { type: "yes_no" }>;
  onAnswer: (actionId: string) => void;
  onCancel: () => void;
  disabled: boolean;
  submitting: boolean;
  yesRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text style={styles.fieldLabel}>{view.title}</Text>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        {view.question}
      </Text>
      {view.actions.map((action, index) => (
        <Pressable
          key={action.id}
          ref={index === 0 ? yesRef : undefined}
          accessibilityRole="button"
          accessibilityLabel={action.label}
          disabled={disabled}
          style={index === 0 ? styles.addButton : styles.refreshButton}
          onPress={() => onAnswer(action.id)}
        >
          <Text style={index === 0 ? styles.addButtonText : styles.refreshButtonText}>
            {action.label}
          </Text>
        </Pressable>
      ))}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Cancel planning"
        disabled={disabled}
        style={styles.refreshButton}
        onPress={onCancel}
      >
        <Text style={styles.refreshButtonText}>Cancel planning</Text>
      </Pressable>
      {submitting && <Text style={styles.status}>Submitting…</Text>}
    </View>
  );
}

function TaskBreakdownTemplate({
  view,
  onChangeDraft,
  onSubmit,
  onCancel,
  onSuggest,
  onCheckSuggestion,
  onStartAnother,
  onApplySuggestions,
  onReplaceSuggestions,
  onCancelReplace,
  suggestion,
  suggestionError,
  suggestionControlsDisabled,
  replaceSuggestions,
  newSuggestionWarning,
  onConfirmStartAnother,
  onCancelStartAnother,
  suggesting,
  disabled,
  submitting,
  inputRef,
  draft,
}: {
  view: Extract<TodoWorkflow["view"], { type: "task_breakdown" }>;
  draft: string;
  onChangeDraft: (value: string) => void;
  onSubmit: (bounds: { min_titles: number; max_titles: number }) => void;
  onCancel: () => void;
  onSuggest: () => void;
  onCheckSuggestion: () => void;
  onStartAnother: () => void;
  onApplySuggestions: () => void;
  onReplaceSuggestions: () => void;
  onCancelReplace: () => void;
  suggestion: WorkflowSuggestion | null;
  suggestionError: string | null;
  suggestionControlsDisabled: boolean;
  replaceSuggestions: boolean;
  newSuggestionWarning: boolean;
  onConfirmStartAnother: () => void;
  onCancelStartAnother: () => void;
  onWarnStartAnother?: () => void;
  suggesting: boolean;
  disabled: boolean;
  submitting: boolean;
  inputRef: InputRef;
}) {
  const hasEditedDraft = draft !== "";
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        {view.title}
      </Text>
      <Text style={styles.fieldLabel}>Todo titles (one per line)</Text>
      <TextInput
        ref={inputRef}
        accessibilityLabel="Todo titles (one per line)"
        editable={!disabled || suggesting || suggestion?.status === "pending"}
        value={draft}
        multiline
        onChangeText={onChangeDraft}
        onSubmitEditing={() =>
          onSubmit({ min_titles: view.min_titles, max_titles: view.max_titles })
        }
        placeholder={"Send invitations\nBuy decorations"}
        style={[styles.input, styles.multilineInput]}
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Save tasks"
        disabled={disabled}
        style={styles.addButton}
        onPress={() =>
          onSubmit({ min_titles: view.min_titles, max_titles: view.max_titles })
        }
      >
        <Text style={styles.addButtonText}>Save tasks</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Suggest todos"
        disabled={suggestionControlsDisabled || suggesting}
        style={styles.refreshButton}
        onPress={onSuggest}
      >
        <Text style={styles.refreshButtonText}>Suggest todos</Text>
      </Pressable>
      {suggesting && (
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          Getting todo suggestions…
        </Text>
      )}
      {suggestionError !== null && (
        <Text accessibilityLiveRegion="polite" style={styles.status}>
          {suggestionError}
        </Text>
      )}
      {suggestion?.status === "pending" && !suggesting && (
        <View style={styles.screen}>
          <Text accessibilityLiveRegion="polite" style={styles.status}>
            Suggestions are still being generated. The earlier request may still finish.
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Check status"
            disabled={suggestionControlsDisabled}
            style={styles.refreshButton}
            onPress={onCheckSuggestion}
          >
            <Text style={styles.refreshButtonText}>Check status</Text>
          </Pressable>
          {!newSuggestionWarning ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Start another request"
              disabled={suggestionControlsDisabled}
              style={styles.refreshButton}
              onPress={onStartAnother}
            >
              <Text style={styles.refreshButtonText}>Start another request</Text>
            </Pressable>
          ) : (
            <View style={styles.screen}>
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                Starting another request may bill the earlier request too.
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Start another request anyway"
                disabled={suggestionControlsDisabled}
                style={styles.addButton}
                onPress={onConfirmStartAnother}
              >
                <Text style={styles.addButtonText}>Start another request anyway</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Cancel new request"
                disabled={suggestionControlsDisabled}
                style={styles.refreshButton}
                onPress={onCancelStartAnother}
              >
                <Text style={styles.refreshButtonText}>Cancel</Text>
              </Pressable>
            </View>
          )}
        </View>
      )}
      {suggestion?.status === "failed" && !suggesting && (
        <View style={styles.screen}>
          <Text accessibilityLiveRegion="polite" style={styles.status}>
            Suggestions are unavailable. You can enter todo titles manually.
          </Text>
          <Pressable
          accessibilityRole="button"
          accessibilityLabel="Try suggestions again"
          disabled={disabled}
          style={styles.refreshButton}
          onPress={onSuggest}
        >
            <Text style={styles.refreshButtonText}>Try suggestions again</Text>
          </Pressable>
        </View>
      )}
      {suggestion?.status === "ready" && !suggesting && (
        <View style={styles.screen}>
          <Text accessibilityLiveRegion="polite" style={styles.status}>
            Saved suggestions are ready to review.
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Apply saved suggestions"
            disabled={disabled}
            style={styles.refreshButton}
            onPress={onApplySuggestions}
          >
            <Text style={styles.refreshButtonText}>Apply saved suggestions</Text>
          </Pressable>
          {replaceSuggestions && hasEditedDraft && (
            <View style={styles.screen}>
              <Text accessibilityLiveRegion="polite" style={styles.status}>
                Replace your edited draft with the saved suggestions?
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Replace draft with saved suggestions"
                disabled={disabled}
                style={styles.addButton}
                onPress={onReplaceSuggestions}
              >
                <Text style={styles.addButtonText}>Replace draft</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Keep edited draft"
                disabled={disabled}
                style={styles.refreshButton}
                onPress={onCancelReplace}
              >
                <Text style={styles.refreshButtonText}>Keep edited draft</Text>
              </Pressable>
            </View>
          )}
        </View>
      )}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Cancel planning"
        disabled={disabled}
        style={styles.refreshButton}
        onPress={onCancel}
      >
        <Text style={styles.refreshButtonText}>Cancel planning</Text>
      </Pressable>
      {submitting && <Text style={styles.status}>Submitting…</Text>}
    </View>
  );
}

function ReviewTemplate({
  view,
  onConfirm,
  onCancel,
  disabled,
  submitting,
  confirmRef,
}: {
  view: Extract<TodoWorkflow["view"], { type: "review" }>;
  onConfirm: () => void;
  onCancel: () => void;
  disabled: boolean;
  submitting: boolean;
  confirmRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        {view.title}
      </Text>
      {view.proposed_titles.map((title, index) => (
        <Text
          key={`${index}-${title}`}
          accessibilityLabel={`Proposed todo ${index + 1} of ${view.proposed_titles.length}: ${title}`}
          style={styles.todoTitle}
        >
          {title}
        </Text>
      ))}
      <Pressable
        ref={confirmRef}
        accessibilityRole="button"
        accessibilityLabel="Confirm plan"
        disabled={disabled}
        style={styles.addButton}
        onPress={onConfirm}
      >
        <Text style={styles.addButtonText}>Confirm plan</Text>
      </Pressable>
      {submitting && <Text style={styles.status}>Submitting…</Text>}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Cancel planning"
        disabled={disabled}
        style={styles.refreshButton}
        onPress={onCancel}
      >
        <Text style={styles.refreshButtonText}>Cancel planning</Text>
      </Pressable>
    </View>
  );
}

function CompletionTemplate({
  view,
  onExit,
  backRef,
}: {
  view: Extract<TodoWorkflow["view"], { type: "completion" }>;
  onExit: () => void;
  backRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        {view.title}
      </Text>
      {view.created_todos.map((todo, index) => (
        <Text
          key={todo.id}
          accessibilityLabel={`Created todo ${index + 1} of ${view.created_todos.length}: ${todo.title}`}
          style={styles.todoTitle}
        >
          {todo.title}
        </Text>
      ))}
      <Pressable
        ref={backRef}
        accessibilityRole="button"
        accessibilityLabel="Back to todos"
        style={styles.refreshButton}
        onPress={onExit}
      >
        <Text style={styles.refreshButtonText}>Back to todos</Text>
      </Pressable>
    </View>
  );
}

function UnsupportedTemplate({
  onExit,
  onReload,
  backRef,
}: {
  onExit: () => void;
  onReload: () => void;
  backRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Unsupported step
      </Text>
      <Text style={styles.empty}>This planning step needs a newer app version.</Text>
      <Pressable
        ref={backRef}
        accessibilityRole="button"
        accessibilityLabel="Back to todos"
        style={styles.refreshButton}
        onPress={onExit}
      >
        <Text style={styles.refreshButtonText}>Back to todos</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Reload plan"
        style={styles.refreshButton}
        onPress={onReload}
      >
        <Text style={styles.refreshButtonText}>Reload plan</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
    gap: 16,
    padding: 24,
  },
  screen: {
    gap: 10,
  },
  heading: {
    color: "#172033",
    fontSize: 32,
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
  multilineInput: {
    minHeight: 132,
    paddingVertical: 12,
    textAlignVertical: "top",
  },
  addButton: {
    alignItems: "center",
    backgroundColor: "#2457d6",
    borderRadius: 10,
    justifyContent: "center",
    minHeight: 48,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  addButtonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  refreshButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  refreshButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
  error: {
    color: "#b42318",
    fontSize: 15,
  },
  status: {
    color: "#42526b",
    fontSize: 15,
  },
  empty: {
    color: "#66758a",
    fontSize: 16,
    paddingVertical: 12,
  },
  todoTitle: {
    color: "#172033",
    fontSize: 17,
  },
});
