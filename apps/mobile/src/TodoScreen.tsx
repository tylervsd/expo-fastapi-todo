import { type ComponentProps, type ComponentType, useCallback, useEffect, useRef, useState } from "react";
import {
  type NativeSyntheticEvent,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  createTodo,
  listTodos,
  setTodoCompleted,
  TodoApiError,
  type Todo,
} from "./todos/todoApi";

type TodoFilter = "all" | "active" | "completed";
type LoadState = "loading" | "ready" | "initial-error" | "refreshing" | "refresh-error";
type Operation = "loading" | "creating" | "updating" | null;

export type TodoScreenApi = {
  list: (options: { signal: AbortSignal }) => Promise<Todo[]>;
  create: (title: string, options: { signal: AbortSignal }) => Promise<Todo>;
  setCompleted: (id: string, completed: boolean, options: { signal: AbortSignal }) => Promise<Todo>;
};

const defaultApi: TodoScreenApi = {
  list: listTodos,
  create: createTodo,
  setCompleted: setTodoCompleted,
};

const filters: { value: TodoFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
];

const UNKNOWN_MUTATION = "The result may be unknown. Refresh before making more changes.";
const VALIDATION_ERROR = "Check the todo title and try again.";
const NOT_FOUND_ERROR = "That todo no longer exists. Refresh the list.";

type PressableWithKeyDownProps = ComponentProps<typeof Pressable> & {
  onKeyDown?: (event: NativeSyntheticEvent<{ key: string }>) => void;
};

const PressableWithKeyDown = Pressable as ComponentType<PressableWithKeyDownProps>;

function isValidTitle(title: string): boolean {
  if (title.length === 0) return false;
  let codePoints = 0;
  for (let index = 0; index < title.length; index += 1) {
    const code = title.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = title.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return false;
    }
    codePoints += 1;
  }
  return codePoints <= 120;
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function mutationError(error: unknown): string {
  if (error instanceof TodoApiError) {
    if (error.kind === "validation") return VALIDATION_ERROR;
    if (error.kind === "not-found") return NOT_FOUND_ERROR;
  }
  return UNKNOWN_MUTATION;
}

