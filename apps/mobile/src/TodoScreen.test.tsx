import { fireEvent, render, screen } from "@testing-library/react-native";
import { TodoScreen } from "./TodoScreen";

it("starts empty with All selected", async () => {
  await render(<TodoScreen />);
  expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "All" })).toHaveProp("accessibilityState", { selected: true });
  expect(screen.getByRole("button", { name: "All" })).toHaveProp("aria-pressed", true);
});

it("validates, trims, and permits duplicate titles", async () => {
  await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");

  await fireEvent.changeText(input, "   ");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a todo title.");

  await fireEvent.changeText(input, ` ${"a".repeat(121)} `);
  await fireEvent(input, "submitEditing");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Todo titles must be 120 characters or fewer.",
  );

  const acceptedTitle = "b".repeat(120);
  await fireEvent.changeText(input, acceptedTitle);
  await fireEvent(input, "submitEditing");
  expect(screen.getByRole("checkbox", { name: acceptedTitle })).toBeTruthy();

  await fireEvent.changeText(input, "  Buy milk  ");
  await fireEvent(input, "submitEditing");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getAllByRole("checkbox", { name: "Buy milk" })).toHaveLength(2);
  expect(input).toHaveProp("value", "");
});

it("toggles todos and derives filtered views", async () => {
  await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");
  await fireEvent.changeText(input, "Write tests");
  await fireEvent(input, "submitEditing");

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp("accessibilityState", { checked: true });
  await fireEvent.press(screen.getByRole("button", { name: "Active" }));
  expect(screen.getByRole("button", { name: "Active" })).toHaveProp("accessibilityState", { selected: true });
  expect(screen.getByRole("button", { name: "Active" })).toHaveProp("aria-pressed", true);
  expect(screen.queryByText("Buy milk")).toBeNull();
  await fireEvent.press(screen.getByRole("checkbox", { name: "Write tests" }));
  expect(screen.getByText("No active todos.")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  expect(screen.getByRole("button", { name: "Completed" })).toHaveProp("accessibilityState", { selected: true });
  await fireEvent.changeText(input, "Hidden active todo");
  await fireEvent(input, "submitEditing");
  expect(screen.queryByText("Hidden active todo")).toBeNull();
  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  await fireEvent.press(screen.getByRole("checkbox", { name: "Write tests" }));
  expect(screen.getByText("No completed todos.")).toBeTruthy();
});

it("toggles a focused checkbox with Space", async () => {
  await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");

  const checkbox = screen.getByRole("checkbox", { name: "Buy milk" });
  const preventDefault = jest.fn();
  await fireEvent(checkbox, "keyDown", {
    nativeEvent: { key: " " },
    preventDefault,
  });

  expect(preventDefault).toHaveBeenCalled();
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    { checked: true },
  );
});

it("keeps duplicate rows independent and resets on remount", async () => {
  const view = await render(<TodoScreen />);
  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent(input, "submitEditing");
  const duplicates = screen.getAllByRole("checkbox", { name: "Buy milk" });
  await fireEvent.press(duplicates[0]);
  const updated = screen.getAllByRole("checkbox", { name: "Buy milk" });
  expect(updated[0]).toHaveProp("accessibilityState", { checked: true });
  expect(updated[1]).toHaveProp("accessibilityState", { checked: false });
  await view.unmount();
  await render(<TodoScreen />);
  expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "All" })).toHaveProp("accessibilityState", { selected: true });
});
