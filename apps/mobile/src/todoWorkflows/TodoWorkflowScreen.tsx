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
  type TodoWorkflowState,
} from "../todos/todoApi";

export type TodoWorkflowScreenApi = {
  startWorkflow: (title: string) => Promise<TodoWorkflow>;
  getWorkflow: (
    id: string,
    options: { signal: AbortSignal }
  ) => Promise<TodoWorkflow>;
  advanceWorkflow: (id: string, action: TodoWorkflowAction) => Promise<TodoWorkflow>;
};

export function workflowQueryKey(userId: string, workflowId: string) {
  return ["todo-workflow", userId, workflowId] as const;
}

const EMPTY_TITLE = "Enter a task title.";
const INVALID_TITLE = "Check the plan title and try again.";
const INVALID_TASKS = "Enter 2 to 10 todo titles, one per line.";
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
  const hasData = snapshot !== undefined;
  const isFetching = workflowQuery.isFetching;
  const isStale = workflowQuery.isStale;
  const fresh = hasData && !isStale;

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

  const announcedState = useRef<TodoWorkflowState | null>(null);
  useEffect(() => {
    if (snapshot === undefined || snapshot.state === announcedState.current) return;
    announcedState.current = snapshot.state;
    setFocusSignal((signal) => signal + 1);
  }, [snapshot]);

  useEffect(() => {
    if (snapshot?.state === "COMPLETED") {
      void queryClient.invalidateQueries({ queryKey: ["todos"] });
    }
  }, [queryClient, snapshot?.state]);

  useEffect(() => {
    if (focusSignal === focusedSignal.current) return;
    focusedSignal.current = focusSignal;
    if (snapshot === undefined) {
      titleInput.current?.focus();
      return;
    }
    const step: string = {
      ASSESS_TASK: "Does this task involve multiple steps?",
      COLLECT_TASKS: "Break it into smaller todos",
      REVIEW: "Review your plan",
      COMPLETED: "Plan complete",
      CANCELLED: "Plan cancelled",
    }[snapshot.state] ?? snapshot.state;
    AccessibilityInfo.announceForAccessibility(step);
    const focusButton = (ref: ControlRef) => {
      const control = ref.current as unknown as { focus?: () => void } | null;
      control?.focus?.();
      if (Platform.OS !== "web") {
        const node = findNodeHandle(ref.current);
        if (node !== null) AccessibilityInfo.setAccessibilityFocus(node);
      }
    };
    switch (snapshot.state) {
      case "ASSESS_TASK":
        focusButton(yesButton);
        break;
      case "COLLECT_TASKS":
        tasksInput.current?.focus();
        break;
      case "REVIEW":
        focusButton(confirmButton);
        break;
      default:
        focusButton(backButton);
        break;
    }
  }, [focusSignal, snapshot]);

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

  const sendAction = (action: TodoWorkflowAction) => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    busy.current = true;
    setLocalError(null);
    advanceMutation.mutate({ id: workflowId, action });
  };

  const submitTasks = () => {
    if (workflowId === null || busy.current || buttonsDisabled) return;
    const lines = tasksDraft
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line !== "");
    if (lines.length < 2 || lines.length > 10) {
      setLocalError(INVALID_TASKS);
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

  const reloadVisible = hasData && isStale && !isFetching;

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}
      >
        {snapshot === undefined && (
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
        )}
        {snapshot?.state === "ASSESS_TASK" && (
          <AssessTaskScreen
            onAnswer={(answer) =>
              sendAction({ action: "answer_multiple_steps", answer })
            }
            onCancel={() => sendAction({ action: "cancel" })}
            disabled={buttonsDisabled}
            submitting={advancePending}
            yesRef={yesButton}
          />
        )}
        {snapshot?.state === "COLLECT_TASKS" && (
          <CollectTasksScreen
            draft={tasksDraft}
            onChangeDraft={setTasksDraft}
            onSubmit={submitTasks}
            onCancel={() => sendAction({ action: "cancel" })}
            disabled={buttonsDisabled}
            submitting={advancePending}
            inputRef={tasksInput}
          />
        )}
        {snapshot?.state === "REVIEW" && (
          <ReviewWorkflowScreen
            titles={[...snapshot.context.proposed_todo_titles]}
            onConfirm={() => sendAction({ action: "confirm" })}
            onCancel={() => sendAction({ action: "cancel" })}
            disabled={buttonsDisabled}
            submitting={advancePending}
            confirmRef={confirmButton}
          />
        )}
        {snapshot?.state === "COMPLETED" && (
          <CompletedWorkflowScreen
            created={(snapshot.result?.created_todos ?? []).map((todo) => ({
              id: todo.id,
              title: todo.title,
            }))}
            onExit={onExit}
            backRef={backButton}
          />
        )}
        {snapshot?.state === "CANCELLED" && (
          <CancelledWorkflowScreen onExit={onExit} backRef={backButton} />
        )}
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

