import { render, screen } from "@testing-library/react-native";
import App from "./App";

it("opens the local todo experience", async () => {
  await render(<App />);
  expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy();
  expect(screen.getByLabelText("Todo title")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
});
