import { type ComponentProps, type ComponentType, useEffect, useRef, useState } from "react";
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
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createTodo,
  deleteTodo,
  listTodos,
  normalizeTodoTitle,
  setTodoCompleted,
  setTodoTitle,
  TodoApiError,
  type Todo,
} from "./todos/todoApi";

type TodoFilter = "all" | "active" | "completed";

export type TodoScreenApi = {
  list: (options: { signal: AbortSignal }) => Promise<Todo[]>;
  create: (title: string) => Promise<Todo>;
  rename: (id: string, title: string) => Promise<Todo>;
  setCompleted: (id: string, completed: boolean) => Promise<Todo>;
  remove: (id: string) => Promise<void>;
};

const defaultApi: TodoScreenApi = {
  list: listTodos,
  create: (title) => createTodo(title),
  rename: (id, title) => setTodoTitle(id, title),
  setCompleted: (id, completed) => setTodoCompleted(id, completed),
  remove: (id) => deleteTodo(id),
};

const filters: { value: TodoFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
];

const UNKNOWN_MUTATION = "The result may be unknown. Refresh before making more changes.";
const VALIDATION_ERROR = "Check the todo title and try again.";
const NOT_FOUND_ERROR = "That todo no longer exists. Refresh the list.";
const LOAD_ERROR = "Could not load todos.";
const REFRESH_ERROR = "Could not refresh todos.";

type PressableWithKeyDownProps = ComponentProps<typeof Pressable> & {
  onKeyDown?: (event: NativeSyntheticEvent<{ key: string }>) => void;
};

const PressableWithKeyDown = Pressable as ComponentType<PressableWithKeyDownProps>;

function mutationError(error: unknown): string {
  if (error instanceof TodoApiError) {
    if (error.kind === "validation") return VALIDATION_ERROR;
    if (error.kind === "not-found") return NOT_FOUND_ERROR;
  }
  return UNKNOWN_MUTATION;
}