export function TodoScreen({ api = defaultApi }: { api?: TodoScreenApi } = {}): React.JSX.Element {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<TodoFilter>("all");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [hasLoaded, setHasLoaded] = useState(false);
  const [operation, setOperation] = useState<Operation>("loading");
  const [error, setError] = useState<string | null>(null);
  const [writeLocked, setWriteLocked] = useState(false);
  const mounted = useRef(false);
  const attempt = useRef(0);
  const active = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const loaded = useRef(false);
  const input = useRef<TextInput>(null);

  const abortActiveAttempt = useCallback(() => {
    active.current?.abort();
  }, []);
  const invalidateAttempt = useCallback(() => {
    ++attempt.current;
  }, []);

  const runLoad = useCallback(() => {
    if (!mounted.current || busy.current) return;

    busy.current = true;
    const id = ++attempt.current;
    abortActiveAttempt();
    const controller = new AbortController();
    active.current = controller;
    const isRefresh = loaded.current;
    setOperation("loading");
    setLoadState(isRefresh ? "refreshing" : "loading");
    setError(null);

    void api.list({ signal: controller.signal }).then(
      (next) => {
        if (
          !mounted.current ||
          attempt.current !== id ||
          controller.signal.aborted
        ) {
          return;
        }
        setTodos(next);
        loaded.current = true;
        setHasLoaded(true);
        setWriteLocked(false);
        setLoadState("ready");
        setError(null);
      },
      (reason: unknown) => {
        if (
          !mounted.current ||
          attempt.current !== id ||
          controller.signal.aborted ||
          isAbortError(reason)
        ) {
          return;
        }
        setLoadState(isRefresh ? "refresh-error" : "initial-error");
        setError(isRefresh ? "Could not refresh todos." : "Could not load todos.");
        if (isRefresh) setWriteLocked(true);
      },
    ).finally(() => {
      if (attempt.current !== id) return;
      busy.current = false;
      active.current = null;
      setOperation(null);
    });
  }, [abortActiveAttempt, api]);

  useEffect(() => {
    mounted.current = true;
    runLoad();

    return () => {
      mounted.current = false;
      invalidateAttempt();
      abortActiveAttempt();
      active.current = null;
      busy.current = false;
    };
  }, [abortActiveAttempt, invalidateAttempt, runLoad]);

  const startCreate = () => {
    if (!mounted.current || !hasLoaded || loadState !== "ready" || writeLocked || busy.current) {
      return;
    }
    const title = draft.trim();
    if (!title) {
      setError("Enter a todo title.");
      return;
    }
    if (!isValidTitle(title)) {
      setError("Todo titles must be 120 characters or fewer.");
      return;
    }

    busy.current = true;
    const id = ++attempt.current;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const draftAtSubmit = draft;
    setOperation("creating");
    setError(null);

    void api.create(title, { signal: controller.signal }).then(
      (created) => {
        if (
          !mounted.current ||
          attempt.current !== id ||
          controller.signal.aborted
        ) {
          return;
        }
        setTodos((current) => [...current, created]);
        setDraft((current) => (current === draftAtSubmit ? "" : current));
        setError(null);
        input.current?.focus();
      },
      (reason: unknown) => {
        if (
          !mounted.current ||
          attempt.current !== id ||
          controller.signal.aborted ||
          isAbortError(reason)
        ) {
          return;
        }
        const message = mutationError(reason);
        setError(message);
        if (message === UNKNOWN_MUTATION) setWriteLocked(true);
      },
    ).finally(() => {
      if (attempt.current !== id) return;
      busy.current = false;
      active.current = null;
      setOperation(null);
    });
  };

  const toggleTodo = (id: string) => {
    if (!mounted.current || !hasLoaded || loadState !== "ready" || writeLocked || busy.current) {
      return;
    }
    const current = todos.find((todo) => todo.id === id);
    if (!current) return;
    const desired = !current.completed;
    busy.current = true;
    const operationId = ++attempt.current;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setOperation("updating");
    setError(null);

    void api.setCompleted(id, desired, { signal: controller.signal }).then(
      (updated) => {
        if (
          !mounted.current ||
          attempt.current !== operationId ||
          controller.signal.aborted
        ) {
          return;
        }
        setTodos((currentTodos) =>
          currentTodos.map((todo) => (todo.id === id ? updated : todo)),
        );
        setError(null);
      },
      (reason: unknown) => {
        if (
          !mounted.current ||
          attempt.current !== operationId ||
          controller.signal.aborted ||
          isAbortError(reason)
        ) {
          return;
        }
        const message = mutationError(reason);
        setError(message);
        if (message === UNKNOWN_MUTATION) setWriteLocked(true);
      },
    ).finally(() => {
      if (attempt.current !== operationId) return;
      busy.current = false;
      active.current = null;
      setOperation(null);
    });
  };

  const visible = todos.filter(
    (todo) =>
      filter === "all" ||
      (filter === "completed" ? todo.completed : !todo.completed),
  );
  const empty =
    filter === "all"
      ? "No todos yet. Add one above."
      : filter === "active"
        ? "No active todos."
        : "No completed todos.";
  const writesDisabled =
    !hasLoaded || loadState !== "ready" || writeLocked || operation !== null;
  const rowsDisabled = writesDisabled;

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        automaticallyAdjustKeyboardInsets
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}
      >
        <Text accessibilityRole="header" style={styles.heading}>
          Todos
        </Text>
        <View style={styles.form}>
          <Text style={styles.fieldLabel}>Todo title</Text>
          <TextInput
            ref={input}
            accessibilityLabel="Todo title"
            editable={!writesDisabled}
            value={draft}
            returnKeyType="done"
            submitBehavior="submit"
            onChangeText={setDraft}
            onSubmitEditing={startCreate}
            placeholder="What needs doing?"
            style={styles.input}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Add todo"
            disabled={writesDisabled}
            style={styles.addButton}
            onPress={startCreate}
          >
            <Text style={styles.addButtonText}>Add todo</Text>
          </Pressable>
        </View>
        {error && (
          <Text accessibilityRole="alert" style={styles.error}>
            {error}
          </Text>
        )}
        {loadState === "loading" && <Text style={styles.status}>Loading todos…</Text>}
        {loadState === "refreshing" && <Text style={styles.status}>Refreshing todos…</Text>}
        <View style={styles.filters}>
          {filters.map(({ value, label }) => (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: filter === value }}
              aria-pressed={filter === value}
              style={[styles.filterButton, filter === value && styles.selectedFilter]}
              onPress={() => setFilter(value)}
            >
              <Text
                style={[styles.filterText, filter === value && styles.selectedFilterText]}
              >
                {label}
              </Text>
            </Pressable>
          ))}
        </View>
        {loadState === "initial-error" && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Retry"
            disabled={operation !== null}
            style={styles.refreshButton}
            onPress={runLoad}
          >
            <Text style={styles.refreshButtonText}>Retry</Text>
          </Pressable>
        )}
        {hasLoaded && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Refresh"
            disabled={operation !== null}
            style={styles.refreshButton}
            onPress={runLoad}
          >
            <Text style={styles.refreshButtonText}>Refresh</Text>
          </Pressable>
        )}
        {hasLoaded && visible.length === 0 && <Text style={styles.empty}>{empty}</Text>}
        {visible.map((todo) => (
          <PressableWithKeyDown
            key={todo.id}
            accessibilityRole="checkbox"
            accessibilityLabel={todo.title}
            accessibilityState={{ checked: todo.completed }}
            aria-checked={todo.completed}
            disabled={rowsDisabled}
            style={styles.todoRow}
            onPress={() => toggleTodo(todo.id)}
            onKeyDown={(event) => {
              if (event.nativeEvent.key === " ") {
                event.preventDefault();
                toggleTodo(todo.id);
              }
            }}
          >
            <View style={[styles.checkbox, todo.completed && styles.checkedBox]}>
              {todo.completed && <Text style={styles.checkmark}>✓</Text>}
            </View>
            <Text
              style={[styles.todoTitle, todo.completed && styles.completedTitle]}
            >
              {todo.title}
            </Text>
          </PressableWithKeyDown>
        ))}
      </ScrollView>
    </SafeAreaView>
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
  heading: {
    color: "#172033",
    fontSize: 32,
    fontWeight: "700",
  },
  form: {
    gap: 10,
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
  addButton: {
    alignItems: "center",
    backgroundColor: "#2457d6",
    borderRadius: 10,
    justifyContent: "center",
    minHeight: 48,
    paddingHorizontal: 16,
  },
  addButtonText: {
    color: "#ffffff",
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
  filters: {
    flexDirection: "row",
    gap: 8,
  },
  filterButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 20,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: 16,
  },
  selectedFilter: {
    backgroundColor: "#e7edff",
    borderColor: "#2457d6",
  },
  filterText: {
    color: "#42526b",
    fontSize: 15,
    fontWeight: "600",
  },
  selectedFilterText: {
    color: "#173da0",
  },
  refreshButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    paddingHorizontal: 16,
  },
  refreshButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
  empty: {
    color: "#66758a",
    fontSize: 16,
    paddingVertical: 12,
  },
  todoRow: {
    alignItems: "center",
    borderColor: "#d5dce6",
    borderRadius: 10,
    borderWidth: 1,
    flexDirection: "row",
    gap: 12,
    minHeight: 56,
    paddingHorizontal: 14,
  },
  checkbox: {
    alignItems: "center",
    borderColor: "#718096",
    borderRadius: 6,
    borderWidth: 2,
    height: 24,
    justifyContent: "center",
    width: 24,
  },
  checkedBox: {
    backgroundColor: "#2457d6",
    borderColor: "#2457d6",
  },
  checkmark: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  todoTitle: {
    color: "#172033",
    flex: 1,
    fontSize: 17,
  },
  completedTitle: {
    color: "#66758a",
    textDecorationLine: "line-through",
  },
});
