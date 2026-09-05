import { type ComponentProps, type ComponentType, useRef, useState } from "react";
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

type Todo = { id: string; title: string; completed: boolean };
type TodoFilter = "all" | "active" | "completed";

const filters: { value: TodoFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
];

type PressableWithKeyDownProps = ComponentProps<typeof Pressable> & {
  onKeyDown?: (event: NativeSyntheticEvent<{ key: string }>) => void;
};

const PressableWithKeyDown = Pressable as ComponentType<PressableWithKeyDownProps>;

export function TodoScreen(): React.JSX.Element {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState<TodoFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const nextId = useRef(1);
  const input = useRef<TextInput>(null);

  const addTodo = () => {
    const title = draft.trim();
    if (!title) {
      setError("Enter a todo title.");
      return;
    }
    if (title.length > 120) {
      setError("Todo titles must be 120 characters or fewer.");
      return;
    }
    const id = `todo-${nextId.current++}`;
    setTodos((current) => [...current, { id, title, completed: false }]);
    setDraft("");
    setError(null);
    input.current?.focus();
  };

  const toggleTodo = (id: string) =>
    setTodos((current) =>
      current.map((todo) =>
        todo.id === id ? { ...todo, completed: !todo.completed } : todo,
      ),
    );

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
          value={draft}
          returnKeyType="done"
          submitBehavior="submit"
          onChangeText={setDraft}
          onSubmitEditing={addTodo}
          placeholder="What needs doing?"
          style={styles.input}
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Add todo"
          style={styles.addButton}
          onPress={addTodo}
        >
          <Text style={styles.addButtonText}>Add todo</Text>
        </Pressable>
      </View>
      {error && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
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
      {visible.length === 0 && <Text style={styles.empty}>{empty}</Text>}
      {visible.map((todo) => (
        <PressableWithKeyDown
          key={todo.id}
          accessibilityRole="checkbox"
          accessibilityLabel={todo.title}
          accessibilityState={{ checked: todo.completed }}
          aria-checked={todo.completed}
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