function AssessTaskScreen({
  onAnswer,
  onCancel,
  disabled,
  submitting,
  yesRef,
}: {
  onAnswer: (answer: boolean) => void;
  onCancel: () => void;
  disabled: boolean;
  submitting: boolean;
  yesRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Does this task involve multiple steps?
      </Text>
      <Pressable
        ref={yesRef}
        accessibilityRole="button"
        accessibilityLabel="Yes"
        disabled={disabled}
        style={styles.addButton}
        onPress={() => onAnswer(true)}
      >
        <Text style={styles.addButtonText}>Yes</Text>
      </Pressable>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="No"
        disabled={disabled}
        style={styles.refreshButton}
        onPress={() => onAnswer(false)}
      >
        <Text style={styles.refreshButtonText}>No</Text>
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

function CollectTasksScreen({
  draft,
  onChangeDraft,
  onSubmit,
  onCancel,
  disabled,
  submitting,
  inputRef,
}: {
  draft: string;
  onChangeDraft: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  disabled: boolean;
  submitting: boolean;
  inputRef: InputRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Break it into smaller todos
      </Text>
      <Text style={styles.fieldLabel}>Todo titles (one per line)</Text>
      <TextInput
        ref={inputRef}
        accessibilityLabel="Todo titles (one per line)"
        editable={!disabled}
        value={draft}
        multiline
        onChangeText={onChangeDraft}
        onSubmitEditing={onSubmit}
        placeholder={"Send invitations\nBuy decorations"}
        style={[styles.input, styles.multilineInput]}
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Save tasks"
        disabled={disabled}
        style={styles.addButton}
        onPress={onSubmit}
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

function ReviewWorkflowScreen({
  titles,
  onConfirm,
  onCancel,
  disabled,
  submitting,
  confirmRef,
}: {
  titles: string[];
  onConfirm: () => void;
  onCancel: () => void;
  disabled: boolean;
  submitting: boolean;
  confirmRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Review your plan
      </Text>
      {titles.map((title, index) => (
        <Text
          key={`${index}-${title}`}
          accessibilityLabel={`Proposed todo ${index + 1} of ${titles.length}: ${title}`}
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

function CompletedWorkflowScreen({
  created,
  onExit,
  backRef,
}: {
  created: { id: string; title: string }[];
  onExit: () => void;
  backRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Plan complete
      </Text>
      {created.map((todo, index) => (
        <Text
          key={todo.id}
          accessibilityLabel={`Created todo ${index + 1} of ${created.length}: ${todo.title}`}
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

function CancelledWorkflowScreen({
  onExit,
  backRef,
}: {
  onExit: () => void;
  backRef: ControlRef;
}) {
  return (
    <View style={styles.screen}>
      <Text accessibilityRole="header" accessibilityLiveRegion="polite" style={styles.heading}>
        Plan cancelled
      </Text>
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