export function TodoScreen({ api = defaultApi }: { api?: TodoScreenApi } = {}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<TodoFilter>("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<{ message: string; atUpdatedAt: number } | null>(null);
  const [createFocusSignal, setCreateFocusSignal] = useState(0);
  const busy = useRef(false);
  const input = useRef<TextInput>(null);
  const focusedCreateSignal = useRef(0);

  const todosQuery = useQuery({
    queryKey: ["todos"],
    queryFn: ({ signal }) => api.list({ signal }),
  });
  const pendingWrites = useIsMutating({ mutationKey: ["todos", "write"] });

  const todos = todosQuery.data ?? [];
  const hasData = todosQuery.data !== undefined;
  const isFetching = todosQuery.isFetching;
  const isStale = todosQuery.isStale;
  const fresh = hasData && !isStale;
  const dataUpdatedAt = todosQuery.dataUpdatedAt;
  const writesDisabled = !fresh || isFetching || pendingWrites > 0;
  const visibleWriteError =
    writeError && dataUpdatedAt <= writeError.atUpdatedAt ? writeError.message : null;

  const handleMutationError = async (error: unknown): Promise<void> => {
    const atUpdatedAt = queryClient.getQueryState(["todos"])?.dataUpdatedAt ?? 0;
    setWriteError({ message: mutationError(error), atUpdatedAt });
    if (!(error instanceof TodoApiError && error.kind === "validation")) {
      await queryClient.invalidateQueries({ queryKey: ["todos"], refetchType: "none" });
    }
  };

  const createMutation = useMutation({
    mutationKey: ["todos", "write"],
    mutationFn: (title: string) => api.create(title),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["todos"] });
    },
    onSuccess: async (created) => {
      queryClient.setQueryData<Todo[]>(["todos"], (current) => [...(current ?? []), created]);
      setDraft("");
      setCreateFocusSignal((current) => current + 1);
      await queryClient.invalidateQueries({ queryKey: ["todos"] });
    },
    onError: handleMutationError,
    onSettled: () => {
      busy.current = false;
    },
  });

  const renameMutation = useMutation({
    mutationKey: ["todos", "write"],
    mutationFn: ({ id, title }: { id: string; title: string }) => api.rename(id, title),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["todos"] });
    },
    onSuccess: async (renamed) => {
      queryClient.setQueryData<Todo[]>(["todos"], (current) =>
        (current ?? []).map((item) => (item.id === renamed.id ? renamed : item)),
      );
      setEditingId(null);
      await queryClient.invalidateQueries({ queryKey: ["todos"] });
    },
    onError: handleMutationError,
    onSettled: () => {
      busy.current = false;
    },
  });

  const completeMutation = useMutation({
    mutationKey: ["todos", "write"],
    mutationFn: ({ id, completed }: { id: string; completed: boolean }) =>
      api.setCompleted(id, completed),
    onMutate: async ({ id, completed }) => {
      await queryClient.cancelQueries({ queryKey: ["todos"] });
      const snapshot = queryClient.getQueryData<Todo[]>(["todos"]);
      queryClient.setQueryData<Todo[]>(["todos"], (current) =>
        (current ?? []).map((item) => (item.id === id ? { ...item, completed } : item)),
      );
      return { snapshot };
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<Todo[]>(["todos"], (current) =>
        (current ?? []).map((item) => (item.id === updated.id ? updated : item)),
      );
      await queryClient.invalidateQueries({ queryKey: ["todos"] });
    },
    onError: async (error, _variables, context) => {
      if (context?.snapshot !== undefined) {
        queryClient.setQueryData(["todos"], context.snapshot);
      }
      await handleMutationError(error);
    },
    onSettled: () => {
      busy.current = false;
    },
  });

  const removeMutation = useMutation({
    mutationKey: ["todos", "write"],
    mutationFn: (id: string) => api.remove(id),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["todos"] });
    },
    onSuccess: async (_value, id) => {
      queryClient.setQueryData<Todo[]>(["todos"], (current) =>
        (current ?? []).filter((item) => item.id !== id),
      );
      setConfirmingId(null);
      await queryClient.invalidateQueries({ queryKey: ["todos"] });
    },
    onError: handleMutationError,
    onSettled: () => {
      busy.current = false;
    },
  });

  const syncGuard = () => {
    if (busy.current) return false;
    if (queryClient.isMutating({ mutationKey: ["todos", "write"] }) !== 0) return false;
    return true;
  };

  const refresh = () => {
    if (isFetching || pendingWrites > 0) return;
    if (!hasData) {
      void todosQuery.refetch();
      return;
    }
    void (async () => {
      await queryClient.invalidateQueries({ queryKey: ["todos"], refetchType: "none" });
      await todosQuery.refetch();
    })();
  };

  const startCreate = () => {
    if (writesDisabled || !syncGuard()) return;
    if (draft.trim() === "") {
      setWriteError({ message: "Enter a todo title.", atUpdatedAt: dataUpdatedAt });
      return;
    }
    const canonical = normalizeTodoTitle(draft);
    if (canonical === null) {
      setWriteError({ message: "Todo titles must be 120 characters or fewer.", atUpdatedAt: dataUpdatedAt });
      return;
    }
    busy.current = true;
    input.current?.blur();
    setWriteError(null);
    createMutation.mutate(canonical);
  };

  const toggleTodo = (id: string) => {
    if (writesDisabled || !syncGuard()) return;
    const current = todos.find((item) => item.id === id);
    if (!current) return;
    busy.current = true;
    setWriteError(null);
    completeMutation.mutate({ id, completed: !current.completed });
  };

  const startEdit = (id: string) => {
    if (writesDisabled || !syncGuard()) return;
    const current = todos.find((item) => item.id === id);
    if (!current) return;
    setConfirmingId(null);
    setEditingId(id);
    setEditDraft(current.title);
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const saveEdit = () => {
    if (writesDisabled || !syncGuard() || editingId === null) return;
    const canonical = normalizeTodoTitle(editDraft);
    if (canonical === null) {
      setWriteError({ message: VALIDATION_ERROR, atUpdatedAt: dataUpdatedAt });
      return;
    }
    busy.current = true;
    setWriteError(null);
    renameMutation.mutate({ id: editingId, title: canonical });
  };

  const askDelete = (id: string) => {
    if (writesDisabled || !syncGuard()) return;
    setEditingId(null);
    setConfirmingId(id);
  };

  const cancelDelete = () => {
    setConfirmingId(null);
  };

  const confirmDelete = () => {
    if (writesDisabled || !syncGuard() || confirmingId === null) return;
    busy.current = true;
    setWriteError(null);
    removeMutation.mutate(confirmingId);
  };

  const visible = todos.filter(
    (item) =>
      filter === "all" ||
      (filter === "completed" ? item.completed : !item.completed),
  );
  const empty =
    filter === "all"
      ? "No todos yet. Add one above."
      : filter === "active"
        ? "No active todos."
        : "No completed todos.";

  const initialError = !hasData && todosQuery.isError;
  const alert = initialError ? LOAD_ERROR : (visibleWriteError ?? (hasData && isStale && !isFetching && todosQuery.error ? REFRESH_ERROR : null));

  useEffect(() => {
    if (createFocusSignal === focusedCreateSignal.current || writesDisabled) return;
    input.current?.focus();
    focusedCreateSignal.current = createFocusSignal;
  }, [createFocusSignal, writesDisabled]);

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
        {alert && (
          <Text accessibilityRole="alert" style={styles.error}>
            {alert}
          </Text>
        )}
        {!hasData && todosQuery.isPending && <Text style={styles.status}>Loading todos…</Text>}
        {hasData && isFetching && <Text style={styles.status}>Refreshing todos…</Text>}
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
        {initialError && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Retry"
            disabled={isFetching || pendingWrites > 0}
            style={styles.refreshButton}
            onPress={refresh}
          >
            <Text style={styles.refreshButtonText}>Retry</Text>
          </Pressable>
        )}
        {hasData && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Refresh"
            disabled={isFetching || pendingWrites > 0}
            style={styles.refreshButton}
            onPress={refresh}
          >
            <Text style={styles.refreshButtonText}>Refresh</Text>
          </Pressable>
        )}
        {hasData && visible.length === 0 && <Text style={styles.empty}>{empty}</Text>}
        {visible.map((item) => (
          <View key={item.id} style={styles.todoRow}>
            <PressableWithKeyDown
              accessibilityRole="checkbox"
              accessibilityLabel={item.title}
              accessibilityState={{ checked: item.completed }}
              aria-checked={item.completed}
              disabled={writesDisabled}
              style={styles.checkboxHitbox}
              onPress={() => toggleTodo(item.id)}
              onKeyDown={(event) => {
                if (event.nativeEvent.key === " ") {
                  event.preventDefault();
                  toggleTodo(item.id);
                }
              }}
            >
              <View style={[styles.checkbox, item.completed && styles.checkedBox]}>
                {item.completed && <Text style={styles.checkmark}>✓</Text>}
              </View>
            </PressableWithKeyDown>
            <Text
              style={[styles.todoTitle, item.completed && styles.completedTitle]}
            >
              {item.title}
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Edit ${item.title}`}
              disabled={writesDisabled}
              style={styles.rowButton}
              onPress={() => startEdit(item.id)}
            >
              <Text style={styles.rowButtonText}>Edit</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Delete ${item.title}`}
              disabled={writesDisabled}
              style={styles.rowButton}
              onPress={() => askDelete(item.id)}
            >
              <Text style={styles.rowButtonText}>Delete</Text>
            </Pressable>
            {editingId === item.id && (
              <View style={styles.inlineEditor}>
                <TextInput
                  accessibilityLabel="Edit todo title"
                  editable={!writesDisabled}
                  value={editDraft}
                  onChangeText={setEditDraft}
                  style={styles.input}
                />
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Save changes"
                  disabled={writesDisabled}
                  style={styles.addButton}
                  onPress={saveEdit}
                >
                  <Text style={styles.addButtonText}>Save changes</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Cancel edit"
                  style={styles.refreshButton}
                  onPress={cancelEdit}
                >
                  <Text style={styles.refreshButtonText}>Cancel edit</Text>
                </Pressable>
              </View>
            )}
            {confirmingId === item.id && (
              <View style={styles.inlineEditor}>
                <Text style={styles.confirmText}>Delete &#8220;{item.title}&#8221;?</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Confirm delete"
                  disabled={writesDisabled}
                  style={styles.addButton}
                  onPress={confirmDelete}
                >
                  <Text style={styles.addButtonText}>Confirm delete</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Cancel delete"
                  style={styles.refreshButton}
                  onPress={cancelDelete}
                >
                  <Text style={styles.refreshButtonText}>Cancel delete</Text>
                </Pressable>
              </View>
            )}
          </View>
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
    minWidth: 44,
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
    minWidth: 44,
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
    minWidth: 44,
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
    borderColor: "#d5dce6",
    borderRadius: 10,
    borderWidth: 1,
    gap: 12,
    minHeight: 56,
    minWidth: 44,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  checkboxHitbox: {
    alignItems: "center",
    flexDirection: "row",
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
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
  rowButton: {
    alignItems: "center",
    borderColor: "#aeb9c9",
    borderRadius: 10,
    borderWidth: 1,
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 16,
  },
  rowButtonText: {
    color: "#173da0",
    fontSize: 16,
    fontWeight: "700",
  },
  inlineEditor: {
    gap: 10,
  },
  confirmText: {
    color: "#172033",
    fontSize: 16,
  },
});
