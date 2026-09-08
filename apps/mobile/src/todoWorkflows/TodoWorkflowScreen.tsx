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
  const [localError, setLocalError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<{ message: string; lock: boolean } | null>(
    null
  );
  const [pendingRecord, setPendingRecord] = useState<PendingWorkflowWrite | null>(null);
  const [persisting, setPersisting] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const [reconcileFailed, setReconcileFailed] = useState(false);
  const [focusSignal, setFocusSignal] = useState(0);
  const busy = useRef(false);
  const mountedRef = useRef(true);
  const reconcileAbortRef = useRef<AbortController | null>(null);
  const focusedSignal = useRef(-1);
  const previousStepId = useRef<string | null>(null);
  const titleInput = useRef<TextInput>(null);
  const tasksInput = useRef<TextInput>(null);
  const yesButton = useRef<View>(null);
  const confirmButton = useRef<View>(null);
  const backButton = useRef<View>(null);

  useEffect(() => () => {
    mountedRef.current = false;
    reconcileAbortRef.current?.abort();
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
        record.operation === "advance" ? record.workflowId : null;
      setPendingRecord(record);
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
  // Mirror render values for async callbacks without touching refs
  // during render. Declared before the step effect so mirrors are fresh
  // when it runs.
  useEffect(() => {
    workflowQueryRef.current = workflowQuery;
    pendingRecordRef.current = pendingRecord;
    reconcileFailedRef.current = reconcileFailed;
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
    setTasksDraft("");
    setLocalError(null);
    // An arrived step clears alerts only when no recovery is outstanding:
    // a pending write or a failed reconciliation owns the message.
    if (pendingRecordRef.current === null && !reconcileFailedRef.current) {
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
        setWriteError({ message: error.message, lock: true });
        void reconcileAfterWrite(record.workflowId, captured, {
          clearRecord: record,
          keepMessage: false,
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
    return advanceMutation.mutateAsync(record).then(
      (response) => settleAdvanceResponse(record, response, captured),
      (error: unknown) => {
        settleAdvanceError(record, error, captured);
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

  const persistAndSend = (record: PendingWorkflowWrite): void => {
    if (busy.current) return;
    busy.current = true;
    setLocalError(null);
    setWriteError(null);
    const captured = sessionEpoch;
    setPersisting(true);
    // The write is in flight from here: surface it immediately so a second
    // write cannot replace it and the callbacks below only ever clear it.
    setPendingRecord(record);
    void (async () => {
      try {
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

  const startPending = startMutation.isPending;
  const advancePending = advanceMutation.isPending;
  // `busy` stays a synchronous re-entrancy guard for handlers only: refs
  // must not be read during render, so the discard path mirrors it into
  // state (every other busy window already has a state flag). This also
  // disables the recovery buttons for the whole discard instead of only
  // after the next unrelated render.
  const [discarding, setDiscarding] = useState(false);
  const ioBusy =
    discarding || persisting || startPending || advancePending || reconciling;
  const buttonsDisabled =
    !fresh || isFetching || advancePending || persisting || reconciling ||
    reconcileFailed ||
    livePending !== null;

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

  const retryPending = () => {
    const record = livePending;
    if (
      record === null ||
      busy.current ||
      persisting ||
      startPending ||
      advancePending ||
      reconciling
    ) {
      return;
    }
    persistAndSend(record);
  };

  const discardPending = () => {
    const record = livePending;
    if (
      record === null ||
      busy.current ||
      persisting ||
      startPending ||
      advancePending ||
      reconciling
    ) {
      return;
    }
    busy.current = true;
    const captured = sessionEpoch;
    setDiscarding(true);
    void (async () => {
      try {
        await pendingStore.clear(userId, record.requestId);
        if (!mountedRef.current || !isSessionCurrent(captured)) return;
        setPendingRecord(null);
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
    (!writeError.lock || !fresh || livePending !== null || reconcileFailed);
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
            onChangeDraft={setTasksDraft}
            onSubmit={submitTasks}
            onCancel={cancel}
            disabled={buttonsDisabled}
            submitting={advancePending}
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
              accessibilityLabel="Discard saved request"
              disabled={ioBusy}
              style={styles.refreshButton}
              onPress={discardPending}
            >
              <Text style={styles.refreshButtonText}>Discard saved request</Text>
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
  disabled: boolean;
  submitting: boolean;
  inputRef: InputRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        {view.title}
      </Text>
      <Text style={styles.fieldLabel}>Todo titles (one per line)</Text>
      <TextInput
        ref={inputRef}
        accessibilityLabel="Todo titles (one per line)"
        editable={!disabled}
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
