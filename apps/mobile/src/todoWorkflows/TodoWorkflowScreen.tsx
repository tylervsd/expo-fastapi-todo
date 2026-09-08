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

export function workflowQueryKey(userId: string, workflowId: string) {
  return ["todo-workflow", userId, workflowId] as const;
}

const EMPTY_TITLE = "Enter a task title.";
const INVALID_TITLE = "Check the plan title and try again.";
const SERVER_INVALID = "Check the plan details and try again.";
const LOST_START = "The result may be unknown. Starting again may create another draft.";
const UNCERTAIN = "The result may be unknown. Reload this plan before trying again.";

function serverCopy(error: unknown, uncertain: string): { message: string; lock: boolean } {
  if (error instanceof TodoApiError) {
    if (error.kind === "validation") return { message: SERVER_INVALID, lock: false };
    if (error.kind === "conflict") return { message: error.message, lock: true };
  }
  return { message: uncertain, lock: true };
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
}: {
  userId: string;
  api: TodoWorkflowScreenApi;
  onExit: () => void;
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [startDraft, setStartDraft] = useState("");
  const [tasksDraft, setTasksDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<{ message: string; lock: boolean } | null>(
    null
  );
  const [focusSignal, setFocusSignal] = useState(0);
  const busy = useRef(false);
  const focusedSignal = useRef(-1);
  const previousStepId = useRef<string | null>(null);
  const titleInput = useRef<TextInput>(null);
  const tasksInput = useRef<TextInput>(null);
  const yesButton = useRef<View>(null);
  const confirmButton = useRef<View>(null);
  const backButton = useRef<View>(null);

  const workflowQuery = useQuery({
    queryKey:
      workflowId === null
        ? (["todo-workflow", userId, "new"] as const)
        : workflowQueryKey(userId, workflowId),
    queryFn: ({ signal }) => api.getWorkflow(workflowId as string, { signal }),
    enabled: workflowId !== null,
  });

  const snapshot = workflowId === null ? undefined : workflowQuery.data;
  const view = snapshot?.view;
  const stepId = view?.step_id;
  const hasData = snapshot !== undefined;
  const isFetching = workflowQuery.isFetching;
  const isStale = workflowQuery.isStale;
  const fresh = hasData && !isStale;

  useEffect(() => {
    if (stepId === undefined || stepId === previousStepId.current) return;
    previousStepId.current = stepId;
    setTasksDraft("");
    setLocalError(null);
    setWriteError(null);
    setFocusSignal((signal) => signal + 1);
  }, [stepId]);

  const seedSnapshot = (workflow: TodoWorkflow) => {
    queryClient.setQueryData(workflowQueryKey(userId, workflow.workflow_id), workflow);
    setWorkflowId(workflow.workflow_id);
    setLocalError(null);
    setWriteError(null);
  };

  const startMutation = useMutation({
    mutationFn: (title: string) => api.startWorkflow(title),
    onSuccess: (workflow) => {
      seedSnapshot(workflow);
    },
    onError: (error: unknown) => {
      if (error instanceof TodoApiError && error.kind === "validation") {
        setWriteError({ message: SERVER_INVALID, lock: false });
      } else {
        setWriteError(serverCopy(error, LOST_START));
      }
    },
    onSettled: () => {
      busy.current = false;
    },
  });

  const advanceMutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: TodoWorkflowAction }) =>
      api.advanceWorkflow(id, action),
    onSuccess: (workflow, { id }) => {
      queryClient.setQueryData(workflowQueryKey(userId, id), workflow);
      setLocalError(null);
      setWriteError(null);
    },
    onError: (error: unknown) => {
      if (error instanceof TodoApiError && error.kind === "validation") {
        setWriteError({ message: SERVER_INVALID, lock: false });
      } else {
        setWriteError(serverCopy(error, UNCERTAIN));
        if (workflowId !== null) {
          void queryClient.invalidateQueries({
            queryKey: workflowQueryKey(userId, workflowId),
            refetchType: "none",
          });
          if (error instanceof TodoApiError && error.kind === "conflict") {
            void workflowQuery.refetch();
          }
        }
      }
    },
    onSettled: () => {
      busy.current = false;
    },
  });

  const startPending = startMutation.isPending;
  const advancePending = advanceMutation.isPending;
  const buttonsDisabled = !fresh || isFetching || advancePending;

  useEffect(() => {
    if (workflowQuery.data?.view.type === "completion") {
      const outcome = workflowQuery.data.view.outcome;
      if (outcome === "completed") {
        void queryClient.invalidateQueries({ queryKey: ["todos"] });
      }
    }
  }, [workflowQuery.data, queryClient]);

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
    if (busy.current || startPending) return;
    if (startDraft.trim() === "") {
      setLocalError(EMPTY_TITLE);
      return;
    }
    const canonical = normalizeTodoTitle(startDraft);
    if (canonical === null) {
      setLocalError(INVALID_TITLE);
      return;
    }
    busy.current = true;
    setLocalError(null);
    setWriteError(null);
    startMutation.mutate(canonical);
  };

  const sendAnswer = (actionId: string) => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    busy.current = true;
    setLocalError(null);
    advanceMutation.mutate({
      id: workflowId,
      action: { action: "answer_multiple_steps", answer: actionId === "yes" },
    });
  };

  const cancel = () => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    busy.current = true;
    setLocalError(null);
    advanceMutation.mutate({ id: workflowId, action: { action: "cancel" } });
  };

  const confirm = () => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    busy.current = true;
    setLocalError(null);
    advanceMutation.mutate({ id: workflowId, action: { action: "confirm" } });
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
    busy.current = true;
    setLocalError(null);
    advanceMutation.mutate({ id: workflowId, action: { action: "submit_tasks", titles: canonical } });
  };

  const reload = () => {
    if (!hasData || workflowQuery.isFetching) return;
    void workflowQuery.refetch();
  };

  const showWriteError =
    writeError !== null && (!writeError.lock || !fresh);
  const alert = localError ?? (showWriteError && writeError ? writeError.message : null);

  const reloadVisible = hasData && isStale && !isFetching && view?.type !== "unsupported";

  const renderView = () => {
    if (view === undefined) {
      return (
        <WorkflowStartScreen
          draft={startDraft}
          onChangeDraft={setStartDraft}
          onSubmit={submitStart}
          onExit={onExit}
          exitDisabled={startPending}
          submitDisabled={startPending}
          submitting={startPending}
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
        {alert && (
          <Text accessibilityRole="alert" style={styles.error}>
            {alert}
          </Text>
        )}
        {workflowId !== null && !hasData && (
          <Text style={styles.status}>Loading plan…</Text>
        )}
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
  draft,
  onChangeDraft,
  onSubmit,
  onCancel,
  disabled,
  submitting,
  inputRef,
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
